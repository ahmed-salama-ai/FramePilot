import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

from .common.io import read_json, session_from_argv, write_json
from .common.paths import ROOT

STAGES = [
    ("Ingest + Sync",    "ai_director.ingest.run",      "session.json",      True),
    ("Audio + Captions", "ai_director.audio.run",       "audio_events.json", True),
    ("Perception",       "ai_director.perception.run",  "speaker_map.json",  True),
    ("AI Brain",         "ai_director.brain.run",       "scene.jsonl",       False),
    ("Switching",        "ai_director.director.run",    "cuts.json",         True),
    ("Render",           "ai_director.director.render", "program.mp4",       True),
    ("Highlights",       "ai_director.highlights.run",  "highlights.json",   False),
    ("Evaluation",       "eval.run",                    "metrics.json",      False),
]


def exists(module):
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


def run_stage(session_dir, module, log):
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": os.pathsep.join(p for p in (str(ROOT), os.environ.get("PYTHONPATH", "")) if p)}
    with open(log, "w", encoding="utf-8") as f:
        return subprocess.run([sys.executable, "-m", module, str(session_dir)], cwd=ROOT, env=env,
                              stdout=f, stderr=subprocess.STDOUT).returncode


def tail(path, chars=2000):
    return Path(path).read_text(encoding="utf-8", errors="replace")[-chars:]


def run_pipeline(session_dir, on_progress=lambda stage, pct: print(f"  [{pct:3d}%] {stage}", flush=True)):
    session_dir = Path(session_dir).resolve()
    logs = session_dir / "logs"
    logs.mkdir(exist_ok=True)
    report = []
    times_file = logs / "times.json" 
    times = read_json(times_file) if times_file.exists() else {}
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
        log = logs / f"{i + 1}_{name.split()[0].lower()}.log"
        t0 = time.time()
        code = run_stage(session_dir, module, log)
        secs = round(time.time() - t0, 1)
        times[name] = secs
        write_json(times_file, times)
        problem = (f"failed after {secs} s" if code != 0 else
                   f"ended without writing {done_file}" if not (session_dir / done_file).exists() else None)
        if problem and required:
            raise RuntimeError(f"{name} {problem} (full output: {log}):\n{tail(log)}")
        if problem:
            print(f"  WARNING: {name} {problem}, continuing without it (see {log})", flush=True)   # be made
            report.append((name, f"FAILED (optional, see {log.name})", secs))
            continue
        report.append((name, "done", secs))
    on_progress("Done", 100)
    with open(logs / "pipeline.log", "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M  ") + " | ".join(f"{n}: {s} {t:.0f} s" for n, s, t in report) + "\n")
    return report


if __name__ == "__main__":
    for stage, status, secs in run_pipeline(session_from_argv()):
        print(f"  {stage:18s} {status:24s} {secs:8.1f} s")
