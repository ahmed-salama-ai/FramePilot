import json
import os
import re
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent                     # the project folder (works from any folder)
DATA = Path(os.environ.get("FRAMEPILOT_DATA") or ROOT / "data")    # the tests point this at a temp folder
DB_PATH = DATA / "app.db"
SESSIONS_DIR = DATA / "sessions"
TRASH_DIR = DATA / "trash"                                          # deleted projects are MOVED here, not erased
MOCK_SRC = ROOT / "samples" / "mock_s00"
SID = re.compile(r"s\d{2,4}")

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    language TEXT DEFAULT 'ar',
    wide_cam INTEGER DEFAULT 1,
    num_cameras INTEGER DEFAULT 3,
    consent_at TEXT,
    source TEXT DEFAULT 'upload',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    status TEXT DEFAULT 'queued',
    stage TEXT DEFAULT 'Waiting',
    progress INTEGER DEFAULT 0,
    report TEXT,
    error TEXT,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    steps_json TEXT,
    clips_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""
STAGES = {"pipeline": ["Ingest + Sync", "Audio + Captions", "Perception", "AI Brain", "Switching", "Render",
                       "Highlights", "Evaluation"],
          "finish": ["Captions, name cards and brand", "Highlight clips, trailer and thumbnails"],
          "publish": ["Publish kit", "Article"],
          "language": ["Captions in one language"],
          "thumbnails": ["Thumbnails"],
          "trailer": ["Trailer"]}


