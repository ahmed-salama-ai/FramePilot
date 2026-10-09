# ai_director/director/render.py — stage 6: cut list -> the edited video (program.mp4); render_clip() for clips
#   python -m ai_director.director.render data/sessions/s01
import shutil
from pathlib import Path

import yaml

from ai_director.common.io import h264, quality, read_json, run, session_from_argv   # h264(): GPU or CPU, 8-bit
from ai_director.common.paths import CONFIGS
from ai_director.ingest.probe import probe

SPLIT = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["split"]


def split_filter(i, j, xs, w, h, out):
    """Split screen (2026-10-09): inputs i and j side by side, each cut to a half-width strip around its person's face
    (xs = face positions 0..1, None = the middle), a thin dark line between -> one w x h picture called [out]."""
    cw = w // 4 * 2                                    # half the width, an even number of pixels
    x = [int(min(max((0.5 if fx is None else fx) * w - cw / 2, 0), w - cw)) for fx in xs]
    line = SPLIT["line"]
    return (f"[{i}:v]crop={cw}:ih:{x[0]}:0,scale={cw}:{h},setsar=1[l{out}];"
            f"[{j}:v]crop={cw}:ih:{x[1]}:0,scale={cw}:{h},setsar=1[r{out}];"
            f"[l{out}][r{out}]hstack=inputs=2,drawbox=x={cw - line // 2}:y=0:w={line}:h={h}:color=black:t=fill[{out}]")


def render_program(session_dir, cuts, out="program_nocaps.mp4"):
    """Cut every shot out of its camera, join the shots, add ONE continuous audio track. A split shot = its two
    cameras side by side."""
    ref = read_json(session_dir / "session.json")["reference_cam"]
    tmp = session_dir / "tmp"
    tmp.mkdir(exist_ok=True)
    names = []
    for i, c in enumerate(cuts):                       # 1. one small video file per shot
        name, dur = f"seg{i:04d}.mp4", f"{c['end'] - c['start']:.3f}"
        if c.get("split"):
            size = probe(session_dir / f"video/cam{c['cam']}.mp4")
            cmd = ["ffmpeg", "-y"]
            for cam in c["split"]:
                cmd += ["-ss", f"{c['start']:.3f}", "-t", dur, "-i", f"video/cam{cam}.mp4"]
            cmd += ["-filter_complex", split_filter(0, 1, c["split_x"], size["width"], size["height"], "v"),
                    "-map", "[v]"]
        else:
            cmd = ["ffmpeg", "-y", "-ss", f"{c['start']:.3f}", "-i", f"video/cam{c['cam']}.mp4", "-t", dur]
        run(cmd + ["-an", "-r", "30", *h264(quality("program")), f"tmp/{name}"], cwd=session_dir)
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


def crop_916(crop_x, w=1280, h=720):
    """w x h -> a 9:16 strip around the face (crop_x 0..1; None = the middle) -> h x (h * 16/9).
    1280x720 -> 404x720 -> 720x1280; 1920x1080 -> 608x1080 -> 1080x1920."""
    sw = round(h * 9 / 16 / 2) * 2
    x = (w - sw) // 2 if crop_x is None else int(min(max(crop_x * w - sw / 2, 0), w - sw))
    return f"crop={sw}:{h}:{x}:0,scale={h}:{round(h * 16 / 9 / 2) * 2}"


