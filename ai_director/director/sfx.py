import json
import re
import subprocess
from pathlib import Path

import yaml

from ai_director.common.io import read_json
from ai_director.common.paths import CONFIGS, ROOT

SFX_DIR = ROOT / "assets" / "sfx"
SOUND = {"cut": "whoosh", "title": "hit", "caption": "pop"}       # event -> sound family
PER_FAMILY = {f: len(list(SFX_DIR.glob(f"{f}_*.ogg"))) for f in SOUND.values()}  # files of a family: take turns
PRIORITY = {"cut": 0, "caption": 1}                                 # in a clip, when two compete, the cut wins
CFG = {"per_minute": 6, "min_gap": 3.0, "edge": 0.5, "lead": {"cut": 0.05, "title": 0.0, "caption": 0.0},
       "levels": {"low": -10, "medium": -6, "high": -2},
       **((yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8")) or {}).get("sfx") or {})}
VOLUMES = tuple(CFG["levels"])
LIBRARY_LOUDNESS = -21.0          # every file in assets/sfx: its loudest 400 ms, LUFS momentary (see tests/test_sfx.py)
LIMIT = 0.891                     # -1 dBFS: an effect on a loud word never clips


def job_volume(session_dir):
    """The volume chosen at upload (upload.json "sound_effects": {"on", "volume"}), or None = no effects."""
    p = Path(session_dir) / "upload.json"
    choice = (read_json(p).get("sound_effects") or {}) if p.exists() else {}
    volume = choice.get("volume", "medium")
    return volume if choice.get("on") and volume in VOLUMES else None


def speech_level(session_dir):
    """The recording's speech loudness (integrated LUFS of the sound the clips use), measured once. Only needed when
    video.loudness is off (otherwise the speech is at that loudness when the effects are added)."""
    from ai_director.audio.bleep import soundtrack
    s = Path(session_dir)
    src = s / soundtrack(s)
    cache = s / "tmp" / "sfx_speech.json"
    key = {"src": str(src.name), "size": src.stat().st_size}
    if cache.exists() and {k: read_json(cache).get(k) for k in key} == key:
        return read_json(cache)["lufs"]
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-vn", "-af", "ebur128", "-f", "null",
                          "-"], capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    lufs = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", err)[-1])
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps({**key, "lufs": lufs}), encoding="utf-8")
    return lufs


def set_gains(effects, session_dir, volume, cfg=None, speech=None):
    """Each effect's gain, so its loudest 400 ms sits levels[volume] dB under the speech loudness. speech = the speech
    loudness where the effects are added: after the loudness filter, its target (video.loudness). The same while people
    talk: in a talk show somebody nearly always does, and a short effect under the voice must still be heard."""
    from ai_director.director.render import LOUDNESS
    cfg = {**CFG, **(cfg or {})}
    if speech is None:
        speech = LOUDNESS if LOUDNESS is not None else speech_level(session_dir)
    for e in effects:
        e["gain_db"] = round(speech + cfg["levels"][volume] - LIBRARY_LOUDNESS, 2)
    return effects


def plan_clip(session_dir, start, end, fmt, source, langs, volume, cfg=None):
    """The effects a clip plays, with their sounds, start times and gains (clip time)."""
    chosen = choose(clip_events(session_dir, start, end, fmt, source, langs), end - start, cfg)
    return set_gains(chosen, session_dir, volume, cfg)


def plan_trailer(session_dir, lengths, volume, cfg=None):
    """The trailer's effects (trailer time). lengths = the rendered moments' real lengths, in order (a frame more or
    less than end - start: where they really join)."""
    return set_gains(with_sounds(trailer_events(lengths), cfg), session_dir, volume, cfg)


def mix_lines(effects, first_input, speech, out):
    """FFmpeg filter lines: the speech (`speech`, e.g. "[sp]", after the loudness filter) with every effect (inputs
    first_input, first_input + 1, ...: the effects' files in order) placed at its time and gain -> [out].
    normalize=0: the speech keeps its level; the limiter (no delay: latency=1) only acts where the sum passes -1 dBFS."""
    fmt = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
    lines = [f"{speech}{fmt}[sfx_sp]"]
    for k, e in enumerate(effects):
        ms = int(round(e["at"] * 1000))
        lines.append(f"[{first_input + k}:a]{fmt},volume={e['gain_db']:.2f}dB,adelay={ms}:all=1[sfx{k}]")
    lines.append("[sfx_sp]" + "".join(f"[sfx{k}]" for k in range(len(effects))) +
                 f"amix=inputs={len(effects) + 1}:normalize=0:duration=first,"
                 f"alimiter=limit={LIMIT}:level=0:latency=1[{out}]")
    return lines


def visible_cuts(shots, fmt):
    """Times where the picture changes inside a clip: a new camera, a split screen starting or ending (16:9), or the
    crop moving to another person (9:16 and 1:1, which never split)."""
    def look(c):
        return (c["cam"], tuple(c.get("split") or ())) if fmt == "16:9" else (c["cam"], c.get("crop_x"))
    return [b["start"] for a, b in zip(shots, shots[1:]) if look(a) != look(b)]


def clip_shots(session_dir, start, end, source):
    """The shots a clip is made of: its own list, the AI edit's camera changes, or one camera (no cuts)."""
    if isinstance(source, list):
        return source
    if source == "program":
        from ai_director.director.render import program_shots
        return program_shots(session_dir, start, end)
    return []


def caption_starts(session_dir, start, end, langs):
    """When a new caption line appears inside the clip (the one already showing at its start does not count)."""
    if langs == "none" or not (Path(session_dir) / "transcript.json").exists():
        return []
    from ai_director.audio.subtitles import caption_items
    return [x["start"] for x in caption_items(Path(session_dir), langs) if start < x["start"] < end]


def clip_events(session_dir, start, end, fmt="16:9", source="program", langs="ar+en"):
    """Every possible effect in a clip, in the clip's own time (0 = its first frame): a whoosh at each cut, a pop when
    a caption line appears. Not capped yet (see choose)."""
    shots = clip_shots(session_dir, start, end, source)
    return ([{"t": round(t - start, 3), "kind": "cut"} for t in visible_cuts(shots, fmt)] +
            [{"t": round(t - start, 3), "kind": "caption"} for t in caption_starts(session_dir, start, end, langs)])


def trailer_events(lengths):
    """The trailer's effects: a whoosh where one moment ends and the next begins, and a hit when the end card (the
    title) appears - every join and the card, no limits (count, gap), and nothing inside the moments."""
    bounds = [round(sum(lengths[:k]), 3) for k in range(1, len(lengths) + 1)]
    return [{"t": t, "kind": "cut"} for t in bounds[:-1]] + [{"t": bounds[-1], "kind": "title"}]


def with_sounds(effects, cfg=None):
    """Each effect's sound (a family's files take turns) and its start time (`at`: a little before the event, so the
    loudest part lands on it), in time order."""
    cfg = {**CFG, **(cfg or {})}
    effects = sorted(effects, key=lambda e: e["t"])
    used = {}
    for e in effects:
        family, n = SOUND[e["kind"]], used.get(e["kind"], 0)
        used[e["kind"]] = n + 1
        e["sound"] = f"{family}_{n % PER_FAMILY[family] + 1}.ogg"
        e["at"] = round(max(e["t"] - cfg["lead"].get(e["kind"], 0.0), 0.0), 3)
    return effects


def choose(events, length, cfg=None):
    """The effects a clip plays: none near its edges, at least min_gap apart, and at most per_minute a minute - a
    rate, so a 30 s clip gets half as many (checked over every stretch of a minute, or of the whole clip if it is
    shorter). Cuts first, then captions. Within each the effects are spread out: the next one is the allowed event
    farthest from the ones already chosen and from the clip's start and end. Then their sounds (with_sounds)."""
    cfg = {**CFG, **(cfg or {})}
    edge, gap = cfg["edge"], cfg["min_gap"]
    window = min(60.0, length)
    most = max(1, int(cfg["per_minute"] * window / 60 + 1e-9))
    chosen = []

    def allowed(e):
        if not edge <= e["t"] <= length - edge or any(abs(e["t"] - c["t"]) < gap for c in chosen):
            return False
        trial = chosen + [e]
        return all(sum(a["t"] <= b["t"] < a["t"] + window for b in trial) <= most for a in trial)

    groups = {}
    for e in events:
        groups.setdefault(PRIORITY[e["kind"]], []).append(e)
    for key in sorted(groups):
        left = sorted(groups[key], key=lambda e: e["t"])
        while True:
            ok = [e for e in left if allowed(e)]
            if not ok:
                break
            marks = [0.0, length] + [c["t"] for c in chosen]
            best = max(ok, key=lambda e: min(abs(e["t"] - m) for m in marks))
            chosen.append(best)
            left.remove(best)
    return with_sounds(chosen, cfg)
