# ai_director/common/io.py — shared helpers (everyone uses these)
import json, subprocess, sys
from functools import lru_cache
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


@lru_cache(maxsize=1)
def video_encoder():
    """'h264_nvenc' (NVIDIA GPU) or 'libx264' (CPU), from configs/default.yaml -> video.encoder.
    auto = try a 0.1 s NVENC encode once: if FFmpeg can use an NVIDIA GPU, use it; otherwise the CPU."""
    import yaml
    from .paths import CONFIGS
    choice = (yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8")).get("video") or {}).get(
        "encoder", "auto")
    if choice != "auto":
        return choice
    try:
        test = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
                               "color=c=black:s=256x256:d=0.1", "-c:v", "h264_nvenc", "-f", "null", "-"],
                              capture_output=True, timeout=60)
        return "h264_nvenc" if test.returncode == 0 else "libx264"
    except (OSError, subprocess.TimeoutExpired):
        return "libx264"


def h264(quality):
    """FFmpeg arguments to write H.264 at a quality level (lower = better, like x264's crf; 20 = very good).
    Always 8-bit yuv420p: browsers and phones can't play 10-bit ("High 10") H.264, and NVENC can't write it."""
    if video_encoder() == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", str(quality), "-b:v", "0",
                "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(quality), "-pix_fmt", "yuv420p"]


def decode_on_gpu():
    """FFmpeg input arguments that decode on the NVIDIA GPU when NVENC is used (put them before -i)."""
    return ["-hwaccel", "cuda"] if video_encoder() == "h264_nvenc" else []


def session_from_argv() -> Path:
    """Every run.py does:  python -m ai_director.x.run data/sessions/s01"""
    return Path(sys.argv[1]).resolve()
