"""Exercise CLI behavior without touching real accounts or applications."""

import os
from pathlib import Path
import plistlib
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "bin" / "multicodex"

# Real command handlers, with app operations redirected to a temporary sandbox.
HARNESS = r'''
source "$TEST_CLI"
legacy_codex_home() { printf '%s/legacy-profiles/%s\n' "$TEST_DIR" "$1"; }
data_dir() { printf '%s/data/%s\n' "$TEST_DIR" "$1"; }
profile_app() { printf '%s/apps/Codex %s.app\n' "$TEST_DIR" "$1"; }
app_version() { printf '1.2.3\n'; }
app_build() { printf '%s\n' "${TEST_BUILD:-10}"; }
refresh_icon_cache() { :; }
build_profile_app() {
    printf '%s\n' "$1" >> "$TEST_DIR/builds"
    mkdir -p "$(profile_app "$1")/Contents/MacOS"
    # The real build installs a launcher as the bundle's main executable, and
    # cmd_sync treats a bundle without one as stale. Mirror that here so the
    # stub keeps the contract sync relies on.
    : > "$(profile_app "$1")/Contents/MacOS/$LAUNCHER_NAME"
    chmod +x "$(profile_app "$1")/Contents/MacOS/$LAUNCHER_NAME"
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
        self.assertEqual(result.stdout.strip(), "multicodex 1.0.1")

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

    def moved_session(self, *, archived=False):
        self.create()
        profile = self.root / "profiles/work"
        old = self.root / "legacy-profiles/work"
        relative = Path("archived_sessions" if archived else "sessions") / "rollout-test.jsonl"
        session = profile / relative
        session.parent.mkdir()
        session.write_text('{"type":"session_meta"}\n')
        with sqlite3.connect(profile / "state_5.sqlite") as db:
            db.execute("CREATE TABLE threads (id TEXT, rollout_path TEXT)")
            db.execute("INSERT INTO threads VALUES (?, ?)", ("test", str(old / relative)))
        return profile, old, relative

    def test_launch_repairs_moved_session_without_rewriting_database(self):
        profile, old, relative = self.moved_session()
        original_db = (profile / "state_5.sqlite").read_bytes()
        self.assertFalse((old / relative).exists())
        self.run_shell("main launch work")
        self.assertEqual((old / relative).read_bytes(), (profile / relative).read_bytes())
        self.assertEqual(old.resolve(), profile.resolve())
        self.assertEqual((profile / "state_5.sqlite").read_bytes(), original_db)
        self.run_shell("main launch work; main repair work")
        self.assertEqual(old.resolve(), profile.resolve())

    def test_launch_repairs_archived_sessions(self):
        profile, old, relative = self.moved_session(archived=True)
        self.run_shell("main launch work")
        self.assertEqual((old / relative).read_bytes(), (profile / relative).read_bytes())

    def test_launch_does_not_claim_old_path_without_matching_session(self):
        profile, old, relative = self.moved_session()
        (profile / relative).unlink()
        self.run_shell("main launch work")
        self.assertFalse(old.is_symlink())
        # An index belonging to a different old profile must not claim this name.
        (profile / relative).write_text("session")
        with sqlite3.connect(profile / "state_5.sqlite") as db:
            db.execute("UPDATE threads SET rollout_path = ?", (str(old.parent / "personal" / relative),))
        self.run_shell("main launch work")
        self.assertFalse(old.is_symlink())

    def test_launch_without_readable_index_still_opens_app(self):
        self.create()
        (self.root / "profiles/work/state_5.sqlite").write_text("invalid database")
        self.run_shell("main launch work")
        self.assertTrue((self.root / "launch-args").exists())
        self.assertFalse((self.root / "legacy-profiles/work").is_symlink())

    def test_sessions_dispatches_explicit_pair(self):
        self.run_shell(r'''
