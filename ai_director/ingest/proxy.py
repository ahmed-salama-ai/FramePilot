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
