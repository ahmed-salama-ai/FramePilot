import time
from pathlib import Path
from app import db

FAKE = True  # set to False on Day 7

def fake_pipeline(session_dir, on_progress):
    for i, stage in enumerate(["Ingest + Sync", "Audio + Captions", "Perception", "AI Brain",
                               "Switching", "Render", "Highlights", "Evaluation"]):
        on_progress(stage, i * 12)
        time.sleep(3)

def main():
    db.init()
    print("Worker ready, waiting for jobs...")
    if not FAKE:
        from ai_director.pipeline import run_pipeline
    while True:
        job = db.next_job()
        if not job:
            time.sleep(2)
            continue
        
        sd = Path("data/sessions") / job["session_id"]
        progress = lambda stage, pct: db.update_job(job["id"], stage=stage, progress=pct)
        try:
            if FAKE:
                fake_pipeline(sd, progress)
            else:
                run_pipeline(sd, progress)
            db.update_job(job["id"], status="done", stage="Done", progress=100)
        except Exception as e:
            db.update_job(job["id"], status="error", error=str(e)[-2000:])

if __name__ == "__main__":
    main()
