# ai_director/common/io.py — shared helpers (everyone uses these)
import json, subprocess, sys
from pathlib import Path


def read_json(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def write_json(p, obj): Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def read_jsonl(p):
    return [json.loads(line) for line in Path(p).read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(p, rows):
    Path(p).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def run(cmd, cwd=None):
    """Run FFmpeg (or any command). Raises an error with the last lines of output if it fails."""
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd[0]}\n{r.stderr[-1500:]}")
    return r.stdout


def session_from_argv() -> Path:
    """Every run.py does:  python -m ai_director.x.run data/sessions/s01"""
    return Path(sys.argv[1]).resolve()
