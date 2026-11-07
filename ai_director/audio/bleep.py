"""Profanity matching, caption masking, and FFmpeg beep mix for the soundtrack."""
import re
import unicodedata
from pathlib import Path

import yaml

from ai_director.common.io import read_json, run
from ai_director.common.paths import CONFIGS

HARAKAT = dict.fromkeys(map(ord, "ًٌٍَُِّْٰٕٜٓٔٚٛٝٞ"))
LETTER_MAP = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي", "ة": "ه",
    "ؤ": "و", "ئ": "ي",
    "گ": "ك", "ڤ": "ف",
})
CFG = (yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8")) or {}).get("bleep") or {}
HZ = int(CFG.get("hz", 1000))
PAD = float(CFG.get("pad", 0.07))
FADE = float(CFG.get("fade", 0.02))


def normalize(text):
    """One token or phrase: Arabic spelling variants and English case/punctuation collapse to the same key."""
    s = unicodedata.normalize("NFC", str(text or ""))
    s = s.translate(HARAKAT).replace("ـ", "").translate(LETTER_MAP)
    s = s.casefold()
    s = re.sub(r"(.)\1{2,}", r"\1", s)
    s = re.sub(r"[^\w]+", "", s, flags=re.UNICODE)
    return s


def wordlist_path(session_dir=None):
    if session_dir:
        local = Path(session_dir) / "profanity.txt"
        if local.exists():
            return local
    return CONFIGS / "profanity.txt"


def load_phrases(path=None):
    """Normalised phrases, longest first so 'قليل الادب' wins over a shorter leftover."""
    path = Path(path) if path else wordlist_path()
    phrases = []
    if not path.exists():
        return phrases
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        tokens = [normalize(t) for t in line.split()]
        tokens = [t for t in tokens if t]
        if tokens and tokens not in phrases:
            phrases.append(tokens)
    phrases.sort(key=len, reverse=True)
    return phrases


def bleep_enabled(session_dir):
    s = Path(session_dir)
    for name in ("session.json", "upload.json"):
        p = s / name
        if p.exists():
            v = read_json(p).get("bleep_profanity")
            if v is not None:
                return bool(v)
    return False


def match_tokens(tokens, phrases=None):
    """Greedy whole-token matches. tokens = [{'w', 'start', 'end'}, ...]."""
    phrases = phrases if phrases is not None else load_phrases()
    norms = [normalize(t.get("w", "")) for t in tokens]
    hits, i = [], 0
    while i < len(tokens):
        n = next((len(p) for p in phrases if i + len(p) <= len(norms) and norms[i:i + len(p)] == p), 0)
        if n:
            hits.append({"start": float(tokens[i]["start"]), "end": float(tokens[i + n - 1]["end"]),
                         "n": n, "i": i, "text": " ".join(t["w"] for t in tokens[i:i + n])})
            i += n
        else:
            i += 1
    return hits


def match_transcript(rows, phrases=None):
    phrases = phrases if phrases is not None else load_phrases()
    hits = []
    for row in rows:
        for h in match_tokens(row.get("words") or [], phrases):
            hits.append({**h, "id": row.get("id")})
    return hits


def merge_spans(spans):
    out = []
    for a, b in sorted((float(s["start"]), float(s["end"])) if isinstance(s, dict) else s for s in spans):
        if b <= a:
            continue
        if out and a <= out[-1][1] + 1e-6:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def pad_spans(spans, pad=None, duration=None):
    pad = PAD if pad is None else pad
    out = []
    for a, b in merge_spans(spans):
        a, b = a - pad, b + pad
        if duration is not None:
            a, b = max(0.0, a), min(float(duration), b)
        if b > a:
            out.append((round(a, 4), round(b, 4)))
    return merge_spans(out)


def stars(token):
    n = max(3, len(token))
    return "*" * n


def mask_tokens(tokens, phrases=None):
    phrases = phrases if phrases is not None else load_phrases()
    hits = {j for h in match_tokens(tokens, phrases) for j in range(h["i"], h["i"] + h["n"])}
    return [{**t, "w": stars(t["w"]) if i in hits else t["w"]} for i, t in enumerate(tokens)]


def mask_text(text, phrases=None):
    """Mask whole words / phrases in a caption or translation string; spacing is kept."""
    parts = str(text or "").split()
    if not parts:
        return text
    dummy = [{"w": p, "start": i, "end": i + 1} for i, p in enumerate(parts)]
    return " ".join(t["w"] for t in mask_tokens(dummy, phrases))


def media_duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path])
    return float(out.strip())


