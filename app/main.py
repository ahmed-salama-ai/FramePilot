import csv
import io
import json
import logging
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile, File, status
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent     # the project folder: `app` and `ai_director` import from it
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import db, eta
from ai_director.audio import edit as caption_edit
from ai_director.audio.speakers import ROLES
from ai_director.director.versions import delete_version, get_version, list_versions, version_captions

logger = logging.getLogger(__name__)
DATA_DIR = db.SESSIONS_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)
MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}                  # brand logo
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".ogg"}
MAX_LOGO_BYTES = 10 * 1024 * 1024
MAX_BRAND_VIDEO_BYTES = 500 * 1024 * 1024                    # brand intro / outro
MAX_MUSIC_BYTES = 30 * 1024 * 1024
MAX_BRAND_SECONDS = 60
MAX_MUSIC_SECONDS = 600

# Uploads are first written to a temp folder by the server. Keep it next to the data (D:), not in the
# Windows temp folder on C: (C: was full once; 3 cameras = about 2 GB).
UPLOAD_TMP = db.DATA / "tmp_uploads"
UPLOAD_TMP.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(UPLOAD_TMP)

AGENT_LOCK = threading.Lock()                    # one Editor Agent request at a time (two at once = same clip id)

app = FastAPI(
    title="FramePilot - The AI Director",
    description="Multi-camera autonomous AI video director and editing suite",
    version="1.0.0"
)

# Static file mounts
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")

# Mount sessions for video seeking (Starlette StaticFiles natively handles Range requests).
# It serves EVERY file in data/sessions: keep the server on 127.0.0.1 (never --host 0.0.0.0).
app.mount("/files", StaticFiles(directory=DATA_DIR), name="files")

# 3D host avatar bonus mount (only when that folder exists)
avatar_dir = ROOT / "avatar" / "static"
if avatar_dir.is_dir():
    app.mount("/avatar", StaticFiles(directory=avatar_dir, html=True), name="avatar")

templates = Jinja2Templates(directory=ROOT / "app" / "templates")
templates.env.globals["static_version"] = "20261013b"

# Initialize database on startup
db.init()


def check_sid(sid: str) -> Path:
    """Security check: ensure session ID matches safe pattern s01, s02, etc."""
    if not db.SID.fullmatch(sid):
        raise HTTPException(status_code=400, detail="Invalid session ID format")
    session_path = DATA_DIR / sid
    if not session_path.exists():
        raise HTTPException(status_code=404, detail="Session directory not found")
    return session_path


def read_json_file(path: Path):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None

# =========================================================================
# HTML Page Routes
# =========================================================================

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def home_page(request: Request):
    """Page 1: Projects dashboard."""
    projects = db.list_projects()
    return templates.TemplateResponse(request, "index.html", {
        "projects": projects
    })

@app.get("/new", response_class=HTMLResponse)
def new_project_page(request: Request):
    """Page 2: Upload new project."""
    return templates.TemplateResponse(request, "new.html", {})

@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: int):
    """Page 3: Live processing tracker."""
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    project = db.get_project(job["session_id"])
    return templates.TemplateResponse(request, "job.html", {
        "job": job,
        "project": project
    })

@app.get("/results/{sid}", response_class=HTMLResponse)
def results_page(request: Request, sid: str):
    """Page 4: Video player, timeline, highlights & agent chat."""
    check_sid(sid)
    project = db.get_project(sid) or {
        "name": f"Project {sid}",
        "session_id": sid,
        "language": "ar",
        "num_cameras": 3,
        "source": "imported"
    }
    return templates.TemplateResponse(request, "results.html", {
        "sid": sid,
        "project": project
    })

@app.get("/captions/{sid}", response_class=HTMLResponse)
def captions_page(request: Request, sid: str):
    check_sid(sid)
    project = db.get_project(sid) or {"name": f"Session {sid}", "session_id": sid, "language": "ar"}
    return templates.TemplateResponse(request, "captions.html", {"sid": sid, "project": project})

