import json
import shutil
import subprocess
from pathlib import Path

import yaml

from ai_director.common.io import h264, quality, read_json, run, session_from_argv   # h264(): GPU or CPU, 8-bit
from ai_director.common.paths import CONFIGS
from ai_director.director.brand import caption_fields, load_brand, logo_overlay
from ai_director.director.cards import name_cards
from ai_director.director.pauses import fit_cuts, keep_parts, out_time
from ai_director.director.zoom import zoom_filter, zoom_plan
from ai_director.ingest.probe import probe

CONFIG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))
SPLIT = CONFIG["split"]
LOUDNESS = (CONFIG.get("video") or {}).get("loudness")
WORDS = (CONFIG.get("captions") or {}).get("word_by_word") or {}
VOICE = (CONFIG.get("voice") or {}).get("clean")
COLD = CONFIG.get("cold_open") or {"enabled": False}
HOLD = 100


def split_filter(i, j, xs, w, h, out):
    cw = w // 4 * 2                                    #half the width, an even number of pixels
    x = [int(min(max((0.5 if fx is None else fx) * w - cw / 2, 0), w - cw)) for fx in xs]
    line = SPLIT["line"]
    return (f"[{i}:v]crop={cw}:ih:{x[0]}:0,scale={cw}:{h},setsar=1[l{out}];"
            f"[{j}:v]crop={cw}:ih:{x[1]}:0,scale={cw}:{h},setsar=1[r{out}];"
            f"[l{out}][r{out}]hstack=inputs=2,drawbox=x={cw - line // 2}:y=0:w={line}:h={h}:color=black:t=fill[{out}]")


def clean_voice(session_dir):
    """ clean voice filter """
    return VOICE if VOICE and load_brand(session_dir).get("clean_voice") else ""


def loudness_filter(session_dir):
    """An FFmpeg audio filter that brings the session's sound to video.loudness LUFS with ONE fixed gain for the program
    and every clip"""
    clean = clean_voice(session_dir)
    if LOUDNESS is None:
        return clean or None
    s = Path(session_dir)
    cache = s / "tmp" / "loudness.json"
    m = read_json(cache) if cache.exists() else {}
    if m.get("target") != LOUDNESS or m.get("clean", "") != clean:
        ref = read_json(s / "session.json")["reference_cam"]
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", f"video/cam{ref}.mp4", "-vn", "-af",
                            (f"{clean}," if clean else "") + f"loudnorm=I={LOUDNESS}:TP=-1.5:LRA=11:print_format=json",
                            "-f", "null", "-"],
                           cwd=s, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError(f"Command failed: ffmpeg (loudness)\n{r.stderr[-1500:]}")
        m = {**json.loads(r.stderr[r.stderr.rindex("{"):r.stderr.rindex("}") + 1]), "target": LOUDNESS, "clean": clean}
        cache.parent.mkdir(exist_ok=True)
        cache.write_text(json.dumps(m, indent=2), encoding="utf-8")
    return ((f"{clean}," if clean else "") +
            f"loudnorm=I={LOUDNESS}:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
            f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
            f"linear=true,aresample=48000")


def audio_args(session_dir):
    """FFmpeg output arguments for the sound: the loudness filter (if on) + AAC."""
    lf = loudness_filter(session_dir)
    return (["-af", lf] if lf else []) + ["-c:a", "aac", "-b:a", "192k"]