@contextmanager
def conn():
    """One database connection: saved (commit) and closed at the end of the with block."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def add_column(c, table, column, decl):
    """Older app.db files: add a column that was added later."""
    if column not in [r["name"] for r in c.execute(f"PRAGMA table_info({table})")]:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init():
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        c.executescript(SCHEMA)
        add_column(c, "projects", "source", "TEXT DEFAULT 'upload'")
        add_column(c, "projects", "duration", "REAL")
        add_column(c, "messages", "clips_json", "TEXT")
        add_column(c, "jobs", "kind", "TEXT DEFAULT 'pipeline'")
        add_column(c, "jobs", "args", "TEXT")
        add_column(c, "jobs", "stage_started_at", "TEXT")
    seed_mock_if_needed()
    import_sessions()


def seed_mock_if_needed():
    """Ensure mock session s00 is available in database and data/sessions."""
    s00_dir = SESSIONS_DIR / "s00"
    if MOCK_SRC.exists() and not s00_dir.exists():
        shutil.copytree(MOCK_SRC, s00_dir)
    if not s00_dir.exists():
        return

    with conn() as c:
        row = c.execute("SELECT id FROM projects WHERE session_id = 's00'").fetchone()
        if row:
            c.execute("UPDATE projects SET source = 'mock' WHERE session_id = 's00'")
            return
        now_iso = datetime.now().isoformat()
        c.execute(
            """INSERT INTO projects (session_id, name, language, wide_cam, num_cameras, consent_at, source)
               VALUES ('s00', 'FramePilot Demo: Tech Podcast Episode', 'ar', 1, 3, ?, 'mock')""",
            (now_iso,)
        )
        report_mock = json.dumps([
            ["Ingest + Sync", "done", 4.2],
            ["Audio + Captions", "done", 8.5],
            ["Perception", "done", 12.1],
            ["AI Brain", "done", 9.4],
            ["Switching", "done", 3.2],
            ["Render", "done", 15.0],
            ["Highlights", "done", 7.8],
            ["Evaluation", "done", 2.1]
        ])
        c.execute(
            """INSERT INTO jobs (session_id, status, stage, progress, report, finished_at)
               VALUES ('s00', 'done', 'Done', 100, ?, ?)""",
            (report_mock, now_iso)
        )


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def import_sessions():
    """Session folders made outside the web app (e.g. s01-s03 run with ai_director.pipeline) appear on the
    projects page as 'imported': they can be opened, but the app never deletes them."""
    with conn() as c:
        known = {r["session_id"] for r in c.execute("SELECT session_id FROM projects")}
        for folder in sorted(SESSIONS_DIR.iterdir()):
            if not folder.is_dir() or not SID.fullmatch(folder.name) or folder.name in known:
                continue
            upload = read_json(folder / "upload.json")
            if not isinstance(upload, dict):
                continue
            cams = len(list((folder / "raw").glob("cam*.mp4"))) or 3
            meta = read_json(folder / "session.json", {}) or {}
            c.execute(
                """INSERT INTO projects (session_id, name, language, wide_cam, num_cameras, consent_at, source, duration)
                   VALUES (?, ?, ?, ?, ?, NULL, 'imported', ?)""",
                (folder.name, upload.get("name") or f"Session {folder.name}", upload.get("language", "ar"),
                 upload.get("wide_cam", 1), cams, meta.get("duration"))
            )
            if (folder / "program.mp4").exists():
                times = read_json(folder / "logs" / "times.json", {}) or {}
                report = [[stage, "done", secs] for stage, secs in times.items()]
                c.execute(
                    """INSERT INTO jobs (session_id, status, stage, progress, report, finished_at)
                       VALUES (?, 'done', 'Done', 100, ?, ?)""",
                    (folder.name, json.dumps(report, ensure_ascii=False), datetime.now().isoformat())
                )


def new_session_id():
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        rows = c.execute("SELECT session_id FROM projects").fetchall()
    existing_nums = []
    for r in rows:
        m = re.fullmatch(r"s(\d+)", r["session_id"] or "")
        if m:
            existing_nums.append(int(m.group(1)))
    for p in SESSIONS_DIR.iterdir():
        m = re.fullmatch(r"\.?s(\d+)(\.uploading)?", p.name)        # also uploads still being written
        if m:
            existing_nums.append(int(m.group(1)))
    next_num = max(existing_nums, default=0) + 1
    return f"s{next_num:02d}"


def create_project(sid, name, language="ar", wide_cam=1, num_cameras=3, consent_at=None, duration=None):
    if not consent_at:
        consent_at = datetime.now().isoformat()
    with conn() as c:
        c.execute(
            """INSERT INTO projects (session_id, name, language, wide_cam, num_cameras, consent_at, source, duration)
               VALUES (?, ?, ?, ?, ?, ?, 'upload', ?)""",
            (sid, name, language, wide_cam, num_cameras, consent_at, duration)
        )


def list_projects():
    with conn() as c:
        query = """
            SELECT p.*,
                   j.id as job_id,
                   j.status as job_status,
                   j.stage as job_stage,
                   j.progress as job_progress,
                   j.error as job_error
            FROM projects p
            LEFT JOIN jobs j ON j.id = (
                SELECT id FROM jobs WHERE session_id = p.session_id ORDER BY id DESC LIMIT 1
            )
            ORDER BY p.id DESC
        """
        rows = c.execute(query).fetchall()
        return [dict(r) for r in rows]


def get_project(sid):
    with conn() as c:
        row = c.execute("SELECT * FROM projects WHERE session_id = ?", (sid,)).fetchone()
        return dict(row) if row else None


def forget_project(sid):
    """Remove the project's rows from the database (the folder is not touched)."""
    with conn() as c:
        c.execute("DELETE FROM projects WHERE session_id = ?", (sid,))
        c.execute("DELETE FROM jobs WHERE session_id = ?", (sid,))
        c.execute("DELETE FROM messages WHERE session_id = ?", (sid,))


def delete_project(sid):
    """Delete a project: its folder is MOVED to data/trash/sNN_<date>_<time> (empty that folder by hand to free
    the space), then its rows are removed. Raises OSError if the folder can't be moved (a file is in use)."""
    session_dir = SESSIONS_DIR / sid
    if session_dir.exists():
        TRASH_DIR.mkdir(parents=True, exist_ok=True)
        session_dir.rename(TRASH_DIR / f"{sid}_{datetime.now():%Y%m%d_%H%M%S}")
    forget_project(sid)
    return True


def create_job(sid, kind="pipeline", args=None):
    with conn() as c:
        cur = c.execute("INSERT INTO jobs(session_id, status, stage, progress, kind, args) "
                        "VALUES (?, 'queued', 'Waiting', 0, ?, ?)",
                        (sid, kind, json.dumps(args or {}, ensure_ascii=False)))
        return cur.lastrowid


