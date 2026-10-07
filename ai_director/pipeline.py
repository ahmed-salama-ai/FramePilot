# ai_director/pipeline.py — runs all the stages of one session in order, and skips what is already done
#   python -m ai_director.pipeline data/sessions/s01
# Used by the web app's worker (Ahmed Sameh): run_pipeline(session_dir, on_progress)
# Owner: Ahmed Salama
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

from .common.io import session_from_argv
from .common.paths import ROOT

STAGES = [   # (name shown in the web app, python module, the stage's "done" file, required?)
    ("Ingest + Sync",    "ai_director.ingest.run",      "session.json",      True),
    ("Audio + Captions", "ai_director.audio.run",       "audio_events.json", True),
    ("Perception",       "ai_director.perception.run",  "speaker_map.json",  True),
    ("AI Brain",         "ai_director.brain.run",       "scene.jsonl",       False),   # Eslam; needs Ollama
    ("Switching",        "ai_director.director.run",    "cuts.json",         True),
    ("Render",           "ai_director.director.render", "program.mp4",       True),
    ("Highlights",       "ai_director.highlights.run",  "highlights.json",   False),   # later
    ("Evaluation",       "eval.run",                    "metrics.json",      False),   # Day 10
]


def exists(module):
    """True if the module's file is in the repo (find_spec looks for it without running it)."""
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:                                  # even its folder is missing
        return False


def run_stage(session_dir, module, log):
    """One stage in its OWN Python process: when it ends, all its memory (GPU too) is freed.
    Everything it prints goes into the log file. Returns the exit code (0 = success)."""
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",    # Arabic and ✓ in a log file
           "PYTHONPATH": os.pathsep.join(p for p in (str(ROOT), os.environ.get("PYTHONPATH", "")) if p)}
    with open(log, "w", encoding="utf-8") as f:
        return subprocess.run([sys.executable, "-m", module, str(session_dir)], cwd=ROOT, env=env,
                              stdout=f, stderr=subprocess.STDOUT).returncode


def tail(path, chars=2000):
    """The end of a log file (the error is usually there)."""
    return Path(path).read_text(encoding="utf-8", errors="replace")[-chars:]


def run_pipeline(session_dir, on_progress=lambda stage, pct: print(f"  [{pct:3d}%] {stage}", flush=True)):
    """Every stage in order. A stage whose done file exists is skipped, so a second run is instant and a run
    that stopped (error, power cut) continues where it stopped. Returns [(stage, status, seconds), ...]."""
    session_dir = Path(session_dir).resolve()
    logs = session_dir / "logs"
    logs.mkdir(exist_ok=True)
    report = []
    for i, (name, module, done_file, required) in enumerate(STAGES):
        on_progress(name, int(100 * i / len(STAGES)))
        if (session_dir / done_file).exists():
            report.append((name, "already done", 0.0))
            continue
        if not exists(module):
            if required:
                raise RuntimeError(f"{name}: {module} is not in the repo yet")
            report.append((name, "skipped (not built yet)", 0.0))
            continue
        log = logs / f"{i + 1}_{name.split()[0].lower()}.log"        # e.g. logs/2_audio.log
        t0 = time.time()
        code = run_stage(session_dir, module, log)
        secs = round(time.time() - t0, 1)
        problem = (f"failed after {secs} s" if code != 0 else
                   f"ended without writing {done_file}" if not (session_dir / done_file).exists() else None)
        if problem and required:
            raise RuntimeError(f"{name} {problem} (full output: {log}):\n{tail(log)}")
        if problem:                          # an optional stage (e.g. AI Brain without Ollama): the video can still
            print(f"  WARNING: {name} {problem}, continuing without it (see {log})", flush=True)   # be made
            report.append((name, f"FAILED (optional, see {log.name})", secs))
            continue
        report.append((name, "done", secs))
    on_progress("Done", 100)
    with open(logs / "pipeline.log", "a", encoding="utf-8") as f:     # one line per run: the history + times
        f.write(time.strftime("%Y-%m-%d %H:%M  ") + " | ".join(f"{n}: {s} {t:.0f} s" for n, s, t in report) + "\n")
    return report


if __name__ == "__main__":
    for stage, status, secs in run_pipeline(session_from_argv()):
        print(f"  {stage:18s} {status:24s} {secs:8.1f} s")