def render_clip(session_dir, start, end, out, fmt="16:9", source="program", crop_x=None, langs="ar+en"):
    """One short clip (Day 8), used by Highlights (Sara) and the Editor Agent (Eslam).
    source = "program" (the AI edit), a camera id (e.g. 3 = only that camera) or a list of shots
    [{"start", "end", "cam"}] from start to end (the agent's "mostly one person" edit: every shot from its own camera).
    fmt = "16:9" (the size of the camera copies: 1920x1080 since 2026-10-08, YouTube) or "9:16" (1080x1920, TikTok / Reels).
    crop_x = where the face is, 0..1 (features.face_x), for the 9:16 crop; with shots {cam: face_x} (each shot is
    cropped on its own camera's face), or a "crop_x" in each shot (wins: two people on one camera, 2026-10-09).
    langs = "ar", "en", "ar+en" or "none".
    out = a path inside the session folder, e.g. "highlights/h1_916.mp4"."""
    from ai_director.audio.subtitles import FORCE_STYLE, write_clip_srt      # Nada's caption code
    meta = read_json(session_dir / "session.json")
    if not 0 <= start < end <= meta["duration"] + 0.05:
        raise ValueError(f"clip {start}-{end} s is not inside the video (0-{meta['duration']} s)")
    if fmt not in ("16:9", "9:16"):
        raise ValueError(f"fmt must be '16:9' or '9:16', not {fmt!r}")
    shots = source if isinstance(source, list) else None
    if shots and (abs(shots[0]["start"] - start) > 0.05 or abs(shots[-1]["end"] - end) > 0.05):
        raise ValueError(f"the shots must cover the clip {start}-{end} s")
    video = "program_nocaps.mp4" if source == "program" else f"video/cam{source}.mp4"
    size = probe(session_dir / (f"video/cam{shots[0]['cam']}.mp4" if shots else video))   # 9:16 strip follows it
    (session_dir / out).parent.mkdir(parents=True, exist_ok=True)
    (session_dir / "tmp").mkdir(exist_ok=True)
    vf, style = [], FORCE_STYLE
    if fmt == "9:16":
        if not shots:
            vf.append(crop_916(crop_x, size["width"], size["height"]))
        style = style.replace("FontSize=15", "FontSize=9")    # captions scale with the height: smaller on tall video
    srt = session_dir / "tmp" / f"{Path(out).stem}.srt"
    if langs != "none":
        write_clip_srt(session_dir, start, end, langs, srt)   # caption times shifted so the clip starts at 0
        vf.append(f"subtitles=tmp/{srt.name}:force_style='{style}'")
    ref = f"video/cam{meta['reference_cam']}.mp4"                                  # the sound of the reference camera
    if shots:                          # one input per shot, joined in ONE FFmpeg run, then the captions on top
        cmd, parts, n = ["ffmpeg", "-y"], [], 0                 # n = inputs so far (a split shot has 2)
        for i, c in enumerate(shots):
            cams = c["split"] if c.get("split") and fmt == "16:9" else [c["cam"]]   # 9:16: never split, its main camera
            for cam in cams:
                cmd += ["-ss", f"{c['start']:.3f}", "-t", f"{c['end'] - c['start']:.3f}", "-i", f"video/cam{cam}.mp4"]
            if len(cams) == 2:
                parts.append(split_filter(n, n + 1, c["split_x"], size["width"], size["height"], f"s{i}")
                             + f";[s{i}]fps=30,setpts=PTS-STARTPTS[v{i}]")
            else:
                x = c["crop_x"] if "crop_x" in c else (crop_x or {}).get(c["cam"])    # per shot (2 people) or per camera
                crop = crop_916(x, size["width"], size["height"]) + "," if fmt == "9:16" else ""
                parts.append(f"[{n}:v]{crop}fps=30,setsar=1,setpts=PTS-STARTPTS[v{i}]")
            n += len(cams)
        graph = (";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(len(shots)))
                 + f"concat=n={len(shots)}:v=1:a=0" + "".join("," + f for f in vf) + "[v]")
        cmd += ["-ss", f"{start:.2f}", "-i", ref, "-t", f"{end - start:.2f}", "-filter_complex", graph,
                "-map", "[v]", "-map", f"{n}:a"]
    else:
        cmd = ["ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", video, "-ss", f"{start:.2f}", "-i", ref,
               "-t", f"{end - start:.2f}", "-map", "0:v", "-map", "1:a"]
        if vf:
            cmd += ["-vf", ",".join(vf)]
    run(cmd + [*h264(quality("clips")), "-c:a", "aac", "-movflags", "+faststart", out],
        cwd=session_dir)                                                           # faststart: plays in a browser at once
    srt.unlink(missing_ok=True)
    return session_dir / out


if __name__ == "__main__":
    s = session_from_argv()
    render_program(s, read_json(s / "cuts.json"))
    add_captions(s)                                    # writes program.mp4 LAST: the "done" file
    print("done:", s / "program.mp4")