def render_program(session_dir, cuts, out="program_nocaps.mp4", removed=None):
    """Cut every shot out of its camera, join the shots, add ONE continuous audio track. A split shot = its two
    cameras side by side"""
    meta = read_json(session_dir / "session.json")
    ref = meta["reference_cam"]
    tmp = session_dir / "tmp"
    tmp.mkdir(exist_ok=True)
    if removed:
        cuts = fit_cuts(cuts, removed)                 #camera changes next to a cut pause moved into it (hidden cut)
    zooms = zoom_plan(session_dir, cuts)
    names = []
    for i, c in enumerate(cuts):                       #1. one small video file per shot (per part, pauses cut out)
        for a, b in keep_parts(c["start"], c["end"], removed) if removed else [(c["start"], c["end"])]:
            name, dur = f"seg{len(names):04d}.mp4", f"{b - a:.3f}"
            if c.get("split"):
                size = probe(session_dir / f"video/cam{c['cam']}.mp4")
                cmd = ["ffmpeg", "-y"]
                for cam in c["split"]:
                    cmd += ["-ss", f"{a:.3f}", "-t", dur, "-i", f"video/cam{cam}.mp4"]
                cmd += ["-filter_complex", split_filter(0, 1, c["split_x"], size["width"], size["height"], "v"),
                        "-map", "[v]"]
            else:
                cmd = ["ffmpeg", "-y", "-ss", f"{a:.3f}", "-i", f"video/cam{c['cam']}.mp4", "-t", dur]
                if i in zooms:                         #punch-in: the same picture, slowly closer
                    size = probe(session_dir / f"video/cam{c['cam']}.mp4")
                    cmd += ["-vf", zoom_filter(zooms[i], a, size["width"], size["height"])]
            run(cmd + ["-an", "-r", "30", *h264(quality("program")), f"tmp/{name}"], cwd=session_dir)
            names.append(f"file '{name}'")
    (tmp / "list.txt").write_text("\n".join(names), encoding="utf-8")
    #2. join the shots (no re-encoding) + 3. the sound of the reference camera for the whole video (one loudness)
    if removed:                                        #the same parts of the sound, joined with 10 ms fades (no clicks)
        parts = keep_parts(0.0, meta["duration"], removed)
        graph = [f"[1:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.01,"
                 f"afade=t=out:st={max(b - a - 0.01, 0):.3f}:d=0.01[a{k}]" for k, (a, b) in enumerate(parts)]
        chain = loudness_filter(session_dir)
        graph.append("".join(f"[a{k}]" for k in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1"
                     + (f",{chain}" if chain else "") + "[aout]")
        (tmp / "audio_graph.txt").write_text(";\n".join(graph), encoding="utf-8")
        sound = ["-/filter_complex", "tmp/audio_graph.txt", "-map", "0:v", "-map", "[aout]",   #graph read from the file
                 "-c:a", "aac", "-b:a", "192k"]
    else:
        sound = ["-map", "0:v", "-map", "1:a", *audio_args(session_dir)]
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "tmp/list.txt", "-i", f"video/cam{ref}.mp4",
         *sound, "-c:v", "copy", "-shortest", out], cwd=session_dir)
    for k in range(len(names)):                        #4. clean up the shot files
        (tmp / f"seg{k:04d}.mp4").unlink()
    (tmp / "audio_graph.txt").unlink(missing_ok=True)
    return session_dir / out


