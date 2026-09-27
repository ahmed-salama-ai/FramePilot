import json, re, shutil
from pathlib import Path
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from app import db

DATA = Path("data/sessions")
DATA.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="FramePilot")

Path("app/static").mkdir(parents=True, exist_ok=True)

app.mount("/files", StaticFiles(directory=DATA), name="files")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
# Day 14 bonus: mount 3D host avatar directory
avatar_dir = Path("avatar/static")
avatar_dir.mkdir(parents=True, exist_ok=True)
app.mount("/avatar", StaticFiles(directory=avatar_dir, html=True), name="avatar")

templates = Jinja2Templates(directory="app/templates")
db.init()

def check_sid(sid):
    if not re.fullmatch(r"s\d{2,4}", sid): raise HTTPException(404)
    return DATA / sid

@app.post("/api/projects/{sid}/delete")
def delete_project(sid: str):
    # D12-13 Polish: delete project button
    d = check_sid(sid)
    with db.conn() as c:
        c.execute("DELETE FROM projects WHERE session_id=?", (sid,))
        c.execute("DELETE FROM jobs WHERE session_id=?", (sid,))
    shutil.rmtree(d, ignore_errors=True)
    return {"status": "deleted"}

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {"projects": db.list_projects()})

@app.post("/api/projects")
def create_project(files: list[UploadFile], name: str = Form(...), language: str = Form("ar"),
                   wide_cam: int = Form(1), num_speakers: int | None = Form(None)):
    if not 2 <= len(files) <= 4: raise HTTPException(400, "Upload 2 to 4 videos")
    sid = db.new_session_id()
    raw = DATA / sid / "raw"
    raw.mkdir(parents=True)
    
    for i, f in enumerate(files, 1):
        with open(raw / f"cam{i}.mp4", "wb") as out:
            shutil.copyfileobj(f.file, out, 1024 * 1024)
    
    (DATA / sid / "upload.json").write_text(json.dumps({
        "name": name, "language": language,
        "wide_cam": wide_cam, "num_speakers": num_speakers
    }))
    
    db.create_project(sid, name, language, wide_cam)
    return {"job_id": db.create_job(sid), "session_id": sid}

@app.get("/api/jobs/{job_id}")
def job_status(job_id: int):
    return db.get_job(job_id)

@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: int):
    return templates.TemplateResponse(request, "job.html", {"job": db.get_job(job_id)})

@app.get("/results/{sid}", response_class=HTMLResponse)
def results_page(request: Request, sid: str):
    projects = db.list_projects()
    project = next((p for p in projects if p["session_id"] == sid), {"name": "Unknown"})
    return templates.TemplateResponse(request, "results.html", {"sid": sid, "project": project})

@app.get("/label/{sid}", response_class=HTMLResponse)
def label_page(request: Request, sid: str):
    projects = db.list_projects()
    project = next((p for p in projects if p["session_id"] == sid), {"name": "Unknown"})
    return templates.TemplateResponse(request, "label.html", {"sid": sid, "cams": [1, 2, 3], "project": project})

class LabelsIn(BaseModel):
    changes: list[tuple[float, int]]
    highlights: list[tuple[float, float, str]]
    duration: float

@app.post("/api/labels/{sid}")
def save_labels(sid: str, body: LabelsIn):
    d = check_sid(sid)
    ch = sorted(body.changes)
    cam, k, rows = ch[0][1] if ch else 1, 0, ["t,cam"]
    for i in range(int(body.duration * 10)):
        t = i / 10
        while k < len(ch) and ch[k][0] <= t:
            cam = ch[k][1]
            k += 1
        rows.append(f"{t:.1f},{cam}")
    (d / "labels.csv").write_text("\n".join(rows))
    
    h_rows = ["start,end,reason"]
    for a, b, r in body.highlights:
        h_rows.append(f"{a},{b},{r}")
    (d / "highlight_labels.csv").write_text("\n".join(h_rows))
    return {"saved": len(rows) - 1}

class ChatIn(BaseModel):
    message: str

def agent_chat(sid, message, history):
    # Fake agent response until the real AI model is integrated
    return {
        "reply": "This is a demo response from the AI assistant. The real model has not been integrated yet.",
        "steps": [{"tool": "demo_search", "summary": "Searching transcripts..."}],
        "clips": []
    }

@app.post("/api/agent/{sid}")
def agent(sid: str, body: ChatIn):
    d = check_sid(sid)
    if db.gpu_busy():
        raise HTTPException(409, "The GPU is busy processing a video. Please try again in a few minutes.")
    history = db.get_messages(sid)
    result = agent_chat(d, body.message, history)
    db.add_message(sid, "user", body.message)
    db.add_message(sid, "assistant", result["reply"], json.dumps(result["steps"], ensure_ascii=False))
    return result
