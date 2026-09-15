"""Exercise CLI behavior without touching real accounts or applications."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "bin" / "multicodex"

# Real command handlers, with app operations redirected to a temporary sandbox.
HARNESS = r'''
source "$TEST_CLI"
data_dir() { printf '%s/data/%s\n' "$TEST_DIR" "$1"; }
profile_app() { printf '%s/apps/Codex %s.app\n' "$TEST_DIR" "$1"; }
app_version() { printf '1.2.3\n'; }
app_build() { printf '%s\n' "${TEST_BUILD:-10}"; }
refresh_icon_cache() { :; }
build_profile_app() {
    printf '%s\n' "$1" >> "$TEST_DIR/builds"
    mkdir -p "$(profile_app "$1")"
    info "mock build progress"
    printf '%s\n' "$(profile_app "$1")"
}
open() { printf '%s\n' "$@" >> "$TEST_DIR/launch-args"; }
'''


class CLIBehavior(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="multicodex-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "source.app").mkdir()
        self.env = dict(os.environ)
        self.env.update(
            TEST_CLI=str(CLI),
            TEST_DIR=str(self.root),
            MULTICODEX_ROOT=str(self.root / "profiles"),
            MULTICODEX_APP=str(self.root / "source.app"),
        )

    def run_shell(self, script, *, input=None, success=True):
        result = subprocess.run(
            ["/bin/bash", "-c", HARNESS + "\n" + script],
            env=self.env,
            text=True,
            input=input,
            capture_output=True,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def create(self, name="work", color="blue"):
        return self.run_shell(f"cmd_create {name} --color {color}")

    def test_help_and_version(self):
        result = subprocess.run([str(CLI), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("multicodex sync", result.stdout)
        result = subprocess.run([str(CLI), "--version"], capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), "multicodex 1.0.0")

    def test_create_metadata_and_private_directories(self):
        result = self.create()
        profile = self.root / "profiles/work"
        self.assertEqual(
            (profile / ".multicodex").read_text(),
            "color=blue\nsource_version=1.2.3\nsource_build=10\n",
        )
        self.assertEqual(profile.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.root / "data/work").stat().st_mode & 0o777, 0o700)
        self.assertIn("mock build progress", result.stdout)
        self.assertIn(f"app         {self.root}/apps/Codex work.app", result.stdout)
        self.assertNotIn("or open", result.stdout)

    def test_automatic_colors_are_distinct(self):
        self.run_shell("cmd_create work; cmd_create personal")
        self.assertIn("color=blue", (self.root / "profiles/work/.multicodex").read_text())
        self.assertIn("color=green", (self.root / "profiles/personal/.multicodex").read_text())

    def test_launch_supplies_both_isolation_variables(self):
        self.create()
        self.create("personal", "green")
        self.run_shell("cmd_launch work; cmd_launch personal")
        args = (self.root / "launch-args").read_text().splitlines()
        expected = []
        for name in ("work", "personal"):
            expected.extend([
                "-n", "--env", f"CODEX_HOME={self.root}/profiles/{name}",
                "--env", f"CODEX_ELECTRON_USER_DATA_PATH={self.root}/data/{name}",
                f"{self.root}/apps/Codex {name}.app", "--args",
                f"--user-data-dir={self.root}/data/{name}",
            ])
        self.assertEqual(args, expected)

    def test_sync_detects_new_build_and_preserves_data(self):
        self.create()
        sentinel = self.root / "profiles/work/session.txt"
        sentinel.write_text("local test session")
        self.run_shell("cmd_sync work")
        self.assertEqual((self.root / "builds").read_text().splitlines(), ["work"])
        self.env["TEST_BUILD"] = "11"
        self.assertIn("stale", self.run_shell("cmd_list").stdout)
        self.run_shell("cmd_sync work")
        self.assertEqual((self.root / "builds").read_text().splitlines(), ["work", "work"])
        self.assertEqual(sentinel.read_text(), "local test session")
        self.assertIn("source_build=11", (self.root / "profiles/work/.multicodex").read_text())
        self.assertIn("up to date", self.run_shell("cmd_list").stdout)

    def test_launch_all_skips_running_profiles(self):
        self.create()
        self.create("personal", "green")
        result = self.run_shell(r'''
profile_running() {
    [ "$1" = "work" ] || [ -f "$TEST_DIR/started-$1" ]
}
open() { touch "$TEST_DIR/started-personal"; }
sleep() { :; }
main launch --all
''')
        self.assertIn("work already running", result.stdout)
        self.assertIn("1 started, 0 failed", result.stdout)

    def test_launch_all_reports_failure_and_continues(self):
        self.create("broken", "red")
        self.create("work", "blue")
        (self.root / "apps/Codex broken.app").rmdir()
        result = self.run_shell(r'''
profile_running() { [ -f "$TEST_DIR/started-$1" ]; }
open() { touch "$TEST_DIR/started-work"; }
sleep() { :; }
main launch --all
''', success=False)
        self.assertIn("1 started, 1 failed", result.stdout)
        self.assertIn("broken could not launch", result.stderr)
        self.assertTrue((self.root / "started-work").exists())

    def test_running_detection_matches_literal_profile_path(self):
        script = r'''
ps() { cat "$TEST_DIR/processes"; }
profile_running 'client.one'
'''
        process_file = self.root / "processes"
        for wrong in (
            f"{self.root}/apps/Codex clientXone.app/Contents/MacOS/ChatGPT",
            f"{self.root}/apps/Codex client.one.app/Contents/MacOS/helper/nested",
            f"/other/apps/Codex client.one.app/Contents/MacOS/ChatGPT",
        ):
            process_file.write_text(wrong + "\n")
            self.run_shell(script, success=False)
        process_file.write_text(
            f"{self.root}/apps/Codex client.one.app/Contents/MacOS/ChatGPT\n"
        )
        self.run_shell(script)

    def test_sync_migrates_legacy_metadata(self):
        self.create()
        metadata = self.root / "profiles/work/.multicodex"
        metadata.write_text("color=blue\nsource_version=1.2.3\n")
        self.run_shell("cmd_sync work")
        self.assertIn("source_build=10", metadata.read_text())
        self.assertEqual((self.root / "builds").read_text().splitlines(), ["work", "work"])

    def test_invalid_arguments_fail_before_creating_profiles(self):
        for command in (
            "cmd_create ../escape", "cmd_create work --color",
            "cmd_create work personal", "cmd_create work --color invalid",
            "cmd_launch ../escape", "cmd_sync ../escape",
            "cmd_sync work personal", "cmd_remove ../escape",
        ):
            with self.subTest(command=command):
                self.run_shell(command, success=False)
        self.assertFalse((self.root / "profiles").exists())

    def test_remove_requires_matching_confirmation(self):
        self.create()
        self.create("personal", "green")
        self.run_shell("cmd_remove work", input="wrong\n", success=False)
        self.assertTrue((self.root / "profiles/work").exists())
        self.run_shell("cmd_remove work", input="work\n")
        self.assertFalse((self.root / "profiles/work").exists())
        self.assertFalse((self.root / "data/work").exists())
        self.assertFalse((self.root / "apps/Codex work.app").exists())
        self.assertTrue((self.root / "profiles/personal").exists())

    def test_download_identity_verification(self):
        mock = r'''
codesign() {
    if [ "$1" = "--verify" ]; then return "${TEST_VERIFY_EXIT:-0}"; fi
    printf 'TeamIdentifier=%s\nIdentifier=%s\n' \
        "${TEST_TEAM:-2DC432GLL2}" "${TEST_IDENTIFIER:-com.openai.codex}" >&2
}
verify_openai_bundle "$APP"
'''
        self.run_shell(mock)
        for variable, value in (
            ("TEST_TEAM", "WRONGTEAM"),
            ("TEST_IDENTIFIER", "com.example.other"),
            ("TEST_VERIFY_EXIT", "1"),
        ):
            with self.subTest(variable=variable):
                self.env[variable] = value
                self.run_shell(mock, success=False)
                del self.env[variable]


if __name__ == "__main__":
    unittest.main()