def ass_time(t):
    cs = int(round(max(t, 0) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def ass_text(text):
    """Caption text -> ASS: a new line = \\N; { } \\ would be read as ASS codes."""
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def ass_bgr(hex_rgb):
    """"#RRGGBB" -> the colour inside an ASS override tag: &HBBGGRR&."""
    h = hex_rgb.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def line_text(x, lit=None, colour=None):
    """One caption line as ASS text; lit = the index of the word being said -> that word in `colour`"""
    if lit is None:
        return ass_text(x["text"])
    ws = [w["w"] for w in x["words"]]
    before = x["prefix"] + " ".join(ws[:lit]) + (" " if lit else "")
    after = (" " if lit < len(ws) - 1 else "") + " ".join(ws[lit + 1:])
    return f"{ass_text(before)}{{\\1c{colour}}}{ass_text(ws[lit])}{{\\r}}{ass_text(after)}"


def word_steps(item, tmap, a, b):
    """Word-by-word captions"""
    spans = sorted((int(round(tmap(w["start"]) * 100)), int(round(tmap(w["end"]) * 100)), i, k)
                   for i, x in enumerate(item["lines"]) for k, w in enumerate(x["words"]))
    spans = [(s0, nxt[0] if nxt and 0 <= nxt[0] - s1 < HOLD else s1, i, k)       #a short gap: the word stays lit
             for (s0, s1, i, k), nxt in zip(spans, spans[1:] + [None])]
    a, b = int(round(a * 100)), int(round(b * 100))
    points = sorted({a, b, *[min(max(t, a), b) for s0, s1, _, _ in spans for t in (s0, s1)]})
    out = []
    for x, y in zip(points, points[1:]):
        mid = (x + y) / 2
        lit = next(((i, k) for s0, s1, i, k in spans if s0 <= mid < s1), None)
        if out and out[-1][2] == lit:
            out[-1][1] = y
        else:
            out.append([x, y, lit])
    return [(x / 100, y / 100, lit) for x, y, lit in out]


def write_ass(session_dir, path, cuts=None, langs="ar+en", captions=True, vertical=False, window=None, words=None,
              removed=None):
    """ONE .ass subtitle file: the captions (brand colours, the same layout as the old SRT burn: a 384x288 canvas,
    Encoding=-1 for right-to-left lines) and, for the whole video, the name cards (captions=False: only the cards, for
    the video without captions). Returns how many cards.
    langs = "ar", "en" or "ar+en"; vertical = 9:16 sizes; words = word-by-word (None = configs captions);
    removed = pauses cut out of the video (times move earlier); window = (a, b) in the video's time: only that part,
    starting at 0 (a clip, the cold open)."""
    from ai_director.audio.subtitles import FONT, RLM, caption_items
    s = Path(session_dir)
    meta = read_json(s / "session.json")
    brand = load_brand(s)
    f = caption_fields(brand, vertical)
    if words is None:
        words = bool(WORDS.get("clips" if window and not cuts else "program"))
    colour = ass_bgr(brand["captions"]["word_color"])
    arabic = meta["language"] == "ar"
    styles = [
        f"Style: Caption,{FONT},{f['FontSize']},{f['PrimaryColour']},&H000000FF,{f['OutlineColour']},"
        f"{f['BackColour']},0,0,0,0,100,100,0,0,{f['BorderStyle']},{f['Outline']},{f['Shadow']},2,10,10,30,-1",
        #name card: dark box, bottom-left (English) / bottom-right (Arabic), above two lines of captions
        f"Style: Card,{FONT},13,&H00FFFFFF,&H000000FF,&H33141414,&H33141414,1,0,0,0,100,100,0,0,3,3,0,"
        f"{3 if arabic else 1},16,16,92,-1",
    ]
    w0, w1 = window or (0.0, float("inf"))
    tmap = (lambda t: out_time(t, removed)) if removed else (lambda t: t)

    def place(a, b):                         #edit time -> this file's time (None = outside the window / cut out)
        a, b = max(tmap(a), w0), min(tmap(b), w1)
        return (a - w0, b - w0) if b - a >= 0.05 else None

    events = []
    if captions and langs != "none" and (s / "transcript.json").exists():
        for x in caption_items(s, langs):
            t = place(x["start"], x["end"])
            if not t:
                continue
            if words and any(line["words"] for line in x["lines"]):
                for a, b, lit in word_steps(x, lambda u: tmap(u) - w0, *t):
                    text = "\\N".join(line_text(line, lit[1] if lit and lit[0] == i else None, colour)
                                       for i, line in enumerate(x["lines"]))
                    events.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Caption,,0,0,0,,{text}")
            else:
                events.append(f"Dialogue: 0,{ass_time(t[0])},{ass_time(t[1])},Caption,,0,0,0,,{ass_text(x['text'])}")
    cards = name_cards(s, cuts) if cuts else []
    shown = 0
    for c in cards:
        t = place(c["start"], c["end"])
        if not t:
            continue
        shown += 1
        name = (RLM if arabic else "") + ass_text(c["name"])
        role = f"\\N{{\\b0\\fs10\\c&H2C8AEF&}}{(RLM if arabic else '') + ass_text(c['role'])}" if c["role"] else ""
        side = {"left": "\\an1", "right": "\\an3"}.get(c.get("side"), "")      #next to the person (2 on a camera)
        events.append(f"Dialogue: 1,{ass_time(t[0])},{ass_time(t[1])},Card,,0,0,0,,"
                      f"{{{side}\\fad(300,300)}}{name}{role}")
    Path(path).write_text("\n".join([
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 384", "PlayResY: 288", "ScaledBorderAndShadow: yes",
        "WrapStyle: 0", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding", *styles, "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text", *events, ""]),
        encoding="utf-8-sig")
    return shown


def has_audio(path):
    out = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0",
               path])
    return bool(out.strip())


def intro_seconds(session_dir):
    """How long the brand intro is (0 = none)."""
    b = load_brand(session_dir)
    return round(probe(Path(session_dir) / b["intro"])["duration"], 3) if b["intro"] else 0.0


def cold_open(session_dir, removed=None):
    """The cold open (configs cold_open): (start, end) in the plain edit's time (pauses already cut out),
    or None. The strongest moment of the talk (the highlights' interest curve), whole sentences."""
    if not COLD.get("enabled"):
        return None
    from ai_director.director.coldopen import strongest_moment
    m = strongest_moment(session_dir, *COLD.get("seconds", [6, 12]))
    if not m:
        return None
    a, b = out_time(m[0], removed), out_time(m[1], removed)
    return (round(a, 2), round(b, 2)) if b - a >= 2 else None


def lead_in(session_dir, removed=None):
    """(cold open or None, seconds before the edit starts in the finished videos = cold open + brand intro). The web
    player adds these seconds when it jumps to a time of the edit (versions.json "intro")."""
    cold = cold_open(session_dir, removed)
    return cold, round((cold[1] - cold[0] if cold else 0.0) + intro_seconds(session_dir), 3)


def finish(session_dir, inp="program_nocaps.mp4", out="program.mp4", cuts=None, clean=None, langs="ar+en",
           removed=None, cold="config"):
    """The finished videos from the plain edit `inp` (not changed): `out` = captions + name cards + the brand logo,
    intro and outro; `clean` (if given) = the same WITHOUT captions (made first: `out` is the render stage's done
    file). Returns how many name cards. langs = the caption languages; removed = the pauses cut out of
    `inp` (captions and cards move with them); the cold open comes first: "config" = as configs cold_open says, or
    the (start, end) / None a version was made with (its one-language copies match it)."""
    if cold == "config":
        cold = cold_open(session_dir, removed)
    if clean:
        _finish(session_dir, inp, clean, cuts, captions=False, removed=removed, cold=cold)
    return _finish(session_dir, inp, out, cuts, captions=True, langs=langs, removed=removed, cold=cold)


def burn_part(s, inp, out, cuts, captions, langs, removed, window, b, w):
    """The cold open: `window` (a, b) of the plain edit with its captions, cards and logo, faded out at the end."""
    a, e = window
    ass = s / "tmp" / f"{Path(out).stem}.ass"
    write_ass(s, ass, cuts, langs, captions, window=window, removed=removed)
    inputs, graph = ["-ss", f"{a:.3f}", "-t", f"{e - a:.3f}", "-i", inp], [f"[0:v]subtitles=tmp/{ass.name}[main]"]
    last = "main"
    if b["logo"]:
        inputs += ["-i", b["logo"]]
        scale, over = logo_overlay(b, 1, w, "logoed")
        graph.append(scale + f"[{last}][logo]" + over)
        last = "logoed"
    fade = max(e - a - 0.3, 0)
    graph.append(f"[{last}]fade=t=out:st={fade:.3f}:d=0.3[v];[0:a]afade=t=out:st={fade:.3f}:d=0.3[a]")
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
         *h264(quality("program")), "-c:a", "aac", "-b:a", "192k", out], cwd=s)
    ass.unlink(missing_ok=True)


