import json
import os
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

SESSIONS_DIR = Path(os.environ.get("PHONE_CONTROLLER_DATA", "data")) / "sessions"
RETENTION_DAYS = int(os.environ.get("PHONE_CONTROLLER_RETENTION_DAYS", "14"))
SAFE_NAME = re.compile(r"^[\w.-]+$")


def now():
    return datetime.now(UTC).isoformat()


class SessionRecord:
    def __init__(self, session_id, holder, waited):
        self.dir = SESSIONS_DIR / session_id
        self.dir.mkdir(parents=True)
        self.meta = {
            "id": session_id,
            "holder": holder,
            "granted_at": now(),
            "waited": waited,
            "actions": 0,
            "errors": 0,
            "status": "running",
        }
        self.save()

    def save(self):
        (self.dir / "session.json").write_text(json.dumps(self.meta))

    def next_step(self):
        self.meta["actions"] += 1
        return self.meta["actions"]

    def save_image(self, n, name, image):
        filename = f"{n:02d}_{name}.png"
        image.save(self.dir / filename)
        return filename

    def save_text(self, n, name, text, extension):
        filename = f"{n:02d}_{name}.{extension}"
        (self.dir / filename).write_text(text)
        return filename

    def add_step(self, step):
        if not step["ok"]:
            self.meta["errors"] += 1
        with open(self.dir / "steps.jsonl", "a") as f:
            f.write(json.dumps(step) + "\n")
        self.save()

    def close(self, duration):
        self.meta.update(closed_at=now(), duration=duration, status="closed")
        self.save()


def prune_sessions(days=RETENTION_DAYS):
    if days <= 0 or not SESSIONS_DIR.exists():
        return []
    cutoff = datetime.now(UTC) - timedelta(days=days)
    removed = []
    for session_dir in SESSIONS_DIR.iterdir():
        meta_file = session_dir / "session.json"
        if meta_file.exists():
            meta = json.loads(meta_file.read_text())
            if meta["status"] == "running":
                continue
            started = datetime.fromisoformat(meta["granted_at"])
        else:
            started = datetime.fromtimestamp(session_dir.stat().st_mtime, UTC)
        if started < cutoff:
            shutil.rmtree(session_dir)
            removed.append(session_dir.name)
    return removed


def list_sessions():
    sessions = []
    for meta_file in SESSIONS_DIR.glob("*/session.json"):
        sessions.append(json.loads(meta_file.read_text()))
    return sorted(sessions, key=lambda s: s["granted_at"], reverse=True)


def load_session(session_id):
    if not SAFE_NAME.match(session_id):
        return None, []
    session_dir = SESSIONS_DIR / session_id
    if not (session_dir / "session.json").exists():
        return None, []
    meta = json.loads((session_dir / "session.json").read_text())
    steps_file = session_dir / "steps.jsonl"
    steps = []
    if steps_file.exists():
        steps = [json.loads(line) for line in steps_file.read_text().splitlines()]
    return meta, steps


def session_file(session_id, name):
    if not (SAFE_NAME.match(session_id) and SAFE_NAME.match(name)):
        return None
    path = SESSIONS_DIR / session_id / name
    return path if path.is_file() else None
