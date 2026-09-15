#!/usr/bin/env python3
"""Opt-in, local two-way conversation sync. Never copy account/config databases."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import sqlite3
import subprocess
import sys


# Explicit allowlists: enrollment, credentials, queues, migrations and settings
# remain private to each app. Reject schema drift rather than guessing a repair.
STATE_TABLES = (
    "projects", "thread_sections", "project_roots", "threads",
    "thread_dynamic_tools", "thread_spawn_edges", "thread_artifacts",
)
HISTORY_TABLES = (
    "thread_turns", "thread_items", "thread_realtime_items",
    "thread_history_projection_state",
)


def write_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, sort_keys=True))
    temp.chmod(0o600)
    temp.replace(path)


def digest(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()


def database(home, prefix):
    candidates = list(home.glob(f"{prefix}_[0-9]*.sqlite"))
    if not candidates:
        raise ValueError(f"No {prefix} database in {home}; open this profile in Codex first")
    return max(candidates, key=lambda p: int(p.stem.rsplit("_", 1)[1]))


@contextmanager
def connected(left, right):
    db = sqlite3.connect(left.as_uri() + "?mode=rw", uri=True, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        db.execute("ATTACH DATABASE ? AS peer", (right.as_uri() + "?mode=rw",))
        db.execute("PRAGMA foreign_keys = ON")
        yield db
    finally:
        db.close()


def schema(db, tables):
    result = {}
    for table in tables:
        left = [tuple(r) for r in db.execute(f'PRAGMA main.table_info("{table}")')]
        right = [tuple(r) for r in db.execute(f'PRAGMA peer.table_info("{table}")')]
        if not left and not right:
            continue
        if left != right:
            raise ValueError(f"Different {table} schemas; update both Codex apps before syncing")
        columns = [r[1] for r in left]
        keys = [r[1] for r in sorted(left, key=lambda r: r[5]) if r[5]]
        if not keys:
            raise ValueError(f"Unsupported {table} schema: no primary key")
        result[table] = (columns, keys)
    if tables[0] not in result or (tables == STATE_TABLES and "threads" not in result):
        raise ValueError("Unsupported Codex schema")
    return result


def upsert_sql(side, table, columns, keys, select=None):
    names = ",".join(f'"{c}"' for c in columns)
    conflict = ",".join(f'"{c}"' for c in keys)
    updates = ",".join(f'"{c}"=excluded."{c}"' for c in columns if c not in keys)
    values = select or "VALUES (" + ",".join("?" for _ in columns) + ")"
    action = "DO UPDATE SET " + updates if updates else "DO NOTHING"
    return f'INSERT INTO {side}."{table}" ({names}) {values} ON CONFLICT ({conflict}) {action}'


def timestamp(row):
    return max(row.get("updated_at_ms") or 0, (row.get("updated_at") or 0) * 1000)


def merge_state(left, right, baseline):
    changes = conflicts = 0
    next_baseline = {}
    with connected(left, right) as db:
        tables = schema(db, STATE_TABLES)
        db.execute("BEGIN IMMEDIATE")
        try:
            for table, (columns, keys) in tables.items():
                sides = []
                for side in ("main", "peer"):
                    rows = {}
                    for raw in db.execute(f'SELECT * FROM {side}."{table}"'):
                        row = dict(raw)
                        key = json.dumps([row[c] for c in keys])
                        rows[key] = row
                    sides.append(rows)
                for key in sorted(sides[0].keys() | sides[1].keys()):
                    a, b = sides[0].get(key), sides[1].get(key)
                    state_key = table + ":" + key
                    old = baseline.get(state_key)
                    if a == b:
                        winner = a
                    elif a is None:
                        winner = b
                    elif b is None:
                        winner = a
                    elif old == digest(a):
                        winner = b
                    elif old == digest(b):
                        winner = a
                    else:
                        # On the first merge, or simultaneous edits, prefer the
                        # most recently updated record; left wins timestamp ties.
                        winner = b if timestamp(b) > timestamp(a) else a
                        conflicts += 1
                    if table == "threads":
                        path = Path(winner["rollout_path"])
                        if not path.is_file():
                            # Do not import broken paths or replace a valid peer
                            # with an archive move that has not finished yet.
                            continue
                        winner = dict(winner, rollout_path=str(path.resolve()))
                    for side, existing in zip(("main", "peer"), (a, b)):
                        if existing != winner:
                            db.execute(upsert_sql(side, table, columns, keys),
                                       [winner[c] for c in columns])
                            changes += 1
                    next_baseline[state_key] = digest(winner)
            db.commit()
        except Exception:
            db.rollback()
            raise
    return next_baseline, changes, conflicts


def merge_history(left, right):
    changed = 0
    with connected(left, right) as db:
        tables = schema(db, HISTORY_TABLES)
        if "thread_history_projection_state" not in tables:
            raise ValueError("Unsupported Codex history projection schema")
        ids = [r[0] for r in db.execute(
            "SELECT thread_id FROM main.thread_history_projection_state UNION "
            "SELECT thread_id FROM peer.thread_history_projection_state")]
        for thread_id in ids:
            # Bound writer locks to one thread. Re-read progress under the lock
            # so a live app cannot advance the destination between read/write.
            db.execute("BEGIN IMMEDIATE")
            try:
                progress = []
                for side in ("main", "peer"):
                    row = db.execute(f"SELECT next_rollout_ordinal, next_rollout_byte_offset "
                                     f"FROM {side}.thread_history_projection_state WHERE thread_id=?",
                                     (thread_id,)).fetchone()
                    progress.append(tuple(row) if row else (-1, -1))
                if progress[0] != progress[1]:
                    source, target = ("main", "peer") if progress[0] > progress[1] else ("peer", "main")
                    for table, (columns, keys) in tables.items():
                        names = ",".join(f'"{c}"' for c in columns)
                        select = f'SELECT {names} FROM {source}."{table}" WHERE thread_id=?'
                        db.execute(upsert_sql(target, table, columns, keys, select), (thread_id,))
                    changed += 1
                db.commit()
            except Exception:
                db.rollback()
                raise
    return changed


def backup_databases(paths, folder):
    complete = folder / "complete.json"
    if complete.exists():
        return
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    for index, path in enumerate(paths):
        target = folder / f"{index}-{path.name}"
        print(f"Backing up {path.name} ({index + 1}/{len(paths)})", flush=True)
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(target) as destination:
                source.backup(destination, pages=4096)
        target.chmod(0o600)
    write_json(complete, {"sources": [str(p) for p in paths]})


def sync_once(left_home, right_home, folder):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (folder / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        left, right = database(left_home, "state"), database(right_home, "state")
        lh, rh = database(left_home, "thread_history"), database(right_home, "thread_history")
        # Validate all schemas before touching either database or making backups.
        with connected(left, right) as db:
            schema(db, STATE_TABLES)
        with connected(lh, rh) as db:
            schema(db, HISTORY_TABLES)
        backup_databases([left, right, lh, rh], folder / "backup")
        baseline_path = folder / "baseline.json"
        baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else {}
        # History first: new sidebar entries are published only after messages.
        history = merge_history(lh, rh)
        baseline, changes, conflicts = merge_state(left, right, baseline)
        write_json(baseline_path, baseline)
        result = {"last_success": datetime.now(timezone.utc).isoformat(),
                  "metadata_writes": changes, "history_threads": history,
                  "conflicts_resolved": conflicts, "left": str(left_home), "right": str(right_home)}
        write_json(folder / "status.json", result)
        print(json.dumps(result), flush=True)
        return result


def agent_plist(label, helper, left, right, folder):
    return {
        "Label": label,
        "ProgramArguments": [sys.executable, str(helper), "sync", "--left", str(left),
                             "--right", str(right), "--storage", str(folder.parent)],
        "StartInterval": 15,
        "RunAtLoad": True,
        "ProcessType": "Background",
        "StandardOutPath": str(folder / "agent.log"),
        "StandardErrorPath": str(folder / "agent-error.log"),
        "Umask": 0o077,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("sync", "enable", "disable", "status"))
    parser.add_argument("--left", required=True, type=Path)
    parser.add_argument("--right", required=True, type=Path)
    parser.add_argument("--storage", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    left, right = sorted((args.left.resolve(), args.right.resolve()))
    if left == right:
        raise ValueError("Choose two different profile homes")
    pair = hashlib.sha256((str(left) + "\0" + str(right)).encode()).hexdigest()[:16]
    folder = args.storage.resolve() / pair
    label = "local.multicodex.sessions." + pair
    plist = Path.home() / "Library/LaunchAgents" / (label + ".plist")
    domain = f"gui/{os.getuid()}"
    if args.action in ("sync", "enable"):
        try:
            sync_once(left, right, folder)
        except (ValueError, OSError, sqlite3.Error) as error:
            if folder.is_dir():
                write_json(folder / "error.json", {
                    "time": datetime.now(timezone.utc).isoformat(), "error": str(error)})
            raise
        (folder / "error.json").unlink(missing_ok=True)
    if args.action == "enable":
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_bytes(plistlib.dumps(agent_plist(label, Path(__file__).resolve(), left, right, folder)))
        subprocess.run(["launchctl", "bootout", domain + "/" + label], capture_output=True)
        subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
        print("Two-way session sync enabled every 15 seconds and at login.")
    elif args.action == "disable":
        result = subprocess.run(["launchctl", "bootout", domain + "/" + label], capture_output=True)
        if result.returncode and subprocess.run(["launchctl", "print", domain + "/" + label],
                                               capture_output=True).returncode == 0:
            raise ValueError("Could not stop the session sync agent")
        plist.unlink(missing_ok=True)
        print("Session sync disabled. Conversation data and backups are retained.")
    elif args.action == "status":
        loaded = subprocess.run(["launchctl", "print", domain + "/" + label], capture_output=True).returncode == 0
        print("Automatic sync: " + ("enabled" if loaded else "disabled"))
        path = folder / "status.json"
        print(path.read_text() if path.exists() else "No successful sync recorded.")
        error = folder / "error.json"
        if error.exists():
            print("Latest attempt failed: " + error.read_text())
        print(f"Backups and logs: {folder}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, sqlite3.Error, subprocess.CalledProcessError) as error:
        print(f"session sync: {error}", file=sys.stderr)
        sys.exit(1)
