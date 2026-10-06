# ai_director/director/render.py — stage 6: cut list -> the edited video (program.mp4); render_clip() for clips
#   python -m ai_director.director.render data/sessions/s01
import shutil
from pathlib import Path

from ai_director.common.io import read_json, run, session_from_argv


def render_program(session_dir, cuts, out="program_nocaps.mp4"):
    """Cut every shot out of its camera, join the shots, add ONE continuous audio track."""
    ref = read_json(session_dir / "session.json")["reference_cam"]
    tmp = session_dir / "tmp"
    tmp.mkdir(exist_ok=True)
    names = []
    for i, c in enumerate(cuts):                       # 1. one small video file per shot
        name = f"seg{i:04d}.mp4"
        run(["ffmpeg", "-y", "-ss", f"{c['start']:.3f}", "-i", f"video/cam{c['cam']}.mp4",
             "-t", f"{c['end'] - c['start']:.3f}", "-an", "-r", "30",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", f"tmp/{name}"], cwd=session_dir)
        names.append(f"file '{name}'")
    (tmp / "list.txt").write_text("\n".join(names), encoding="utf-8")
    # 2. join the shots (no re-encoding) + 3. the sound of the reference camera for the whole video
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "tmp/list.txt",
         "-i", f"video/cam{ref}.mp4", "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-shortest", out], cwd=session_dir)
    for i in range(len(cuts)):                         # 4. clean up the shot files
        (tmp / f"seg{i:04d}.mp4").unlink()
    return session_dir / out


def add_captions(session_dir, inp="program_nocaps.mp4", out="program.mp4"):
    """Burn Nada's captions if her code and transcript exist; otherwise copy the video (until Day 7)."""
    try:
        from ai_director.audio.subtitles import burn_captions      # Nada, ready on Day 7
    except ImportError:
        burn_captions = None
    if burn_captions and (session_dir / "transcript.json").exists():
        burn_captions(session_dir, inp, out)
    else:
        shutil.copyfile(session_dir / inp, session_dir / out)


def render_clip(session_dir, start, end, out, fmt="16:9", source="program", crop_x=None, langs="ar+en"):
    """One short clip (Day 8), used by Highlights (Sara) and the Editor Agent (Eslam).
    source = "program" (the AI edit) or a camera id (e.g. 3 = only that camera).
    fmt = "16:9" (1280x720, YouTube) or "9:16" (720x1280, TikTok / Reels).
    crop_x = where the face is, 0..1 (features.face_x), for the 9:16 crop. langs = "ar", "en", "ar+en" or "none".
    out = a path inside the session folder, e.g. "highlights/h1_916.mp4"."""
    from ai_director.audio.subtitles import FORCE_STYLE, write_clip_srt      # Nada's caption code
    meta = read_json(session_dir / "session.json")
    if not 0 <= start < end <= meta["duration"] + 0.05:
        raise ValueError(f"clip {start}-{end} s is not inside the video (0-{meta['duration']} s)")
    if fmt not in ("16:9", "9:16"):
        raise ValueError(f"fmt must be '16:9' or '9:16', not {fmt!r}")
    video = "program_nocaps.mp4" if source == "program" else f"video/cam{source}.mp4"
    (session_dir / out).parent.mkdir(parents=True, exist_ok=True)
    (session_dir / "tmp").mkdir(exist_ok=True)
    vf, style = [], FORCE_STYLE
    if fmt == "9:16":                                  # 1280x720 -> a 404x720 strip around the face -> 720x1280
        x = 438 if crop_x is None else int(min(max(crop_x * 1280 - 202, 0), 1280 - 404))
        vf.append(f"crop=404:720:{x}:0,scale=720:1280")
        style = style.replace("FontSize=15", "FontSize=9")    # captions scale with the height: smaller on tall video
    srt = session_dir / "tmp" / f"{Path(out).stem}.srt"
    if langs != "none":
        write_clip_srt(session_dir, start, end, langs, srt)   # caption times shifted so the clip starts at 0
        vf.append(f"subtitles=tmp/{srt.name}:force_style='{style}'")
    cmd = ["ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", video,
           "-ss", f"{start:.2f}", "-i", f"video/cam{meta['reference_cam']}.mp4",   # the sound of the reference camera
           "-t", f"{end - start:.2f}", "-map", "0:v", "-map", "1:a"]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    run(cmd + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac",
               "-movflags", "+faststart", out], cwd=session_dir)                   # faststart: plays in a browser at once
    srt.unlink(missing_ok=True)
    return session_dir / out


if __name__ == "__main__":
    s = session_from_argv()
    render_program(s, read_json(s / "cuts.json"))
    add_captions(s)                                    # writes program.mp4 LAST: the "done" file
    print("done:", s / "program.mp4")