@app.get("/label/{sid}", response_class=HTMLResponse)
def label_page(request: Request, sid: str):
    """Page 6: Multi-camera synced labelling tool."""
    check_sid(sid)
    project = db.get_project(sid) or {"name": f"Session {sid}", "session_id": sid}
    session_dir = DATA_DIR / sid

    # Check which camera files exist
    cams = []
    video_dir = session_dir / "video"
    raw_dir = session_dir / "raw"
    target_dir = video_dir if video_dir.exists() else raw_dir

    if target_dir.exists():
        for i in range(1, 5):
            if (target_dir / f"cam{i}.mp4").exists():
                cams.append(i)
    if not cams:
        cams = [1, 2, 3]

    return templates.TemplateResponse(request, "label.html", {
        "sid": sid,
        "cams": cams,
        "project": project
    })

# =========================================================================
# API Endpoints
# =========================================================================

async def write_upload(file: UploadFile, target: Path, limit: int, what: str):
    """Save an uploaded file in 1 MB pieces; too big -> 413, empty -> 400."""
    total = 0
    with target.open("wb") as buffer:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise HTTPException(status_code=413, detail=f"{what} is bigger than {limit // 1024 ** 2} MB.")
            buffer.write(chunk)
    if total == 0:
        raise HTTPException(status_code=400, detail=f"{what} is empty.")


def parse_people(text: str) -> List[Dict[str, str]]:
    """The people typed at upload: [{"name", "role"}] (names -> name cards in the video)."""
    try:
        items = json.loads(text or "[]")
    except ValueError:
        raise HTTPException(status_code=400, detail="people: not valid JSON")
    if not isinstance(items, list) or len(items) > 10:
        raise HTTPException(status_code=400, detail="people: a list of at most 10 people")
    out = []
    for item in items:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="people: every person needs a name and a role")
        name = " ".join(str(item.get("name", "")).split())[:60]
        role = str(item.get("role", "")).strip().lower()
        if not name:
            continue
        if role and role not in ROLES:
            raise HTTPException(status_code=400, detail=f"people: role must be one of {', '.join(ROLES)}")
        out.append({"name": name, "role": role})
    return out


def audio_seconds(path: Path):
    """How long a sound file is (ffprobe), None if it has no sound."""
    from ai_director.common.io import run
    try:
        info = json.loads(run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path]))
    except (RuntimeError, ValueError):
        return None
    if not any(st.get("codec_type") == "audio" for st in info.get("streams", [])):
        return None
    return float(info.get("format", {}).get("duration") or 0) or None


def is_picture(path: Path) -> bool:
    """True if FFmpeg can really decode the file as a picture (a renamed text file is not)."""
    from ai_director.common.io import run
    try:
        run(["ffmpeg", "-v", "error", "-xerror", "-i", path, "-frames:v", "1", "-f", "null", "-"])
        return True
    except RuntimeError:
        return False