def _finish(session_dir, inp, out, cuts, captions, langs="ar+en", removed=None, cold=None):
    s = Path(session_dir)
    b = load_brand(s)
    size = probe(s / inp)
    w, h = size["width"], size["height"]
    (s / "tmp").mkdir(exist_ok=True)
    ass = s / "tmp" / f"{Path(out).stem}_{'caps' if captions else 'clean'}.ass"
    cards = write_ass(s, ass, cuts, langs, captions=captions, removed=removed)
    inputs, graph, n, last = ["-i", inp], [f"[0:v]subtitles=tmp/{ass.name}[main]"], 1, "main"
    if b["logo"]:
        inputs += ["-i", b["logo"]]
        scale, over = logo_overlay(b, n, w, "logoed")
        graph.append(scale + f"[{last}][logo]" + over)
        n, last = n + 1, "logoed"
    parts = {k: b[k] for k in ("intro", "outro") if b[k]}
    cold_file = None
    if cold:                                                       #cold open: its own small file, made first
        cold_file = f"tmp/{Path(out).stem}_cold.mp4"
        burn_part(s, inp, cold_file, cuts, captions, langs, removed, cold, b, w)
        parts["cold"] = cold_file
    if parts:                                                      #cold open / intro / outro: same size, fps and sound
        for k, path in parts.items():
            inputs += ["-i", path]
            graph.append(f"[{n}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
                         f"setsar=1,fps=30,format=yuv420p[{k}v]")
            if has_audio(s / path):
                graph.append(f"[{n}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[{k}a]")
            else:
                graph.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={probe(s / path)['duration']:.3f}[{k}a]")
            n += 1
        graph.append(f"[{last}]fps=30,format=yuv420p[mv];[0:a]aresample=48000,aformat=sample_fmts=fltp:"
                     f"channel_layouts=stereo[ma]")
        order = [k for k in ("cold", "intro") if k in parts] + ["m"] + (["outro"] if "outro" in parts else [])
        graph.append("".join(f"[{k}v][{k}a]" for k in order) + f"concat=n={len(order)}:v=1:a=1[v][a]")
        maps, audio = ["-map", "[v]", "-map", "[a]"], ["-c:a", "aac", "-b:a", "192k"]
    else:
        graph.append(f"[{last}]null[v]")
        maps, audio = ["-map", "[v]", "-map", "0:a"], ["-c:a", "copy"]
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(graph), *maps, *h264(quality("program")), *audio,
         "-movflags", "+faststart", out], cwd=s)
    ass.unlink(missing_ok=True)
    if cold_file:
        (s / cold_file).unlink(missing_ok=True)
    return cards


