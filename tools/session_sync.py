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


# The sidebar's projects and thread-to-project assignments live in the desktop
# app's own state file, not the SQLite databases: each app lists only the
# projects in its `local-projects`, under IDs private to that app. The app reads
# the file once at launch and rewrites it whole on every change, so a copy is
# written only while that app is closed and takes effect when it next opens.
GLOBAL_STATE = ".codex-global-state.json"
PROJECTS, ORDER = "local-projects", "project-order"
ASSIGNMENTS, PROJECTLESS = "thread-project-assignments", "projectless-thread-ids"
PINNED_PROJECTS = "pinned-project-ids"
DEFAULT_HOME = Path.home() / ".codex"


def app_running(home):
    # macOS hides these processes' environment, so identify each app by its
    # arguments: profiles are launched with their own --user-data-dir, the
    # official app with none.
    result = subprocess.run(["ps", "-axww", "-o", "command="], capture_output=True, text=True)
    if result.returncode:
        return True
    marker = "/Contents/MacOS/ChatGPT"
    default = home.resolve() == DEFAULT_HOME.resolve()
    for command in result.stdout.splitlines():
        if marker not in command:
            continue
        head, _, args = command.partition(marker)
        if args and not args.startswith(" "):
            continue
        data = [a for a in args.split(" --") if a.startswith("user-data-dir=")]
        if default and not data:
            return True
        if not default and any(Path(a.split("=", 1)[1].strip()).name == home.name for a in data):
            return True
    return False


def project_key(project):
    return json.dumps(sorted(os.path.realpath(p) for p in project.get("rootPaths") or []))


def sidebar(state):
    """Reduce an app's state to ID-free items: projects by root folders, and
    each thread's project (by the same key) or "" when explicitly projectless."""
    projects = state.get(PROJECTS) or {}
    keys = {pid: project_key(p) for pid, p in projects.items() if p.get("rootPaths")}
    items = {}
    for pid, key in keys.items():
        items.setdefault("project:" + key, projects[pid].get("name", ""))
    for thread in state.get(PROJECTLESS) or []:
        items["thread:" + thread] = ""
    for thread, target in (state.get(ASSIGNMENTS) or {}).items():
        if target.get("projectKind") == "local" and target.get("projectId") in keys:
            items["thread:" + thread] = keys[target["projectId"]]
    return items


def project_timestamp(state, key):
    return max([p.get("updatedAt") or 0 for p in (state.get(PROJECTS) or {}).values()
                if p.get("rootPaths") and project_key(p) == key] or [0])


