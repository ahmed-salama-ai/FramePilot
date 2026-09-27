import sqlite3
import os

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY, session_id TEXT UNIQUE, name TEXT,
    language TEXT, wide_cam INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, session_id TEXT, status TEXT DEFAULT 'queued',
    stage TEXT DEFAULT 'Waiting', progress INTEGER DEFAULT 0, error TEXT, created_at TEXT DEFAULT 
    CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,
    steps_json TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);"""

def conn():
    c = sqlite3.connect("data/app.db", timeout=10)
    c.row_factory = sqlite3.Row
    return c

def init():
    os.makedirs("data", exist_ok=True)
    with conn() as c: 
        c.executescript(SCHEMA)

def create_job(sid):
    with conn() as c: 
        return c.execute("INSERT INTO jobs(session_id) VALUES (?)", (sid,)).lastrowid

def get_job(job_id):
    with conn() as c: 
        return dict(c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

def next_job():
    with conn() as c:
        row = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if row: 
            c.execute("UPDATE jobs SET status='running' WHERE id=?", (row["id"],))
        return dict(row) if row else None

def update_job(job_id, **kw):
    with conn() as c: 
        c.execute(f"UPDATE jobs SET {', '.join(k + '=?' for k in kw)} WHERE id=?", 
                  (*kw.values(), job_id))

def gpu_busy():
    with conn() as c: 
        return c.execute("SELECT 1 FROM jobs WHERE status='running'").fetchone() is not None

def new_session_id():
    with conn() as c:
        row = c.execute("SELECT count(*) as c FROM projects").fetchone()
        return f"s{(row['c'] or 0) + 1:02d}"

def create_project(sid, name, language, wide_cam):
    with conn() as c:
        c.execute("INSERT INTO projects (session_id, name, language, wide_cam) VALUES (?, ?, ?, ?)", 
                  (sid, name, language, wide_cam))

def list_projects():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()]

def add_message(sid, role, content, steps_json="[]"):
    with conn() as c:
        c.execute("INSERT INTO messages (session_id, role, content, steps_json) VALUES (?, ?, ?, ?)",
                  (sid, role, content, steps_json))

def get_messages(sid):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM messages WHERE session_id=? ORDER BY id", (sid,)).fetchall()]