def language_file(version, langs):
    """Where a version's video with captions in `langs` is "ar+en" = its program; "none" = its video
    without captions; "ar" / "en" = program_ar.mp4 / program_en.mp4 next to its program (made on request)."""
    if langs == "ar+en":
        return version["program"]
    if langs == "none":
        return version.get("clean") or version["nocaps"]
    return str(Path(version["program"]).with_name(f"program_{langs}.mp4").as_posix())


def add_captions(session_dir, inp="program_nocaps.mp4", out="program.mp4", cuts=None, clean=None, removed=None):
    """program.mp4 from program_nocaps.mp4: captions (if the transcript exists), name cards (cuts = this version's cut
    list), brand; clean = also the video without captions. Kept under its old name: the restyle and the tests call it."""
    finish(Path(session_dir), inp, out, cuts, clean, removed=removed)


def crop_916(crop_x, w=1280, h=720):
    """w x h -> a 9:16 strip around the face (crop_x 0..1; None = the middle) -> h x (h * 16/9).
    1280x720 -> 404x720 -> 720x1280; 1920x1080 -> 608x1080 -> 1080x1920."""
    sw = round(h * 9 / 16 / 2) * 2
    x = (w - sw) // 2 if crop_x is None else int(min(max(crop_x * w - sw / 2, 0), w - sw))
    return f"crop={sw}:{h}:{x}:0,scale={h}:{round(h * 16 / 9 / 2) * 2}"


