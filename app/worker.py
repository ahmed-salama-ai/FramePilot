import os
import shutil
import sys
import time
import traceback
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app import db

STAGES = [
    "Ingest + Sync",
    "Audio + Captions",
    "Perception",
    "AI Brain",
    "Switching",
    "Render",
    "Highlights",
    "Evaluation"
]

def run_fake_pipeline(session_dir: Path, on_progress):
    """TEST MODE ONLY (FAKE_PIPELINE=1): no AI runs. Copies the mock session's results (a 60 s demo) into the
    session so every page can be tried on a PC without the GPU setup. Every stage is reported as 'simulated'."""
    report = []
    for i, stage in enumerate(STAGES):
        on_progress(stage, int(100 * i / len(STAGES)))
        time.sleep(1)
        report.append([stage, "simulated", 1.0])
    if db.MOCK_SRC.exists():
        for item in db.MOCK_SRC.iterdir():
            if item.name in ("raw", "upload.json"):                  # keep the user's own videos and settings
                continue
            target = session_dir / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
    on_progress("Done", 100)
    return report

def run_finish(session_dir, version, on_progress):
    """"Update video": a NEW version made from `version` (its edit, with the captions as edited, the name cards and the
    brand kit as they are now) + the video without captions; the version it was made from is kept. Then the
    highlights again (and the trailer and thumbnails, if they were made: same moments, new captions / brand)."""
    from ai_director.common.io import read_json
    from ai_director.director.render import finish, lead_in
    from ai_director.director.versions import add_version, get_version, new_version
    from ai_director.highlights.clips import remake_clips
    report = []
    base = get_version(session_dir, version)
    v = new_version(session_dir, "update", f"updated from {base['id']}", base=base)
    on_progress(db.STAGES["finish"][0], 5)
    t = time.time()
    try:
        cards = finish(session_dir, v["nocaps"], v["program"], read_json(session_dir / v["cuts"]), clean=v["clean"],
                       removed=v["removed"])
    except Exception:
        import shutil
        shutil.rmtree(session_dir / "versions" / v["id"], ignore_errors=True)      # no half-made version
        raise
    cold, lead = lead_in(session_dir, v["removed"])
    add_version(session_dir, {**v, "intro": lead, "cold_open": list(cold) if cold else None})
    report.append([db.STAGES["finish"][0], f"done: {v['id']} ({cards} name cards)", round(time.time() - t, 1)])
    on_progress(db.STAGES["finish"][1], 60)
    t = time.time()
    done, problems = [], []                    # the video above is already updated: a failure here is only a warning
    try:
        n = len(remake_clips(session_dir))
        done.append(f"{n} highlights" if n else "no highlights")
    except Exception as e:
        problems.append(f"highlights ({type(e).__name__}: {str(e)[:80]})")
    if (session_dir / "trailer.json").exists():
        try:
            from ai_director.highlights.trailer import make_trailer
            make_trailer(session_dir, again=False)
            done.append("trailer")
        except Exception as e:
            problems.append(f"trailer ({type(e).__name__}: {str(e)[:80]})")
    if (session_dir / "thumbnails.json").exists():
        try:
            from ai_director.director.thumbnail import make_thumbnails
            make_thumbnails(session_dir)
            done.append("thumbnails")
        except Exception as e:
            problems.append(f"thumbnails ({type(e).__name__}: {str(e)[:80]})")
    status = ("done (" + ", ".join(done) + ")") if not problems else \
        "FAILED, not updated: " + "; ".join(problems) + (" (done: " + ", ".join(done) + ")" if done else "")
    if problems:
        print(f"  WARNING: {status}")
    report.append([db.STAGES["finish"][1], status, round(time.time() - t, 1)])
    on_progress("Done", 100)
    return report


def run_language(session_dir, version, langs, on_progress):
    from ai_director.common.io import read_json
    from ai_director.director.render import finish, language_file
    from ai_director.director.versions import get_version
    v = get_version(session_dir, version)
    out = language_file(v, langs)
    on_progress(db.STAGES["language"][0], 5)
    t = time.time()
    tmp = Path(out).with_name(Path(out).stem + "_making.mp4").as_posix()       # never a half-written download
    finish(session_dir, v["nocaps"], tmp, read_json(session_dir / v["cuts"]), langs=langs, removed=v["removed"],
           cold=tuple(v["cold_open"]) if v.get("cold_open") else None)                 # the same as its version
    (session_dir / tmp).replace(session_dir / out)
    on_progress("Done", 100)
    return [[db.STAGES["language"][0], f"done: {v['id']} {langs} ({out})", round(time.time() - t, 1)]]