async def save_brand(folder: Path, settings: str = "", logo=None, intro=None, outro=None, remove=(), music=None):
    """brand.json + brand/ files in a session folder (upload or the results page). settings = JSON text with any of
    logo_corner, logo_size, captions {text_color, box_color, box, size, word_color}, clean_voice;
    remove = ["logo", "intro", "outro", "music"]."""
    from pydantic import ValidationError
    from ai_director.common.schemas import Brand
    from ai_director.ingest.probe import probe
    old = read_json_file(folder / "brand.json") or {}
    try:
        new = json.loads(settings or "{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="brand: settings are not valid JSON")
    b = {**old, **{k: new[k] for k in ("logo_corner", "logo_size", "captions", "clean_voice") if k in new}}
    brand_dir = folder / "brand"
    brand_dir.mkdir(exist_ok=True)
    for key in remove:
        if key in ("logo", "intro", "outro", "music") and b.get(key):
            (folder / b[key]).unlink(missing_ok=True)
            b[key] = None
    for key, file, exts, limit in (("logo", logo, IMAGE_EXTENSIONS, MAX_LOGO_BYTES),
                                   ("intro", intro, VIDEO_EXTENSIONS, MAX_BRAND_VIDEO_BYTES),
                                   ("outro", outro, VIDEO_EXTENSIONS, MAX_BRAND_VIDEO_BYTES),
                                   ("music", music, AUDIO_EXTENSIONS, MAX_MUSIC_BYTES)):
        if not file or not getattr(file, "filename", ""):
            continue
        ext = Path(file.filename).suffix.lower()
        if ext not in exts:
            raise HTTPException(status_code=400, detail=f"brand {key}: use {', '.join(sorted(exts))}")
        for old_file in brand_dir.glob(f"{key}.*"):
            old_file.unlink()
        target = brand_dir / f"{key}{ext}"
        await write_upload(file, target, limit, f"The {key}")
        if key == "logo":
            if not is_picture(target):
                target.unlink()
                raise HTTPException(status_code=400, detail="brand logo: not a picture")
        elif key == "music":
            seconds = audio_seconds(target)
            if not seconds or seconds > MAX_MUSIC_SECONDS:
                target.unlink()
                raise HTTPException(status_code=400, detail=f"brand music: a sound file of at most "
                                                            f"{MAX_MUSIC_SECONDS // 60} minutes")
        else:
            try:
                seconds = probe(target)["duration"]
            except Exception:
                target.unlink()
                raise HTTPException(status_code=400, detail=f"brand {key}: not a video")
            if seconds > MAX_BRAND_SECONDS:
                target.unlink()
                raise HTTPException(status_code=400, detail=f"brand {key}: at most {MAX_BRAND_SECONDS} s "
                                                            f"(it is {seconds:.0f} s)")
        b[key] = f"brand/{target.name}"
    try:
        b = Brand.model_validate(b).model_dump()
    except ValidationError as e:
        raise HTTPException(status_code=400, detail="brand: " + "; ".join(
            f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())[:300])
    (folder / "brand.json").write_text(json.dumps(b, ensure_ascii=False, indent=2), encoding="utf-8")
    return b


@app.post("/api/projects")
async def create_project(
    files: List[UploadFile] = File(...),
    name: str = Form(...),
    language: str = Form("ar"),
    wide_cam: int = Form(1),
    num_speakers: Optional[int] = Form(None),
    consent: bool = Form(...),
    people_json: str = Form("[]"),
    brand_json: str = Form(""),
    logo: Optional[UploadFile] = File(None),
    intro: Optional[UploadFile] = File(None),
    outro: Optional[UploadFile] = File(None),
    music: Optional[UploadFile] = File(None),
):
    """Upload 2 to 4 camera videos (+ who is in them, + an optional brand kit), save metadata, create project & queue job."""
    if not consent:
        raise HTTPException(status_code=400, detail="Consent is required to process videos.")
    if not (2 <= len(files) <= 4):
        raise HTTPException(status_code=400, detail="Please upload between 2 and 4 video files.")
    if not name.strip():
        raise HTTPException(status_code=400, detail="Project name cannot be empty.")
    if language not in {"ar", "en"}:
        raise HTTPException(status_code=400, detail="Language must be 'ar' or 'en'.")
    if not 1 <= wide_cam <= len(files):
        raise HTTPException(status_code=400, detail="Wide camera must match one of the uploaded videos.")
    if num_speakers is not None and num_speakers < 1:
        raise HTTPException(status_code=400, detail="Number of speakers must be positive.")
    for file in files:
        if Path(file.filename or "").suffix.lower() not in VIDEO_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Please upload video files only (MP4, MOV, MKV, AVI).")
    people = parse_people(people_json)
    if num_speakers is None and people:
        num_speakers = len(people)              # helps the speech step tell the voices apart

    sid = db.new_session_id()
    session_dir = DATA_DIR / sid
    staging_dir = DATA_DIR / f".{sid}.uploading"
    committed = False
    try:
        raw_dir = staging_dir / "raw"
        raw_dir.mkdir(parents=True)

        for i, file in enumerate(files, 1):
            await write_upload(file, raw_dir / f"cam{i}.mp4", MAX_VIDEO_BYTES, f"Video {i}")   # FFmpeg reads the content
        if brand_json or any(f and getattr(f, "filename", "") for f in (logo, intro, outro, music)):
            await save_brand(staging_dir, brand_json, logo, intro, outro, music=music)

        upload_data = {
            "name": name.strip(),
            "language": language,
            "wide_cam": wide_cam,
            "num_speakers": num_speakers,
            "speaker_names": {},
            "people": people
        }
        (staging_dir / "upload.json").write_text(
            json.dumps(upload_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        try:                                                     # the video's length, for the time estimate
            from ai_director.ingest.probe import probe
            seconds = probe(staging_dir / "raw" / "cam1.mp4")["duration"]
        except Exception:
            seconds = None
        staging_dir.rename(session_dir)
        consent_timestamp = datetime.now().isoformat()
        db.create_project(
            sid=sid,
            name=name.strip(),
            language=language,
            wide_cam=wide_cam,
            num_cameras=len(files),
            consent_at=consent_timestamp,
            duration=seconds
        )
        job_id = db.create_job(sid)
        committed = True
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        if session_dir.exists() and not committed:
            shutil.rmtree(session_dir, ignore_errors=True)       # a half-made upload: nothing worth keeping
            db.forget_project(sid)
        raise

    return {"job_id": job_id, "session_id": sid}

@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: int):
    """Polling endpoint for processing status."""
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.update(eta.estimate(job))
    project = db.get_project(job["session_id"]) or {}
    job["project_name"] = project.get("name", job["session_id"])
    if job["status"] == "error":
        error_log = DATA_DIR / job["session_id"] / "logs" / "error.log"
        try:
            if error_log.is_file():
                job["log_tail"] = error_log.read_text(encoding="utf-8", errors="replace")[-4000:]
        except OSError:
            logger.exception("Could not read error log for job %s", job_id)
    return job

@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: int):
    """Re-queue a failed job."""
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not db.retry_job(job_id):
        raise HTTPException(status_code=409, detail="Only failed jobs can be retried.")
    return {"job_id": job_id, "status": "queued"}

@app.get("/api/sessions/{sid}")
def get_session_data(sid: str):
    """Aggregated JSON payload with everything results dashboard requires."""
    session_dir = check_sid(sid)
    project = db.get_project(sid)

    from ai_director.director.render import language_file
    from ai_director.highlights.publish import descriptions_for
    names = ["session", "speakers", "speaker_map", "highlights", "clips", "metrics", "timeline", "cuts", "publish",
             "brand", "upload", "trailer", "thumbnails"]
    data = {n: read_json_file(session_dir / f"{n}.json") for n in names}

    versions = []
    for v in list_versions(session_dir):
        langs = {k: language_file(v, k) for k in ("ar", "en")}
        shifted = bool(v.get("intro") or v.get("removed")) and isinstance(data["publish"], dict)
        versions.append({**v, "has_nocaps": (session_dir / v["nocaps"]).exists(),
                         "has_program": (session_dir / v["program"]).exists(),
                         "has_clean": bool(v.get("clean")) and (session_dir / v["clean"]).exists(),
                         "languages": {k: {"file": f, "ready": (session_dir / f).exists()} for k, f in langs.items()},
                         "descriptions": descriptions_for(data["publish"], v) if shifted else None})
    try:
        from ai_director.director.stats import speaker_stats
        stats = speaker_stats(session_dir)
    except Exception:
        logger.exception("Speaker stats failed for %s", sid)
        stats = None
    return {"project": project, "versions": versions, "job": db.get_latest_job(sid), "stats": stats,
            "caption_history": len(caption_edit.history(session_dir)), **data}

def speaker_labels(session_dir: Path) -> Dict[str, str]:
    """{SPEAKER_00: "Islam (guest)"} from speakers.json: the name, else the role, else the id."""
    labels = {}
    for item in read_json_file(session_dir / "speakers.json") or []:
        spk = item.get("speaker")
        name, role = (item.get("name") or "").strip(), (item.get("role") or "").strip()
        if spk:
            labels[spk] = f"{name} ({role})" if name and role else name or role or spk
    return labels

@app.get("/api/sessions/{sid}/transcript.txt")
def download_transcript(sid: str):
    """Download clean readable text transcript with speaker names and timestamps."""
    session_dir = check_sid(sid)
    transcript_file = session_dir / "transcript.json"
    if not transcript_file.exists():
        raise HTTPException(status_code=404, detail="Transcript not available for this session")

    try:
        data = json.loads(transcript_file.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read transcript: {e}")

    labels = speaker_labels(session_dir)
    lines = ["FramePilot - Session Transcript", f"Session: {sid}", "=" * 50, ""]

    rows = data if isinstance(data, list) else data.get("rows", data.get("segments", []))
    for row in rows:
        speaker = labels.get(row.get("speaker"), row.get("speaker") or "Speaker")
        start = row.get("start", 0.0)
        minutes = int(start // 60)
        seconds = int(start % 60)
        time_tag = f"[{minutes:02d}:{seconds:02d}]"
        text = row.get("text", "")
        translation = row.get("translation", "")

        lines.append(f"{time_tag} {speaker}:")
        if text:
            lines.append(f"  {text}")
        if translation and translation != text:
            lines.append(f"  ({translation})")
        lines.append("")

    content = "\n".join(lines)
    return PlainTextResponse(
        content,
        headers={"Content-Disposition": f'attachment; filename="transcript_{sid}.txt"'}
    )

class SpeakerRenameIn(BaseModel):
    speakers: Dict[str, str]

@app.patch("/api/sessions/{sid}/speakers")
def update_speakers(sid: str, body: SpeakerRenameIn):
    """Names typed on the results page -> speakers.json (name_source "user" = a name card after "Update video";
    an empty name removes the name and its card). The id itself ("SPEAKER_00") is never saved as a name.
    upload.json is not changed (its speaker_names would also put the name in front of every caption line)."""
    session_dir = check_sid(sid)
    names = {spk: " ".join(name.split())[:60] for spk, name in body.speakers.items()
             if re.fullmatch(r"SPEAKER_\d+", spk) and name.strip() != spk}
    speakers_file = session_dir / "speakers.json"
    spk_list = read_json_file(speakers_file)
    saved = 0
    if isinstance(spk_list, list):
        for item in spk_list:
            if item.get("speaker") in names:
                item["name"] = names[item["speaker"]]
                item["name_source"] = "user" if item["name"] else ""
                saved += 1
        speakers_file.write_text(json.dumps(spk_list, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": saved}

@app.delete("/api/projects/{sid}")
def delete_project(sid: str):
    """Delete a project made in the web app: its folder moves to data/trash/ (not erased).
    Sessions made outside the app (s01-s03, 'imported') are never deleted here."""
    check_sid(sid)
    project = db.get_project(sid)
    if not project or project.get("source") == "imported":
        raise HTTPException(status_code=403, detail="This session was not made in the web app, so the app "
                                                    "does not delete it. Delete its folder by hand if you must.")
    try:
        db.delete_project(sid)
    except OSError as e:
        raise HTTPException(status_code=409, detail="Could not move the project folder (a file is in use). "
                                                    "Stop the video players and try again.") from e
    return {"deleted": True}

class LabelsIn(BaseModel):
    changes: List[List[Any]]
    highlights: List[List[Any]]
    duration: float

@app.post("/api/labels/{sid}")
def save_labels(sid: str, body: LabelsIn):
    """Save user-generated labelling data into labels.csv and highlight_labels.csv."""
    session_dir = check_sid(sid)
    ch = sorted(([float(t), int(c)] for t, c, *_ in body.changes), key=lambda x: x[0])
    cam = ch[0][1] if ch else 1
    k = 0
    rows = ["t,cam"]

    total_steps = int(body.duration * 10)
    for i in range(total_steps):
        t = i / 10.0
        while k < len(ch) and ch[k][0] <= t:
            cam = ch[k][1]
            k += 1
        rows.append(f"{t:.1f},{cam}")

    (session_dir / "labels.csv").write_text("\n".join(rows), encoding="utf-8")

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")                 # quotes a reason that has a comma
    writer.writerow(["start", "end", "reason"])
    for item in body.highlights:
        if len(item) >= 3:
            writer.writerow([item[0], item[1], item[2]])
    (session_dir / "highlight_labels.csv").write_text(out.getvalue().rstrip("\n"), encoding="utf-8")

    return {"saved": len(rows) - 1}

class ChatIn(BaseModel):
    message: str

@app.post("/api/agent/{sid}")
def chat_with_agent(sid: str, body: ChatIn):
    """Interactive chat with FramePilot Editor Agent."""
    session_dir = check_sid(sid)

    if db.gpu_busy():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The GPU is busy processing a video. Please try again in a few minutes."
        )

    user_msg = body.message.strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    if not AGENT_LOCK.acquire(timeout=300):
        raise HTTPException(status_code=409, detail="The Editor Agent is busy with another request. Try again soon.")
    try:
        history = db.get_messages(sid)[-10:]
        try:
            from ai_director.agent.agent import chat as real_agent_chat
            result = real_agent_chat(session_dir, user_msg, history)
        except Exception as e:
            logger.exception("Editor Agent failed for session %s", sid)
            raise HTTPException(
                status_code=503,
                detail="Editor Agent is unavailable. No clip was created; please try again later."
            ) from e

        # Store messages in DB (with the clips, so they show again after a reload)
        db.add_message(sid, "user", user_msg)
        db.add_message(sid, "assistant", result.get("reply", ""), result.get("steps", []), result.get("clips", []))
    finally:
        AGENT_LOCK.release()

    return result

@app.get("/api/agent/{sid}/messages")
def get_agent_messages(sid: str):
    """Retrieve chat history for the editor agent panel."""
    check_sid(sid)
    return db.get_messages(sid)


def no_running_job(sid: str):
    job_id = db.active_job(sid)
    if job_id:
        raise HTTPException(status_code=409, detail=f"Job #{job_id} is still working on this video. Wait until it "
                                                    "is done.")

@app.delete("/api/sessions/{sid}/versions/{vid}")
def remove_version(sid: str, vid: str):
    """Delete a version (never v1): its folder moves to data/trash/."""
    session_dir = check_sid(sid)
    no_running_job(sid)
    try:
        return {"versions": delete_version(session_dir, vid, db.TRASH_DIR)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=409, detail="A file of this version is in use. Stop the video and try "
                                                    "again.") from e

@app.get("/api/sessions/{sid}/export/{vid}")
def export_version(sid: str, vid: str):
    """A .zip for Premiere Pro / DaVinci Resolve: XML + EDL + captions + README."""
    from ai_director.director.export import export_package
    session_dir = check_sid(sid)
    try:
        get_version(session_dir, vid)
        path = export_package(session_dir, vid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (OSError, RuntimeError) as e:
        logger.exception("Export failed for %s %s", sid, vid)
        raise HTTPException(status_code=500, detail=f"Export failed: {e}") from e
    return FileResponse(path, filename=path.name, media_type="application/zip")

@app.get("/api/sessions/{sid}/brand")
def get_brand(sid: str):
    from ai_director.director.brand import load_brand
    return load_brand(check_sid(sid))

@app.post("/api/sessions/{sid}/brand")
async def update_brand(
    sid: str,
    settings: str = Form("{}"),
    remove: str = Form(""),
    logo: Optional[UploadFile] = File(None),
    intro: Optional[UploadFile] = File(None),
    outro: Optional[UploadFile] = File(None),
    music: Optional[UploadFile] = File(None),
):
    """Change the brand kit; the videos change after "Update video"."""
    session_dir = check_sid(sid)
    no_running_job(sid)
    return await save_brand(session_dir, settings, logo, intro, outro,
                            [k.strip() for k in remove.split(",") if k.strip()], music=music)

class UpdateIn(BaseModel):
    version: str = "latest"                       # the version the new one is made from ("latest" = the newest)

@app.post("/api/sessions/{sid}/update")
def update_video(sid: str, body: UpdateIn):
    """Queue "Update video": a NEW version made from this one (edited captions, name cards, brand; with and without
    captions) + the highlights again. The version it is made from is kept."""
    session_dir = check_sid(sid)
    try:
        v = get_version(session_dir, body.version)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not (session_dir / v["nocaps"]).exists():
        raise HTTPException(status_code=400, detail="This version has no video yet.")
    no_running_job(sid)
    return {"job_id": db.create_job(sid, "finish", {"version": v["id"]})}

@app.post("/api/sessions/{sid}/publish")
def queue_publish(sid: str):
    """Queue the publish kit (chapters, summary, social posts): one text-model request."""
    session_dir = check_sid(sid)
    if not (session_dir / "transcript.json").exists():
        raise HTTPException(status_code=400, detail="This video has no transcript yet.")
    no_running_job(sid)
    return {"job_id": db.create_job(sid, "publish")}

@app.get("/api/sessions/{sid}/transcript")
def get_transcript(sid: str):
    """The caption editor's rows: [{id, start, end, speaker, text, translation}] + who each speaker is."""
    session_dir = check_sid(sid)
    rows = read_json_file(session_dir / "transcript.json")
    if not isinstance(rows, list):
        raise HTTPException(status_code=404, detail="Transcript not available for this session")
    return {"rows": [{k: r.get(k) for k in ("id", "start", "end", "speaker", "text", "translation")} for r in rows],
            "speakers": speaker_labels(session_dir),
            "language": (read_json_file(session_dir / "session.json") or {}).get("language", "ar"),
            "saves": len(caption_edit.history(session_dir)),
            "has_original": (session_dir / "history" / "transcript_original.json").exists()}

class RowEdit(BaseModel):
    id: int
    text: Optional[str] = None
    translation: Optional[str] = None

class TranscriptEditIn(BaseModel):
    rows: List[RowEdit]

@app.patch("/api/sessions/{sid}/transcript")
def edit_transcript(sid: str, body: TranscriptEditIn):
    """Save caption edits (the caption files change at once, the burned-in videos after "Update video")."""
    session_dir = check_sid(sid)
    no_running_job(sid)
    n = caption_edit.edit_rows(session_dir, [r.model_dump(exclude_none=True) for r in body.rows])
    return {"saved": n, "saves": len(caption_edit.history(session_dir))}

@app.post("/api/sessions/{sid}/transcript/undo")
def undo_transcript(sid: str):
    session_dir = check_sid(sid)
    no_running_job(sid)
    if not caption_edit.undo(session_dir):
        raise HTTPException(status_code=400, detail="Nothing to undo.")
    return {"saves": len(caption_edit.history(session_dir))}

@app.post("/api/sessions/{sid}/transcript/restore")
def restore_transcript(sid: str):
    session_dir = check_sid(sid)
    no_running_job(sid)
    if not caption_edit.restore_original(session_dir):
        raise HTTPException(status_code=400, detail="The captions were never edited.")
    return {"saves": len(caption_edit.history(session_dir))}


def version_or_400(session_dir: Path, vid: str):
    try:
        return get_version(session_dir, vid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

class LanguageIn(BaseModel):
    version: str = "latest"
    langs: str                                     # "ar", "en", "ar+en" (= its program) or "none" (= without captions)

@app.post("/api/sessions/{sid}/language")
def language_video(sid: str, body: LanguageIn):
    """A version's video with captions in one language: ready -> its file; else a 'language' job makes it."""
    from ai_director.director.render import language_file
    session_dir = check_sid(sid)
    if body.langs not in ("ar", "en", "ar+en", "none"):
        raise HTTPException(status_code=400, detail="langs must be ar, en, ar+en or none")
    v = version_or_400(session_dir, body.version)
    f = language_file(v, body.langs)
    if (session_dir / f).exists():
        return {"ready": True, "file": f}
    if body.langs in ("ar+en", "none") or not (session_dir / v["nocaps"]).exists():
        raise HTTPException(status_code=400, detail="This version has no such video yet.")
    no_running_job(sid)
    return {"ready": False, "job_id": db.create_job(sid, "language", {"version": v["id"], "langs": body.langs})}

@app.get("/api/sessions/{sid}/captions/{vid}")
def version_caption_file(sid: str, vid: str, lang: str = "ar", fmt: str = "srt"):
    """The captions timed for this version's finished video (intro, cold open and cut pauses included)."""
    session_dir = check_sid(sid)
    if lang not in ("ar", "en", "ar+en") or fmt not in ("srt", "vtt"):
        raise HTTPException(status_code=400, detail="lang = ar, en or ar+en; fmt = srt or vtt")
    if not (session_dir / "transcript.json").exists():
        raise HTTPException(status_code=404, detail="Transcript not available for this session")
    v = version_or_400(session_dir, vid)
    name = f"{sid}_{v['id']}_captions_{lang.replace('+', '_')}.{fmt}"
    return PlainTextResponse(version_captions(session_dir, v, lang, fmt), media_type="text/plain; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})

@app.get("/api/sessions/{sid}/why/{vid}")
def why_this_shot(sid: str, vid: str):
    """One reason per shot of this version's cut list (the on-air strip)."""
    from ai_director.director.why import explain
    session_dir = check_sid(sid)
    v = version_or_400(session_dir, vid)
    cuts = read_json_file(session_dir / v["cuts"]) or []
    return explain(session_dir, cuts, v.get("removed"))

@app.get("/api/sessions/{sid}/search")
def search_video(sid: str, q: str = "", mode: str = "words"):
    """Search inside the video: words (spelling variants allowed) or meaning (bge-m3 in Ollama)."""
    from ai_director.agent.search import find_words, search
    session_dir = check_sid(sid)
    q = " ".join(q.split())[:200]
    if not q:
        raise HTTPException(status_code=400, detail="Type something to search for.")
    if not (session_dir / "transcript.json").exists():
        raise HTTPException(status_code=404, detail="Transcript not available for this session")
    if mode == "words":
        return {"mode": mode, "results": find_words(session_dir, q)}
    if mode != "meaning":
        raise HTTPException(status_code=400, detail="mode = words or meaning")
    if db.gpu_busy():
        raise HTTPException(status_code=409, detail="The GPU is busy processing a video. Search by words works now; "
                                                    "search by meaning in a few minutes.")
    try:
        return {"mode": mode, "results": search(session_dir, q, top_k=5)}
    except Exception as e:
        logger.exception("Search by meaning failed for %s", sid)
        raise HTTPException(status_code=503, detail="Search by meaning needs Ollama running with bge-m3. "
                                                    "Search by words still works.") from e

@app.get("/api/sessions/{sid}/podcast/{vid}")
def podcast_audio(sid: str, vid: str, lang: Optional[str] = None):
    """The version as an MP3 with chapters (made on the first click, ~10 s)."""
    from ai_director.director.podcast import make_podcast
    session_dir = check_sid(sid)
    if lang not in (None, "ar", "en"):
        raise HTTPException(status_code=400, detail="lang = ar or en")
    version_or_400(session_dir, vid)
    try:
        path = make_podcast(session_dir, vid, lang)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (OSError, RuntimeError) as e:
        logger.exception("Podcast failed for %s %s", sid, vid)
        raise HTTPException(status_code=500, detail=f"Podcast failed: {str(e)[:200]}") from e
    return FileResponse(path, filename=path.name, media_type="audio/mpeg")

@app.post("/api/sessions/{sid}/thumbnails")
def queue_thumbnails(sid: str):
    session_dir = check_sid(sid)
    if not (session_dir / "highlights.json").exists():
        raise HTTPException(status_code=400, detail="No highlights yet: thumbnails use the highlights.")
    no_running_job(sid)
    return {"job_id": db.create_job(sid, "thumbnails")}

@app.post("/api/sessions/{sid}/trailer")
def queue_trailer(sid: str):
    session_dir = check_sid(sid)
    if not all((session_dir / f).exists() for f in ("transcript.json", "cuts.json", "diarization.json")):
        raise HTTPException(status_code=400, detail="This video is not finished yet.")
    no_running_job(sid)
    return {"job_id": db.create_job(sid, "trailer")}

@app.get("/api/sessions/{sid}/article.md")
def download_article(sid: str, lang: str = "ar"):
    session_dir = check_sid(sid)
    text = (read_json_file(session_dir / "publish.json") or {}).get(f"article_{lang}") if lang in ("ar", "en") else None
    if not text:
        raise HTTPException(status_code=404, detail="No article yet: press Make publish kit.")
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{sid}_article_{lang}.md"'})