python3() { printf '%s\n' "$@" > "$TEST_DIR/sync-args"; }
main sessions enable work --with personal
''')
        self.assertEqual((self.root / "sync-args").read_text().splitlines()[:6], [
            str(REPO / "tools/session_sync.py"), "enable", "--left",
            str(self.root / "profiles/work"), "--right", str(self.root / "profiles/personal"),
        ])
        for command in ("main sessions", "main sessions enable", "main sessions sync ../escape",
                        "main sessions enable work --with", "main sessions enable work --with ../escape"):
            self.run_shell(command, success=False)

    def test_repair_preserves_occupied_old_paths_and_launch_continues(self):
        profile, old, relative = self.moved_session()
        old.mkdir(parents=True)
        sentinel = old / "keep.txt"
        sentinel.write_text("other data")
        self.run_shell("main repair work", success=False)
        result = self.run_shell("main launch work")
        self.assertIn("occupied", result.stderr)
        self.assertEqual(sentinel.read_text(), "other data")
        sentinel.unlink()
        old.rmdir()
        for destination in (self.root / "missing", self.root / "source.app"):
            with self.subTest(destination=destination):
                old.symlink_to(destination, target_is_directory=True)
                self.run_shell("main repair work", success=False)
                self.assertEqual(old.readlink(), destination)
                old.unlink()

    def test_repair_accepts_custom_old_home_with_spaces_and_quotes(self):
        profile, _, relative = self.moved_session()
        old = self.root / "old user's profiles" / "work"
        self.env["TEST_OLD_HOME"] = str(old)
        self.run_shell('main repair work --from "$TEST_OLD_HOME"')
        self.assertEqual((old / relative).read_bytes(), (profile / relative).read_bytes())
        self.run_shell('main repair work --from "$TEST_OLD_HOME"')

    def test_launch_handles_quoted_legacy_path(self):
        profile, _, relative = self.moved_session()
        old = self.root / "old user's profiles" / "work"
        self.env["TEST_OLD_HOME"] = str(old)
        with sqlite3.connect(profile / "state_5.sqlite") as db:
            db.execute("UPDATE threads SET rollout_path = ?", (str(old / relative),))
        self.run_shell('legacy_codex_home() { printf "%s\\n" "$TEST_OLD_HOME"; }; main launch work')
        self.assertEqual((old / relative).read_bytes(), (profile / relative).read_bytes())

    def test_repair_rejects_missing_sessions_and_invalid_arguments(self):
        self.create()
        for command in (
            "main repair", "main repair ../escape", "main repair absent",
            "main repair work --from", "main repair work --unknown /old",
            "main repair work --from relative/path", "main repair work",
        ):
            with self.subTest(command=command):
                self.run_shell(command, success=False)
        self.assertFalse((self.root / "legacy-profiles").exists())

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

    def test_sync_rebuilds_a_bundle_without_a_launcher(self):
        # Profiles built before the launcher existed open the shared default
        # data directory, hand off to whichever instance already owns it and
        # exit. Sync must treat them as stale even when the version matches.
        self.create()
        launcher = self.root / "apps/Codex work.app/Contents/MacOS" / "multicodex-launcher"
        launcher.unlink()
        self.run_shell("cmd_sync work")
        self.assertEqual((self.root / "builds").read_text().splitlines(), ["work", "work"])
        self.assertTrue(launcher.exists())

    def test_sync_force_rebuilds_an_up_to_date_profile(self):
        self.create()
        self.run_shell("cmd_sync work")
        self.assertEqual((self.root / "builds").read_text().splitlines(), ["work"])
        self.run_shell("cmd_sync --force work")
        self.assertEqual((self.root / "builds").read_text().splitlines(), ["work", "work"])

    def test_launch_all_reports_failure_and_continues(self):
        self.create("broken", "red")
        self.create("work", "blue")
        # The bundle now holds a launcher, so remove the tree rather than the
        # bare directory.
        shutil.rmtree(self.root / "apps/Codex broken.app")
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


class URLSchemeNamespacing(unittest.TestCase):
    """A clone must not claim the schemes the official app answers on."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="multicodex-plist-")
        self.addCleanup(self.temp.cleanup)
        self.plist = Path(self.temp.name) / "Info.plist"

    def write(self, url_types):
        with open(self.plist, "wb") as handle:
            plistlib.dump({"CFBundleURLTypes": url_types}, handle)

    def namespace(self, name):
        result = subprocess.run(
            ["/bin/bash", "-c",
             f'source "{CLI}"\nnamespace_url_schemes "{self.plist}" "{name}"'],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with open(self.plist, "rb") as handle:
            return plistlib.load(handle)["CFBundleURLTypes"]

    def test_private_scheme_replaces_the_shared_ones(self):
        # The shape the official app ships: one entry claiming codex and the web.
        self.write([{"CFBundleURLName": "ChatGPT",
                     "CFBundleURLSchemes": ["codex", "http", "https"]}])
        types = self.namespace("work")
        self.assertEqual(len(types), 1)
        self.assertEqual(types[0]["CFBundleURLSchemes"], ["codex-work"])
        self.assertEqual(types[0]["CFBundleURLName"], "local.multicodex.work")

    def test_web_only_entries_are_dropped(self):
        self.write([
            {"CFBundleURLName": "ChatGPT", "CFBundleURLSchemes": ["http", "HTTPS"]},
            {"CFBundleURLName": "ChatGPT", "CFBundleURLSchemes": ["codex", "chatgpt"]},
        ])
        types = self.namespace("work")
        self.assertEqual(len(types), 1)
        self.assertEqual(types[0]["CFBundleURLSchemes"], ["codex-work", "chatgpt-work"])

    def test_names_are_folded_into_a_valid_scheme(self):
        # Profile names admit '_' and capitals; URL schemes admit neither.
        self.write([{"CFBundleURLName": "ChatGPT", "CFBundleURLSchemes": ["codex"]}])
        types = self.namespace("My_Work")
        self.assertEqual(types[0]["CFBundleURLSchemes"], ["codex-my-work"])


if __name__ == "__main__":
    unittest.main()