def run_thumbnails(session_dir, on_progress):
    from ai_director.director.thumbnail import make_thumbnails
    on_progress(db.STAGES["thumbnails"][0], 10)
    t = time.time()
    items = make_thumbnails(session_dir)
    on_progress("Done", 100)
    return [[db.STAGES["thumbnails"][0], f"done ({len(items)} thumbnails)", round(time.time() - t, 1)]]


def run_trailer(session_dir, on_progress):
    from ai_director.highlights.trailer import make_trailer
    on_progress(db.STAGES["trailer"][0], 10)
    t = time.time()
    tr = make_trailer(session_dir)
    on_progress("Done", 100)
    secs = sum(m["end"] - m["start"] for m in tr["moments"])
    return [[db.STAGES["trailer"][0], f"done ({len(tr['moments'])} moments, {secs:.0f} s)", round(time.time() - t, 1)]]


def run_publish(session_dir, on_progress):
    from ai_director.highlights.article import make_article
    from ai_director.highlights.publish import make_publish
    on_progress(db.STAGES["publish"][0], 10)
    t = time.time()
    p = make_publish(session_dir)
    report = [[db.STAGES["publish"][0], f"done ({len(p['chapters'])} chapters, {len(p['posts'])} posts)",
               round(time.time() - t, 1)]]
    on_progress(db.STAGES["publish"][1], 50)
    t = time.time()
    try:                                       # the publish kit above is saved: a failed article is only a warning
        a = make_article(session_dir)
        status = f"done ({len(a['article_ar'].split())} + {len(a['article_en'].split())} words)"
    except Exception as e:
        status = f"FAILED ({type(e).__name__}: {str(e)[:100]})"
        print(f"  WARNING: no article: {status}")
    report.append([db.STAGES["publish"][1], status, round(time.time() - t, 1)])
    on_progress("Done", 100)
    return report


def process_job(job):
    job_id = job["id"]
    sid = job["session_id"]
    kind = job.get("kind") or "pipeline"
    session_dir = db.SESSIONS_DIR / sid

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Job #{job_id} ({kind}) for Session {sid}...")

    def on_progress(stage, pct):
        print(f"  -> Job #{job_id} Stage: {stage} ({pct}%)")
        db.update_job(job_id, stage=stage, progress=pct, stage_started_at=datetime.now().isoformat())

    try:
        if kind == "finish":
            report = run_finish(session_dir, (job.get("args") or {}).get("version", "v1"), on_progress)
        elif kind == "publish":
            report = run_publish(session_dir, on_progress)
        elif kind == "language":
            args = job.get("args") or {}
            report = run_language(session_dir, args.get("version", "v1"), args.get("langs", "ar"), on_progress)
        elif kind == "thumbnails":
            report = run_thumbnails(session_dir, on_progress)
        elif kind == "trailer":
            report = run_trailer(session_dir, on_progress)
        elif os.environ.get("FAKE_PIPELINE", "0") == "1":
            report = run_fake_pipeline(session_dir, on_progress)
        else:
            # Any error here (a stage failed, CUDA out of memory, no internet...) marks the job as failed:
            # it is NEVER replaced by the fake pipeline, so "Done" always means a real program.mp4 exists.
            from ai_director.pipeline import run_pipeline
            report = [list(r) for r in run_pipeline(session_dir, on_progress=on_progress)]

        now_iso = datetime.now().isoformat()
        db.update_job(
            job_id,
            status="done",
            stage="Done",
            progress=100,
            report=report,
            finished_at=now_iso,
            error=None
        )
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Job #{job_id} finished successfully!")

    except Exception as e:
        now_iso = datetime.now().isoformat()
        err_msg = f"{type(e).__name__}: {str(e)}\n\n{traceback.format_exc()}"
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Job #{job_id} FAILED: {str(e)}")

        # Write to session log file for Show Details feature
        logs_dir = session_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "error.log").write_text(err_msg, encoding="utf-8")

        db.update_job(
            job_id,
            status="error",
            error=str(e).splitlines()[0] if str(e) else type(e).__name__,
            finished_at=now_iso
        )

def main():
    db.init()
    stuck = db.reset_running_jobs()
    print("=" * 60)
    print("🎬 FramePilot Worker Process Started" + ("  (TEST MODE: FAKE_PIPELINE=1)" if os.environ.get("FAKE_PIPELINE") == "1" else ""))
    print(f"Watching {db.DB_PATH} for queued jobs...")
    if stuck:
        print(f"{stuck} job(s) were cut off last time and are now marked failed (press Try again on their page).")
    print("=" * 60)

    while True:
        try:
            job = db.next_job()
            if job:
                process_job(job)
            else:
                time.sleep(2)
        except KeyboardInterrupt:
            print("\nWorker stopped by user.")
            break
        except Exception as e:
            print(f"Worker loop error: {e}")
            time.sleep(2)

if __name__ == "__main__":
    main()
