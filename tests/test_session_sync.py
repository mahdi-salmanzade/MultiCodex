"""Exercise real SQLite merges in disposable homes, without launching agents."""

import importlib.util
import contextlib
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "session_sync", Path(__file__).resolve().parents[1] / "tools/session_sync.py")
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


class SessionSync(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.homes = [self.root / "default", self.root / "work"]
        self.folder = self.root / "sync"
        for home in self.homes:
            home.mkdir()
            (home / "sessions").mkdir()
            (home / "auth.json").write_text(home.name + " credentials")
            with sqlite3.connect(home / "state_5.sqlite") as db:
                db.executescript('''
                    CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT, updated_at_ms INTEGER);
                    CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, title TEXT,
                        updated_at_ms INTEGER, archived INTEGER DEFAULT 0,
                        project_id TEXT REFERENCES projects(id));
                    CREATE TABLE remote_control_enrollments (account_id TEXT);
                ''')
                db.execute("INSERT INTO remote_control_enrollments VALUES (?)", (home.name,))
            with sqlite3.connect(home / "thread_history_1.sqlite") as db:
                db.executescript('''
                    CREATE TABLE thread_turns (thread_id TEXT, turn_id TEXT, status TEXT,
                        PRIMARY KEY(thread_id,turn_id));
                    CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, item_id TEXT,
                        item_json TEXT, updated_at_ordinal INTEGER,
                        PRIMARY KEY(thread_id,turn_id,item_id));
                    CREATE TABLE thread_history_projection_state (thread_id TEXT PRIMARY KEY,
                        next_rollout_ordinal INTEGER, next_rollout_byte_offset INTEGER);
                ''')

    def seed(self, home, thread_id):
        path = home / "sessions" / (thread_id + ".jsonl")
        path.write_text('{"type":"session_meta"}\n')
        with sqlite3.connect(home / "state_5.sqlite") as db:
            db.execute("INSERT INTO projects VALUES (?,?,?)", (thread_id, "project", 1))
            db.execute("INSERT INTO threads VALUES (?,?,?,?,?,?)",
                       (thread_id, str(path), "chat " + thread_id, 1, 0, thread_id))
        with sqlite3.connect(home / "thread_history_1.sqlite") as db:
            db.execute("INSERT INTO thread_turns VALUES (?,?,?)", (thread_id, "turn", "completed"))
            db.execute("INSERT INTO thread_items VALUES (?,?,?,?,?)",
                       (thread_id, "turn", "item", '{"text":"hello"}', 1))
            db.execute("INSERT INTO thread_history_projection_state VALUES (?,?,?)", (thread_id, 2, 42))
        return path

    def rows(self, home, table, *, history=False):
        path = home / ("thread_history_1.sqlite" if history else "state_5.sqlite")
        with sqlite3.connect(path) as db:
            return db.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()

    def run_sync(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return sync.sync_once(*self.homes, self.folder)

    def test_two_way_import_includes_history_projects_and_preserves_accounts(self):
        paths = [self.seed(home, home.name) for home in self.homes]
        contents = [p.read_bytes() for p in paths]
        result = self.run_sync()
        self.assertEqual(result["history_threads"], 2)
        for table in ("threads", "projects"):
            self.assertEqual(self.rows(self.homes[0], table), self.rows(self.homes[1], table))
            self.assertEqual(len(self.rows(self.homes[0], table)), 2)
        for table in ("thread_turns", "thread_items", "thread_history_projection_state"):
            self.assertEqual(self.rows(self.homes[0], table, history=True),
                             self.rows(self.homes[1], table, history=True))
        for home in self.homes:
            self.assertEqual((home / "auth.json").read_text(), home.name + " credentials")
            self.assertEqual(self.rows(home, "remote_control_enrollments"), [(home.name,)])
            with sqlite3.connect(home / "state_5.sqlite") as db:
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual([p.read_bytes() for p in paths], contents)
        self.assertTrue((self.folder / "backup/complete.json").is_file())
        with sqlite3.connect(self.folder / "backup/0-state_5.sqlite") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM threads").fetchone()[0], 1)
        result = self.run_sync()
        self.assertEqual(result["metadata_writes"], 0)
        self.assertEqual(result["history_threads"], 0)

    def test_updates_in_either_app_without_timestamp_change(self):
        self.seed(self.homes[0], "chat")
        self.run_sync()
        for home in reversed(self.homes):
            with sqlite3.connect(home / "state_5.sqlite") as db:
                db.execute("UPDATE threads SET title=?", (home.name,))
            self.run_sync()
            for peer in self.homes:
                self.assertEqual(self.rows(peer, "threads")[0][2], home.name)

    def test_history_progress_copies_new_and_updated_messages_both_ways(self):
        self.seed(self.homes[0], "chat")
        self.run_sync()
        for index, home in enumerate(reversed(self.homes), 3):
            with sqlite3.connect(home / "thread_history_1.sqlite") as db:
                db.execute("UPDATE thread_items SET item_json=?,updated_at_ordinal=?", (home.name, index))
                db.execute("UPDATE thread_turns SET status=?", (home.name,))
                db.execute("UPDATE thread_history_projection_state SET next_rollout_ordinal=?", (index,))
            self.run_sync()
            self.assertEqual(self.rows(self.homes[0], "thread_items", history=True),
                             self.rows(self.homes[1], "thread_items", history=True))
            self.assertEqual(self.rows(self.homes[0], "thread_turns", history=True),
                             self.rows(self.homes[1], "thread_turns", history=True))

    def test_archive_uses_existing_rollout_at_new_location(self):
        path = self.seed(self.homes[0], "chat")
        self.run_sync()
        archived = self.homes[0] / "archived_sessions"
        archived.mkdir()
        path.rename(archived / path.name)
        with sqlite3.connect(self.homes[0] / "state_5.sqlite") as db:
            db.execute("UPDATE threads SET rollout_path=?,archived=1", (str(archived / path.name),))
        self.run_sync()
        self.assertEqual(self.rows(self.homes[1], "threads")[0][4], 1)
        self.assertTrue(Path(self.rows(self.homes[1], "threads")[0][1]).is_file())

    def test_schema_mismatch_stops_before_any_import(self):
        self.seed(self.homes[0], "chat")
        with sqlite3.connect(self.homes[1] / "thread_history_1.sqlite") as db:
            db.execute("ALTER TABLE thread_items ADD COLUMN new_field TEXT")
        with self.assertRaisesRegex(ValueError, "Different thread_items schemas"):
            self.run_sync()
        self.assertEqual(self.rows(self.homes[1], "threads"), [])
        self.assertFalse((self.folder / "backup").exists())

    def test_missing_rollout_is_not_imported(self):
        path = self.seed(self.homes[0], "chat")
        path.unlink()
        self.run_sync()
        self.assertEqual(self.rows(self.homes[1], "threads"), [])

    def test_simultaneous_metadata_changes_choose_latest(self):
        self.seed(self.homes[0], "chat")
        self.run_sync()
        for index, home in enumerate(self.homes, 2):
            with sqlite3.connect(home / "state_5.sqlite") as db:
                db.execute("UPDATE threads SET title=?,updated_at_ms=?", (home.name, index))
        result = self.run_sync()
        self.assertEqual(result["conflicts_resolved"], 1)
        self.assertEqual(self.rows(self.homes[0], "threads")[0][2], "work")

    def test_launch_agent_runs_same_pair_every_15_seconds(self):
        plist = sync.agent_plist("test", Path("/repo/tools/session_sync.py"), *self.homes, self.folder)
        self.assertEqual(plist["StartInterval"], 15)
        self.assertTrue(plist["RunAtLoad"])
        self.assertIn("sync", plist["ProgramArguments"])
        self.assertEqual(plist["Umask"], 0o077)


if __name__ == "__main__":
    unittest.main()
