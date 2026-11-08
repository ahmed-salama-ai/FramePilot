import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from ai_director.audio.fillers import MODES, find_candidates, load_fillers, removed_in
from ai_director.common.io import read_json, write_json
from ai_director.director.pauses import fit_cuts, fit_one, pieces_ok, plan_pauses, shot_at

CUT = {"edge_search": 0.06, "move_max": 0.5, "jump_max": 0.06, "min_cut": 0.05, "crossfade": 0.025}
FPS = 30                     #the edit's frame rate: every cut edge is on a frame, so picture and sound stay the same length
MIN_KEEP = 0.15              #a piece of sound shorter than this between two cuts goes too (it would be a fragment)
REPORT = "filler_cuts.json"


def filler_mode(session_dir):
    """off | conservative | standard, from upload.json (the upload page) or session.json; off when not set."""
    s = Path(session_dir)
    for name in ("upload.json", "session.json"):
        p = s / name
        if p.exists():
            mode = read_json(p).get("filler_mode")
            if mode:
                return mode if mode in MODES else "off"
    return "off"


def cut_settings(cfg):
    return {**CUT, **(cfg.get("cut") or {})}


def on_frame(t):
    return round(round(t * FPS) / FPS, 4)


def quiet_point(audio, sr, t, search):
    """The quietest 10 ms within `search` s of t: a cut there lands between words, not inside one."""
    hop = int(0.01 * sr)
    lo, hi = max(0, int((t - search) * sr)), min(len(audio), int((t + search) * sr))
    if hi - lo < 2 * hop:
        return t
    frames = [(float(np.sqrt(np.mean(audio[i:i + hop] ** 2))), i) for i in range(lo, hi - hop, hop // 2)]
    _, best = min(frames)
    return round((best + hop / 2) / sr, 3)


def frame(session_dir, cam, t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(t, 0):.3f}", "-i",
                          str(Path(session_dir) / "video" / f"cam{cam}.mp4"), "-frames:v", "1",
                          "-vf", "scale=64:36,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).astype(float) if len(raw) == 64 * 36 else None


def jump_size(session_dir, cams, r0, r1, frame=frame):
    """How much the picture changes across a cut on the same shot (0 = the same, about 0.22 = a camera change);
    a split shot: the larger of its two cameras. None = a frame could not be read."""
    sizes = []
    for cam in cams:
        a, b = frame(session_dir, cam, r0 - 0.04), frame(session_dir, cam, r1 + 0.04)
        if a is None or b is None:
            return None
        sizes.append(float(np.mean(np.abs(a - b))) / 255)
    return max(sizes)


def merge(spans, gap=0.0):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def fit_free(cuts, r0, r1, done, move_max=float("inf")):
    """fit_one, except that a camera change never moves out of or across another cut piece (`done`: that cut was
    planned with it where it is) and never more than move_max seconds (it would show the wrong person)."""
    fitted = fit_one(cuts, r0, r1)
    for old, new in zip(cuts, fitted):
        if old["start"] != new["start"]:
            lo, hi = sorted((old["start"], new["start"]))
            if hi - lo > move_max + 0.001 or any(a - 0.001 <= hi and b + 0.001 >= lo for a, b in done):
                return cuts
    return fitted


def groups(chosen):
    """Fillers said right after each other ("يعني اه") are cut as one piece."""
    out = []
    for c in sorted(chosen, key=lambda c: c["start"]):
        if out and c["start"] - out[-1][-1]["end"] < MIN_KEEP:
            out[-1].append(c)
        else:
            out.append([c])
    return out


def plan_fillers(session_dir, cuts, mode=None, cfg=None, frame=frame, done=(), shots=False):
    """The filler pieces to remove from this cut list, and a report of every filler the mode removes:
    ([[start, end], ...], [{text, start, end, cut, result}, ...]). The same picture-and-sound cut as pause trimming:
    a camera change close by (cut.move_max) moves into the cut (hidden); on the same camera the cut stays only when
    the picture barely changes (cut.jump_max), otherwise the filler is kept (a visible jump). done = pieces already
    removed (the pauses): their camera changes are not moved again. shots=True: also the cut list with the camera
    changes moved, as the render must use it."""
    s = Path(session_dir)
    mode = filler_mode(s) if mode is None else mode
    nothing = ([], [], cuts) if shots else ([], [])
    if mode == "off" or not cuts:
        return nothing
    cfg = cfg or load_fillers(s)
    st = cut_settings(cfg)
    chosen = removed_in(find_candidates(read_json(s / "transcript.json"), cfg), mode)
    if not chosen:
        return nothing
    audio, sr = sf.read(s / "audio.wav", dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    out, report, cur, done = [], [], [dict(c) for c in cuts], [list(d) for d in done]
    for g in groups(chosen):
        start, end = g[0]["start"], g[-1]["end"]
        r0 = on_frame(quiet_point(audio, sr, start, st["edge_search"]))
        r1 = on_frame(quiet_point(audio, sr, end, st["edge_search"]))
        item = {"text": " ".join(c["text"] for c in g), "start": start, "end": end, "cut": [r0, r1]}
        if r1 - r0 < st["min_cut"]:
            report.append({**item, "result": "kept: too short to cut"})
            continue
        fitted = fit_free(cur, r0, r1, done, st["move_max"])
        if fitted is not cur and not pieces_ok(fitted, r0, r1):
            fitted = cur                       #moving the camera change would leave a flash: try it on its own shot
        before, after = shot_at(fitted, r0 - 0.05), shot_at(fitted, r1 + 0.05)
        if before != after:                    #a flash only matters here: on one shot the picture just goes on
            if not pieces_ok(fitted, r0, r1):
                report.append({**item, "result": "kept: would leave a flash of a shot"})
                continue
            result = "cut: hidden at a camera change"
        else:
            size = jump_size(s, before[1] or (before[0],), r0, r1, frame=frame)
            item["jump"] = None if size is None else round(size, 4)
            if size is None or size > st["jump_max"]:
                report.append({**item, "result": "kept: the jump on the same camera would show"})
                continue
            result = "cut: same camera, the picture barely changes"
        out.append([r0, r1])
        done.append([r0, r1])
        report.append({**item, "result": result})
        cur = fitted
    return (merge(out), report, cur) if shots else (merge(out), report)


def plan_removed(session_dir, cuts, frame=frame):
    """Everything cut out of an edit, in time order: the long pauses ("Remove long pauses" at upload) and the fillers
    (the filler mode at upload), and the cut list with the camera changes moved into those pieces:
    (removed, shots) for render_program(..., shots, removed=removed, fitted=True). What happened to each filler is
    saved in filler_cuts.json."""
    s = Path(session_dir)
    pauses = plan_pauses(s, cuts)
    fillers, report, shots = plan_fillers(s, fit_cuts(cuts, pauses), frame=frame, done=pauses, shots=True)
    if report:
        write_json(s / REPORT, {"mode": filler_mode(s), "cut": sum(r["result"].startswith("cut") for r in report),
                                "seconds": round(sum(b - a for a, b in fillers), 2), "fillers": report})
    else:
        (s / REPORT).unlink(missing_ok=True)
    return merge([list(p) for p in pauses] + fillers, gap=MIN_KEEP), shots


def inside(t, removed):
    return any(a <= t < b for a, b in removed or [])


def drop_cut_words(items, removed):
    """Caption items without the words that were cut out of the video (their middle is inside a removed piece).
    Only lines with word timings can lose words (the transcript's language); a translation line stays as it is."""
    if not removed:
        return items
    out = []
    for x in items:
        lines, changed = [], False
        for line in x["lines"]:
            words = line.get("words") or []
            kept = [w for w in words if not inside((w["start"] + w["end"]) / 2, removed)]
            if len(kept) == len(words):
                lines.append(line)
                continue
            changed = True
            if kept:
                lines.append({**line, "words": kept, "text": line.get("prefix", "") + " ".join(w["w"] for w in kept)})
        if not changed:
            out.append(x)
        elif lines:
            out.append({**x, "lines": lines, "text": "\n".join(line["text"] for line in lines)})
    return out
