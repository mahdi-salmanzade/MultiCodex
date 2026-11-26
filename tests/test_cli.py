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
    printf '%s\n' "${3:-own}" >> "$TEST_DIR/build-runtimes"
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

    def run_shell(self, script, *, input=None, success=True, harness=HARNESS):
        result = subprocess.run(
            ["/bin/bash", "-c", harness + "\n" + script],
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
            "color=blue\nsource_version=1.2.3\nsource_build=10\nruntime=own\n",
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

    def index_thread(self, home, thread):
        home.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(home / "state_5.sqlite") as db:
            db.execute("CREATE TABLE IF NOT EXISTS threads (id TEXT, rollout_path TEXT)")
            db.execute("INSERT INTO threads VALUES (?, ?)", (thread, "/unused"))

    THREAD = "01a13644-6619-79b2-a18d-e9b6e9ea76bd"

    def test_open_hands_the_link_to_the_chosen_profile(self):
        self.create()
        self.index_thread(self.root / "profiles/work", self.THREAD)
        app = f"{self.root}/apps/Codex work.app"
        fresh = ["-a", app, "--env", f"CODEX_HOME={self.root}/profiles/work",
                 "--env", f"CODEX_ELECTRON_USER_DATA_PATH={self.root}/data/work",
                 f"codex://threads/{self.THREAD}", "--args",
                 f"--user-data-dir={self.root}/data/work"]
        result = self.run_shell(f"profile_running() {{ return 1; }}; main open work codex://threads/{self.THREAD}")
        self.assertEqual((self.root / "launch-args").read_text().splitlines(), fresh)
        self.assertEqual(result.stderr, "")
        # A running profile takes the link as it is; a link written for the
        # profile's private scheme is the same link, which the app only accepts
        # under codex:.
        (self.root / "launch-args").unlink()
        self.run_shell(f"profile_running() {{ return 0; }}; main open work CODEX-work://threads/{self.THREAD}?view=review")
        self.assertEqual((self.root / "launch-args").read_text().splitlines(),
                         ["-a", app, f"codex://threads/{self.THREAD}?view=review"])

    def test_open_says_where_an_unshared_chat_lives(self):
        self.create()
        self.create("personal", "green")
        self.env["HOME"] = str(self.root)
        self.index_thread(self.root / "profiles/work", "00000000-0000-0000-0000-000000000000")
        link = f"codex://threads/{self.THREAD}"
        script = f"profile_running() {{ return 1; }}; main open work {link}"
        self.assertIn("not in any profile", self.run_shell(script).stderr)
        self.index_thread(self.root / "profiles/personal", self.THREAD)
        self.assertIn("multicodex sessions sync work --with personal", self.run_shell(script).stderr)
        self.index_thread(self.root / ".codex", self.THREAD)
        result = self.run_shell(script)
        self.assertIn("belongs to 'default'", result.stderr)
        self.assertTrue(result.stderr.rstrip().endswith("multicodex sessions sync work"))
        # The link is still delivered: the index check is advice, not a gate.
        self.assertEqual(len((self.root / "launch-args").read_text().splitlines()), 27)

    def test_open_default_targets_the_official_app(self):
        self.run_shell("main open default codex://settings")
        self.assertEqual((self.root / "launch-args").read_text().splitlines(),
                         ["-a", str(self.root / "source.app"), "codex://settings"])

    def test_open_rejects_anything_but_a_codex_link(self):
        self.create()
        for command in (
            "main open", "main open work", "main open work codex://a extra",
            "main open ../escape codex://threads/new", "main open absent codex://threads/new",
            "main open work https://example.com/", "main open work codex:threads",
            "main open work 'codex://'", "main open work 'codex://threads/a b'",
            "main open work 'codex://threads/new#x'", "main open work 'codex-wo rk://x'",
            "main open work -a", "main open work 'codexx://threads/new'",
        ):
            with self.subTest(command=command):
                self.run_shell(command, success=False)
        self.assertFalse((self.root / "launch-args").exists())

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

    def test_launch_repairs_compressed_sessions(self):
        profile, old, relative = self.moved_session()
        path = profile / relative
        path.rename(path.with_name(path.name + ".zst"))
        self.run_shell("main launch work")
        self.assertEqual(old.resolve(), profile.resolve())

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

    def test_runtime_is_chosen_per_profile_and_survives_sync(self):
        self.run_shell("cmd_create work --runtime official; cmd_create personal")
        meta = self.root / "profiles/work/.multicodex"
        self.assertIn("runtime=official", meta.read_text())
        self.assertIn("up to date (official runtime)", self.run_shell("cmd_list").stdout)
        # An ordinary sync keeps each profile's choice, rebuilding neither.
        self.run_shell("cmd_sync")
        self.env["TEST_BUILD"] = "11"
        self.run_shell("cmd_sync")
        self.assertEqual((self.root / "build-runtimes").read_text().split(),
                         ["official", "own", "own", "official"])
        # Changing the runtime rebuilds only the profiles it changes.
        self.run_shell("cmd_sync --runtime official")
        self.assertEqual((self.root / "builds").read_text().split()[4:], ["personal"])
        self.assertIn("runtime=official", (self.root / "profiles/personal/.multicodex").read_text())
        self.run_shell("cmd_sync --runtime=own work")
        self.assertIn("runtime=own", meta.read_text())
        for command in ("cmd_create other --runtime", "cmd_create other --runtime patched",
                        "cmd_sync --runtime", "cmd_sync --runtime patched"):
            self.run_shell(command, success=False)
        self.assertFalse((self.root / "profiles/other").exists())

    def test_open_restarts_the_official_app_on_an_official_runtime_profile(self):
        self.run_shell("cmd_create work --runtime official")
        self.index_thread(self.root / "profiles/work", self.THREAD)
        self.run_shell(f"main open work codex://threads/{self.THREAD}")
        self.assertEqual((self.root / "launch-args").read_text().splitlines(), [
            "-n", "-a", str(self.root / "source.app"),
            "--env", f"CODEX_HOME={self.root}/profiles/work",
            "--env", f"CODEX_ELECTRON_USER_DATA_PATH={self.root}/data/work",
            "--args", f"--user-data-dir={self.root}/data/work",
            f"codex://threads/{self.THREAD}"])

    def test_launchers_start_the_right_binary(self):
        script = r'''
profile_app() { printf '%s/apps/Codex %s.app\n' "$TEST_DIR" "$1"; }
profile_running() { return 1; }
signing_identity() { printf -- '-\n'; }
codesign() { :; }
register_app() { :; }
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
printf '#!/bin/sh\nprintf "%%s\\n" "$0" "$CODEX_HOME" "$@"\n' > "$APP/Contents/MacOS/Chat GPT"
chmod +x "$APP/Contents/MacOS/Chat GPT"
/usr/libexec/PlistBuddy -c "Add :CFBundleExecutable string 'Chat GPT'" "$APP/Contents/Info.plist" >/dev/null
build_profile_app own blue own >/dev/null
build_profile_app tools green official >/dev/null
HOME="$TEST_DIR/home" "$(profile_app own)/Contents/MacOS/$LAUNCHER_NAME" one
HOME="$TEST_DIR/home" "$(profile_app tools)/Contents/MacOS/$LAUNCHER_NAME" two
rm -rf "$APP"
HOME="$TEST_DIR/home" "$(profile_app tools)/Contents/MacOS/$LAUNCHER_NAME" 2>&1 || echo "exit $?"
'''
        self.env["MULTICODEX_APP"] = str(self.root / "source app.app")
        lines = self.run_shell(script, harness='source "$TEST_CLI"').stdout.splitlines()
        data = f"{self.root}/home/Library/Application Support/MultiCodex"
        self.assertEqual(lines[:8], [
            f"{self.root}/apps/Codex own.app/Contents/MacOS/Chat GPT",
            f"{self.root}/profiles/own", f"--user-data-dir={data}/own", "one",
            f"{self.root}/source app.app/Contents/MacOS/Chat GPT",
            f"{self.root}/profiles/tools", f"--user-data-dir={data}/tools", "two",
        ])
        self.assertIn("multicodex sync tools", lines[-2])
        self.assertEqual(lines[-1], "exit 1")

    def test_running_detection_finds_the_official_app_on_profile_data(self):
        script = r'''
ps() { cat "$TEST_DIR/processes"; }
profile_running work
'''
        data = f"{self.root}/data/work"
        process_file = self.root / "processes"
        for wrong in (
            f"/Applications/ChatGPT.app/Contents/MacOS/ChatGPT",
            f"/Applications/ChatGPT.app/Contents/MacOS/ChatGPT --user-data-dir={data}2",
            f"/Applications/ChatGPT.app/Contents/Frameworks/H.app/Contents/MacOS/H --user-data-dir={data}",
        ):
            process_file.write_text(wrong + "\n")
            self.run_shell(script, success=False)
        for right in (
            f"/Applications/ChatGPT.app/Contents/MacOS/ChatGPT --user-data-dir={data}",
            f"/Applications/ChatGPT.app/Contents/MacOS/ChatGPT --user-data-dir={data} codex://threads/new",
            f"{self.root}/apps/Codex work.app/Contents/MacOS/ChatGPT --user-data-dir={data}",
        ):
            process_file.write_text(right + "\n")
            self.run_shell(script)

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

    def test_remove_refuses_a_running_profile(self):
        self.create()
        result = self.run_shell("profile_running() { return 0; }; cmd_remove work",
                                input="work\n", success=False)
        self.assertIn("is running", result.stderr)
        self.assertTrue((self.root / "profiles/work").exists())

    def test_remove_stops_only_the_sync_agents_using_that_profile(self):
        self.create()
        self.env["HOME"] = str(self.root)
        agents = self.root / "Library/LaunchAgents"
        agents.mkdir(parents=True)
        home = self.root / "profiles/work"
        for label, peer in (("mine", home), ("other", self.root / "profiles/personal")):
            with (agents / f"local.multicodex.sessions.{label}.plist").open("wb") as f:
                plistlib.dump({"ProgramArguments": [str(peer)]}, f)
        self.run_shell('launchctl() { printf "%s\\n" "$2" >> "$TEST_DIR/bootouts"; }; cmd_remove work',
                       input="work\n")
        self.assertIn("local.multicodex.sessions.mine", (self.root / "bootouts").read_text())
        self.assertNotIn("other", (self.root / "bootouts").read_text())
        self.assertFalse((agents / "local.multicodex.sessions.mine.plist").exists())
        self.assertTrue((agents / "local.multicodex.sessions.other.plist").exists())

    def test_doctor_reports_a_failing_session_sync(self):
        self.env["HOME"] = str(self.root)
        folder = self.root / ".multicodex/session-sync/pair"
        folder.mkdir(parents=True)
        (folder / "error.json").write_text('{"error": "Different threads schemas", "time": "now"}')
        result = self.run_shell("cmd_doctor")
        self.assertIn("session sync failing: Different threads schemas", result.stderr)

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


class AssetLookup(unittest.TestCase):
    def test_assets_resolve_through_an_installed_symlink(self):
        # The documented install links the script into ~/.local/bin. BASH_SOURCE
        # reports the link, not its target, so the icons live one resolution away.
        with tempfile.TemporaryDirectory(prefix="multicodex-link-") as temp:
            link = Path(temp) / "multicodex"
            link.symlink_to(CLI)
            result = subprocess.run(
                ["/bin/bash", "-c", f'source "{link}"\nprintf "%s\\n" "$SELF" "$ICON_DIR"'],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self_dir, icon_dir = result.stdout.split()
            self.assertEqual(Path(self_dir), REPO)
            self.assertTrue(Path(icon_dir).is_dir(), icon_dir)


if __name__ == "__main__":
    unittest.main()