def apply_sidebar(state, merged, peer):
    """Rewrite this app's sidebar keys to match the merged items, keeping its
    own project IDs and every key this tool does not manage."""
    projects = dict(state.get(PROJECTS) or {})
    ids = {}
    for pid, project in projects.items():
        if project.get("rootPaths"):
            ids.setdefault(project_key(project), pid)
    peer_projects = {project_key(p): p for p in (peer.get(PROJECTS) or {}).values() if p.get("rootPaths")}
    wanted = {k[8:]: v for k, v in merged.items() if k.startswith("project:")}
    for pid, project in list(projects.items()):
        key = project_key(project) if project.get("rootPaths") else None
        if key is not None and key not in wanted:
            del projects[pid]
        elif key is not None and ids.get(key) == pid and project.get("name") != wanted[key]:
            projects[pid] = dict(project, name=wanted[key])
    ids = {k: v for k, v in ids.items() if k in wanted}
    added = []
    for key in sorted(wanted.keys() - ids.keys()):
        source = peer_projects.get(key) or {"rootPaths": json.loads(key), "createdAt": 0, "updatedAt": 0}
        pid = source.get("id") if source.get("id") and source.get("id") not in projects else None
        pid = pid or "local-" + hashlib.sha256(key.encode()).hexdigest()[:32]
        projects[pid] = dict(source, id=pid, name=wanted[key])
        ids[key] = pid
        added.append(pid)
    order = [p for p in state.get(ORDER) or [] if p in projects]
    peer_order = [project_key((peer.get(PROJECTS) or {}).get(p) or {}) for p in peer.get(ORDER) or []]
    rank = {ids[k]: i for i, k in enumerate(peer_order) if k in ids}
    order += sorted((p for p in added if p not in order), key=lambda p: rank.get(p, len(rank)))
    order += [p for p in projects if p not in order]
    assignments = {t: v for t, v in (state.get(ASSIGNMENTS) or {}).items()
                   if not (v.get("projectKind") == "local" and v.get("projectId") not in projects)}
    projectless = list(state.get(PROJECTLESS) or [])
    for item in sidebar(state).keys() - merged.keys():
        if item.startswith("thread:"):
            assignments.pop(item[7:], None)
            projectless = [t for t in projectless if t != item[7:]]
    for item, value in merged.items():
        if not item.startswith("thread:"):
            continue
        thread = item[7:]
        if value:
            assignments[thread] = {"projectKind": "local", "projectId": ids[value]}
            if thread in projectless:
                projectless.remove(thread)
        else:
            if assignments.get(thread, {}).get("projectKind") == "local":
                del assignments[thread]
            if thread not in projectless:
                projectless.append(thread)
    result = dict(state)
    result[PROJECTS], result[ORDER], result[ASSIGNMENTS] = projects, order, assignments
    result[PROJECTLESS] = projectless
    if PINNED_PROJECTS in result:
        result[PINNED_PROJECTS] = [p for p in result[PINNED_PROJECTS] if p in projects]
    return result


def merge_sidebar(left_home, right_home, folder):
    paths = [home / GLOBAL_STATE for home in (left_home, right_home)]
    if not all(p.is_file() for p in paths):
        return 0, []
    states = [json.loads(p.read_text()) for p in paths]
    views = [sidebar(s) for s in states]
    baseline_path = folder / "sidebar-baseline.json"
    baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else {}
    merged = {}
    for item in sorted(views[0].keys() | views[1].keys()):
        a, b = views[0].get(item), views[1].get(item)
        old = baseline.get(item)
        if a == b:
            winner = a
        elif a is None or b is None:
            present = b if a is None else a
            # Missing where it existed at the last complete merge: removed there.
            winner = None if old is not None and old == present else present
        elif old == a:
            winner = b
        elif old == b:
            winner = a
        elif item.startswith("project:"):
            key = item[8:]
            winner = b if project_timestamp(states[1], key) > project_timestamp(states[0], key) else a
        else:
            winner = a
        if winner is not None:
            merged[item] = winner
    # A thread may only point at a project that survived the merge.
    merged = {k: v for k, v in merged.items()
              if not (k.startswith("thread:") and v and "project:" + v not in merged)}
    writes, pending = 0, []
    for index, (home, path) in enumerate(zip((left_home, right_home), paths)):
        if views[index] == merged:
            continue
        if app_running(home):
            pending.append(str(home))
            continue
        backup = folder / "backup" / f"{index}-{GLOBAL_STATE.lstrip('.')}"
        if not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            backup.write_bytes(path.read_bytes())
            backup.chmod(0o600)
        updated = apply_sidebar(states[index], merged, states[1 - index])
        temp = path.with_name(path.name + ".multicodex-tmp")
        temp.write_text(json.dumps(updated, separators=(",", ":")))
        temp.chmod(path.stat().st_mode & 0o777)
        temp.replace(path)
        writes += 1
    # Advance the baseline only once both apps hold the merged sidebar, so a
    # side that was open keeps receiving what it missed.
    if not pending:
        write_json(baseline_path, merged)
    return writes, pending


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
        sidebar_writes, sidebar_pending = merge_sidebar(left_home, right_home, folder)
        result = {"last_success": datetime.now(timezone.utc).isoformat(),
                  "metadata_writes": changes, "history_threads": history,
                  "conflicts_resolved": conflicts, "sidebar_writes": sidebar_writes,
                  "sidebar_waiting_for_quit": sidebar_pending,
                  "left": str(left_home), "right": str(right_home)}
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
