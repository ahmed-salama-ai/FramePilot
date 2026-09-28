# ai_director/ingest/proxy.py — synced copies: 720p (render), 640px (perception) and audio.wav
from ai_director.common.io import run


def plan(offsets, durations):
    """Where to start each camera and the common length, in seconds."""
    first = min(offsets.values())
    starts = {c: o - first for c, o in offsets.items()}        # all >= 0
    length = min(durations[c] - starts[c] for c in offsets)    # the part every camera has
    return starts, length


def make_copies(session_dir, offsets, durations, ref):
    starts, length = plan(offsets, durations)
    (session_dir / "video").mkdir(exist_ok=True)
    for c, start in starts.items():
        # 720p, constant 30 fps, with audio (used for rendering)
        run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", f"raw/cam{c}.mp4", "-t", f"{length:.3f}",
             "-map", "0:v:0", "-map", "0:a:0", "-vf", "scale=-2:720", "-r", "30",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-c:a", "aac",
             f"video/cam{c}.mp4"], cwd=session_dir)
        # 640px, no audio (used by Sara's perception)
        run(["ffmpeg", "-y", "-i", f"video/cam{c}.mp4", "-vf", "scale=640:-2", "-an",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
             f"video/cam{c}_640.mp4"], cwd=session_dir)
    # the audio track everyone uses: from the reference camera, 16 kHz mono
    run(["ffmpeg", "-y", "-i", f"video/cam{ref}.mp4", "-vn", "-ac", "1", "-ar", "16000", "audio.wav"],
        cwd=session_dir)
    return starts, length