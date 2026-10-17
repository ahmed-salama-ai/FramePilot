import json
from datetime import datetime

from app import db

DEFAULT_RATES = {"Ingest + Sync": 0.240, "Audio + Captions": 0.351, "Perception": 0.548, "AI Brain": 0.546,
                 "Switching": 0.0031, "Render": 0.180, "Highlights": 0.057, "Evaluation": 0.0017}
FINISH_RATE = {"Captions, name cards and brand": 0.12, "Highlight clips, trailer and thumbnails": 0.13}
KIND_RATES = {"finish": FINISH_RATE, "language": {"Captions in one language": 0.065}}   # measured on s01 (602 s)
FIXED_SECONDS = {"publish": 45, "thumbnails": 30, "trailer": 45}                         # about, whatever the length
PUBLISH_SECONDS = FIXED_SECONDS["publish"]
DONE_FILES = {"Ingest + Sync": "session.json", "Audio + Captions": "audio_events.json", "Perception": "speaker_map.json",
              "AI Brain": "scene.jsonl", "Switching": "cuts.json", "Render": "program.mp4",
              "Highlights": "highlights.json", "Evaluation": "metrics.json"}


def read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def rates():
    """{stage: seconds per second of video} from every finished session on this PC (default where none)."""
    secs, video = {}, {}
    if db.SESSIONS_DIR.exists():
        for folder in db.SESSIONS_DIR.iterdir():
            times, meta = read(folder / "logs" / "times.json"), read(folder / "session.json")
            if not (isinstance(times, dict) and isinstance(meta, dict) and meta.get("duration")):
                continue
            for stage, t in times.items():
                if stage in DEFAULT_RATES and isinstance(t, (int, float)) and t > 0:
                    secs[stage] = secs.get(stage, 0) + t
                    video[stage] = video.get(stage, 0) + meta["duration"]
    return {stage: secs[stage] / video[stage] if stage in secs else r for stage, r in DEFAULT_RATES.items()}


def duration(sid):
    project = db.get_project(sid) or {}
    if project.get("duration"):
        return float(project["duration"])
    meta = read(db.SESSIONS_DIR / sid / "session.json")
    return float(meta["duration"]) if isinstance(meta, dict) and meta.get("duration") else None


def estimate(job):
    """{"eta_seconds": seconds left, "eta_total": seconds for the whole job} or {} (unknown / finished)."""
    if job["status"] not in ("queued", "running"):
        return {}
    kind = job.get("kind") or "pipeline"
    if kind in FIXED_SECONDS:
        return {"eta_seconds": FIXED_SECONDS[kind], "eta_total": FIXED_SECONDS[kind]}
    dur = duration(job["session_id"])
    if not dur:
        return {}
    r = rates() if kind == "pipeline" else KIND_RATES.get(kind, FINISH_RATE)
    folder = db.SESSIONS_DIR / job["session_id"]
    need = {st: 0.0 if kind == "pipeline" and (folder / DONE_FILES[st]).exists() else rate * dur
            for st, rate in r.items()}
    total = sum(need.values())
    stages = list(r)
    if job["status"] == "queued" or job.get("stage") not in stages:
        return {"eta_seconds": round(total), "eta_total": round(total)}
    k = stages.index(job["stage"])
    elapsed = 0.0
    if job.get("stage_started_at"):
        elapsed = (datetime.now() - datetime.fromisoformat(job["stage_started_at"])).total_seconds()
    now = max(r[job["stage"]] * dur - elapsed, 0.1 * r[job["stage"]] * dur)   # running longer than usual: 10 % left
    left = now + sum(need[st] for st in stages[k + 1:])
    return {"eta_seconds": round(left), "eta_total": round(total)}
