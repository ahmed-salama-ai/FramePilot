# ai_director/ingest/proxy.py — synced copies: 1080p video/camN.mp4 + audio.wav (the 640px copies were dropped
# 2026-10-09: perception, the AI Brain and debug_video read camN.mp4 and shrink the frames themselves)
# Video is encoded by common/io.h264(): the NVIDIA GPU when there is one, else the CPU; always 8-bit.
#   python -m ai_director.ingest.proxy data/sessions/s01    an existing session: the copies again at
#                                                           ingest.render_height (same sync, audio.wav kept)
import yaml

from ai_director.common.io import decode_on_gpu, h264, quality, read_json, run, session_from_argv
from ai_director.common.paths import CONFIGS

CFG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["ingest"]


def plan(offsets, durations):
    """Where to start each camera and the common length, in seconds."""
    first = min(offsets.values())
    starts = {c: o - first for c, o in offsets.items()}        # all >= 0
    length = min(durations[c] - starts[c] for c in offsets)    # the part every camera has
    return starts, length


def make_copies(session_dir, offsets, durations, ref, audio=True):
    """audio=False: keep audio.wav (an existing session: the transcript's times belong to it)."""
    starts, length = plan(offsets, durations)
    (session_dir / "video").mkdir(exist_ok=True)
    h = CFG["render_height"]
    for c, start in starts.items():
        # render_height (1080p since 2026-10-08, was 720p), constant 30 fps, with audio: every video we make is cut
        # from these (main video, highlights, clips); perception and the AI Brain shrink the frames themselves
        run(["ffmpeg", "-y", *decode_on_gpu(), "-ss", f"{start:.3f}", "-i", f"raw/cam{c}.mp4", "-t", f"{length:.3f}",
             "-map", "0:v:0", "-map", "0:a:0", "-vf", f"scale=-2:{h}", "-r", "30",
             *h264(quality("cameras")), "-c:a", "aac", f"video/cam{c}.mp4"], cwd=session_dir)
    if audio:   # the audio track everyone uses: from the reference camera, 16 kHz mono
        run(["ffmpeg", "-y", "-i", f"video/cam{ref}.mp4", "-vn", "-ac", "1", "-ar", str(CFG["sample_rate"]),
             "audio.wav"], cwd=session_dir)
    return starts, length


def remake(s):
    """The synced copies of an existing session again (e.g. after render_height changed): the offsets come from
    session.json, so nothing is synced again and every time in the session's files stays right."""
    from ai_director.ingest.probe import probe
    meta = read_json(s / "session.json")
    offsets = {c["id"]: c["offset"] for c in meta["cameras"]}
    durations = {c: probe(s / f"raw/cam{c}.mp4")["duration"] for c in offsets}
    _, length = make_copies(s, offsets, durations, meta["reference_cam"], audio=False)
    print(f"done: {len(offsets)} cameras at {CFG['render_height']}p, {length:.2f} s (session.json: {meta['duration']} s)")


if __name__ == "__main__":
    remake(session_from_argv())