def render_clip(session_dir, start, end, out, fmt="16:9", source="program", crop_x=None, langs="ar+en"):
    """One short clip"""
    meta = read_json(session_dir / "session.json")
    if not 0 <= start < end <= meta["duration"] + 0.05:
        raise ValueError(f"clip {start}-{end} s is not inside the video (0-{meta['duration']} s)")
    if fmt not in ("16:9", "9:16"):
        raise ValueError(f"fmt must be '16:9' or '9:16', not {fmt!r}")
    if source == "program" and program_removed(session_dir):
        source = program_shots(session_dir, start, end)
    shots = source if isinstance(source, list) else None
    if shots and (abs(shots[0]["start"] - start) > 0.05 or abs(shots[-1]["end"] - end) > 0.05):
        raise ValueError(f"the shots must cover the clip {start}-{end} s")
    video = "program_nocaps.mp4" if source == "program" else f"video/cam{source}.mp4"
    size = probe(session_dir / (f"video/cam{shots[0]['cam']}.mp4" if shots else video))   #9:16 strip follows it
    (session_dir / out).parent.mkdir(parents=True, exist_ok=True)
    (session_dir / "tmp").mkdir(exist_ok=True)
    vf = []
    if fmt == "9:16" and not shots:
        vf.append(crop_916(crop_x, size["width"], size["height"]))
    ass = session_dir / "tmp" / f"{Path(out).stem}.ass"
    if langs != "none":                #caption times shifted so the clip starts at 0; 9:16 sizes scale with the height
        write_ass(session_dir, ass, langs=langs, vertical=fmt == "9:16", window=(start, end))
        vf.append(f"subtitles=tmp/{ass.name}")
    ref = f"video/cam{meta['reference_cam']}.mp4"                                  #the sound of the reference camera
    if shots:                          #one input per shot, joined in ONE FFmpeg run, then the captions on top
        cmd, parts, n = ["ffmpeg", "-y"], [], 0                 #n = inputs so far (a split shot has 2)
        for i, c in enumerate(shots):
            cams = c["split"] if c.get("split") and fmt == "16:9" else [c["cam"]]   #9:16: never split, its main camera
            for cam in cams:
                cmd += ["-ss", f"{c['start']:.3f}", "-t", f"{c['end'] - c['start']:.3f}", "-i", f"video/cam{cam}.mp4"]
            if len(cams) == 2:
                parts.append(split_filter(n, n + 1, c["split_x"], size["width"], size["height"], f"s{i}")
                             + f";[s{i}]fps=30,setpts=PTS-STARTPTS[v{i}]")
            else:
                x = c["crop_x"] if "crop_x" in c else (crop_x or {}).get(c["cam"])    #per shot (2 people) or per camera
                crop = crop_916(x, size["width"], size["height"]) + "," if fmt == "9:16" else ""
                parts.append(f"[{n}:v]{crop}fps=30,setsar=1,setpts=PTS-STARTPTS[v{i}]")
            n += len(cams)
        graph = (";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(len(shots)))
                 + f"concat=n={len(shots)}:v=1:a=0" + "".join("," + f for f in vf) + "[v]")
        cmd += ["-ss", f"{start:.2f}", "-i", ref]
        audio_in, inputs = n, n + 1                                 #the sound = the input after the shots
    else:
        cmd = ["ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", video, "-ss", f"{start:.2f}", "-i", ref]
        graph = "[0:v]" + (",".join(vf) or "null") + "[v]"
        audio_in, inputs = 1, 2
    b = load_brand(session_dir)
    if b["logo"]:                                                   #the brand's logo on every clip
        width = size["width"] if fmt == "16:9" else round(size["height"] * 16 / 9)
        scale, over = logo_overlay(b, inputs, width, "v")
        graph = graph[:-3] + "[base];" + scale + "[base][logo]" + over
        cmd += ["-i", b["logo"]]
    run(cmd + ["-filter_complex", graph, "-map", "[v]", "-map", f"{audio_in}:a", "-t", f"{end - start:.2f}",
               *h264(quality("clips")),
               *audio_args(session_dir), "-movflags", "+faststart", out],
        cwd=session_dir)                                                           #faststart: plays in a browser at once
    ass.unlink(missing_ok=True)
    return session_dir / out


def program_removed(session_dir):
    """The pauses cut out of the AI edit's plain video (v1), [] if none."""
    from ai_director.director.versions import list_versions
    return next((v.get("removed") or [] for v in list_versions(session_dir) if v["id"] == "v1"), [])


def program_shots(session_dir, start, end):
    """The AI edit's shots (cuts.json) from start to end, each from its own camera (a split stays a split)."""
    cuts = read_json(Path(session_dir) / "cuts.json")
    shots = [{**c, "start": round(max(c["start"], start), 3), "end": round(min(c["end"], end), 3)}
             for c in cuts if c["end"] > start and c["start"] < end]
    shots = [c for c in shots if c["end"] - c["start"] > 0.01]
    shots[0]["start"], shots[-1]["end"] = start, end
    return shots


if __name__ == "__main__":
    from ai_director.director.pauses import plan_pauses, saved_seconds
    from ai_director.director.versions import V1, add_version
    s = session_from_argv()
    cuts = read_json(s / "cuts.json")
    removed = plan_pauses(s, cuts)
    render_program(s, cuts, removed=removed)
    cold, lead = lead_in(s, removed)
    if lead or removed or (s / "versions.json").exists():
        add_version(s, {**V1, "intro": lead, "removed": removed, "cold_open": list(cold) if cold else None})
    cards = finish(s, cuts=cuts, clean="program_clean.mp4", removed=removed)   #program.mp4
    print(f"done: {s / 'program.mp4'} + program_clean.mp4 (no captions)" + (f", {cards} name cards" if cards else "")
          + (f", {len(removed)} pauses cut ({saved_seconds(removed)} s shorter)" if removed else "")
          + (f", cold open {cold[1] - cold[0]:.1f} s" if cold else ""))