def _expr(spans):
    if not spans:
        return "0"
    return "+".join(f"between(t,{a:.4f},{b:.4f})" for a, b in spans)


def _beep_volume(spans, fade=None):
    """Frame expression: 1 inside each span, with a short linear fade at each edge."""
    fade = FADE if fade is None else fade
    parts = []
    for a, b in spans:
        d = b - a
        f = min(fade, d / 4) if d > 0 else 0.0
        if f <= 0:
            parts.append(f"between(t,{a:.4f},{b:.4f})")
            continue
        parts.append(
            f"if(between(t,{a:.4f},{a + f:.4f}),(t-{a:.4f})/{f:.4f},"
            f"if(between(t,{a + f:.4f},{b - f:.4f}),1,"
            f"if(between(t,{b - f:.4f},{b:.4f}),({b:.4f}-t)/{f:.4f},0)))"
        )
    return "+".join(parts) if parts else "0"


def mix_bleeps(src, dst, spans, hz=None):
    """Mute `src` on each span and overlay a sine beep with short fades. `spans` are already padded."""
    hz = HZ if hz is None else hz
    src, dst = Path(src), Path(dst)
    spans = merge_spans(spans)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not spans:
        run(["ffmpeg", "-y", "-i", src, "-vn", "-ac", "2", "-ar", "48000", dst])
        return dst
    dur = media_duration(src)
    mute, tone = _expr(spans), _beep_volume(spans)
    graph = (
        f"sine=f={hz}:d={dur:.4f}:r=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[beep];"
        f"[0:a]aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=48000,"
        f"volume=eval=frame:volume='if({mute},0,1)'[speech];"
        f"[beep]volume=eval=frame:volume='{tone}'[tone];"
        f"[speech][tone]amix=inputs=2:duration=first:dropout_transition=0,volume=2[aout]"
    )
    run(["ffmpeg", "-y", "-i", src, "-filter_complex", graph, "-map", "[aout]",
         "-c:a", "pcm_s16le", dst])
    return dst


def cam_soundtrack(session_dir):
    meta = read_json(Path(session_dir) / "session.json")
    return f"video/cam{meta['reference_cam']}.mp4"


def write_bleeped_audio(session_dir):
    """When the session flag is on, write audio_bleeped.wav next to the cameras. Off or no hits: remove a stale file."""
    s = Path(session_dir)
    out = s / "audio_bleeped.wav"
    if not bleep_enabled(s) or not (s / "transcript.json").exists():
        out.unlink(missing_ok=True)
        return None
    rows = read_json(s / "transcript.json")
    src = s / cam_soundtrack(s)
    if not src.exists():
        src = s / "audio.wav"
    if not src.exists():
        return None
    phrases_path = wordlist_path(s)
    phrases = load_phrases(phrases_path)
    spans = pad_spans(match_transcript(rows, phrases), duration=media_duration(src))
    if not spans:
        out.unlink(missing_ok=True)
        return None
    newest = max(src.stat().st_mtime, (s / "transcript.json").stat().st_mtime, phrases_path.stat().st_mtime)
    if out.exists() and out.stat().st_mtime >= newest:
        return out
    return mix_bleeps(src, out, spans)


def soundtrack(session_dir):
    """Relative path of the audio that the program and clips mux: bleeped mix when the flag is on and hits exist."""
    s = Path(session_dir)
    cam = cam_soundtrack(s)
    if not bleep_enabled(s):
        return cam
    write_bleeped_audio(s)
    return "audio_bleeped.wav" if (s / "audio_bleeped.wav").exists() else cam