def active_job(sid):
    """The session's queued or running job (one at a time per session), else None."""
    with conn() as c:
        row = c.execute("SELECT id FROM jobs WHERE session_id = ? AND status IN ('queued', 'running') "
                        "ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
        return row["id"] if row else None


def parse_job(row):
    res = dict(row)
    for key in ("report", "args"):
        if res.get(key):
            try:
                res[key] = json.loads(res[key])
            except Exception:
                pass
    res["kind"] = res.get("kind") or "pipeline"
    res["args"] = res.get("args") if isinstance(res.get("args"), dict) else {}
    res["stages"] = STAGES.get(res["kind"], [])
    return res


def get_job(job_id):
    with conn() as c:
        row = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        res = parse_job(row)

        # Calculate queue position if waiting
        if res["status"] == "queued":
            ahead = c.execute(
                "SELECT COUNT(*) as c FROM jobs WHERE status IN ('queued', 'running') AND id < ?",
                (job_id,)
            ).fetchone()["c"]
            res["queue_position"] = ahead
        else:
            res["queue_position"] = 0

        return res


def get_latest_job(sid):
    with conn() as c:
        row = c.execute("SELECT * FROM jobs WHERE session_id = ? ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
        return parse_job(row) if row else None


def next_job():
    with conn() as c:
        row = c.execute("SELECT * FROM jobs WHERE status = 'queued' ORDER BY id ASC LIMIT 1").fetchone()
        if row:
            now_iso = datetime.now().isoformat()
            c.execute("UPDATE jobs SET status = 'running', stage = 'Starting', started_at = ?, stage_started_at = ? "
                      "WHERE id = ?", (now_iso, now_iso, row["id"]))
            return parse_job(row)
        return None


def update_job(job_id, **kw):
    with conn() as c:
        fields = []
        vals = []
        for k, v in kw.items():
            fields.append(f"{k} = ?")
            if k in ("report", "args") and isinstance(v, (list, dict)):
                vals.append(json.dumps(v, ensure_ascii=False))
            else:
                vals.append(v)
        vals.append(job_id)
        c.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", vals)


def retry_job(job_id):
    with conn() as c:
        cur = c.execute(
            """UPDATE jobs
               SET status = 'queued', stage = 'Waiting', progress = 0, report = NULL,
                   error = NULL, started_at = NULL, finished_at = NULL
               WHERE id = ? AND status = 'error'""",
            (job_id,)
        )
        return cur.rowcount == 1


def reset_running_jobs():
    """Called when the worker starts: a job still 'running' was cut off (worker closed, PC turned off).
    Mark it failed, so it can be retried and the Editor Agent is not blocked by 'GPU busy' forever."""
    with conn() as c:
        return c.execute(
            "UPDATE jobs SET status = 'error', error = ?, finished_at = ? WHERE status = 'running'",
            ("The worker stopped during this run. Press Try again.", datetime.now().isoformat())
        ).rowcount


def gpu_busy():
    with conn() as c:
        row = c.execute("SELECT 1 FROM jobs WHERE status = 'running' LIMIT 1").fetchone()
        return row is not None


def add_message(sid, role, content, steps=None, clips=None):
    dump = lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (list, dict)) else x
    with conn() as c:
        c.execute(
            "INSERT INTO messages (session_id, role, content, steps_json, clips_json) VALUES (?, ?, ?, ?, ?)",
            (sid, role, content, dump(steps), dump(clips))
        )


def get_messages(sid):
    """[{role, content, steps, clips, created_at}] oldest first (the clips are shown again after a reload)."""
    with conn() as c:
        rows = c.execute(
            "SELECT role, content, steps_json, clips_json, created_at FROM messages WHERE session_id = ? ORDER BY id ASC",
            (sid,)
        ).fetchall()
    msgs = []
    for r in rows:
        item = {"role": r["role"], "content": r["content"], "created_at": r["created_at"]}
        for key in ("steps", "clips"):
            try:
                item[key] = json.loads(r[f"{key}_json"]) if r[f"{key}_json"] else []
            except ValueError:
                item[key] = []
        msgs.append(item)
    return msgs
