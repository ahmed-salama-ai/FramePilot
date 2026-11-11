"""Profanity matching, caption masking, and FFmpeg beep mix for the soundtrack."""
import re
import unicodedata
from functools import lru_cache
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
# Arabic letters that attach to the start or end of a word without changing the insult (spelled after
# normalize(): ة is already ه). The start goes only on a phrase's first word; what is left must keep 3+ letters.
PREFIXES = ("وال", "فال", "بال", "لل", "ال", "يا", "و", "ف", "ب")
SUFFIXES = ("ين", "ات", "ه")
MIN_STEM = 3
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


def phrases_from(lines):
    """Normalised phrases from lines of text, longest first so 'قليل الادب' wins over a shorter leftover."""
    phrases = []
    for line in lines:
        line = str(line).split("#", 1)[0].strip()
        if not line:
            continue
        tokens = [normalize(t) for t in line.split()]
        tokens = [t for t in tokens if t]
        if tokens and tokens not in phrases:
            phrases.append(tokens)
    phrases.sort(key=len, reverse=True)
    return phrases


def load_phrases(path=None):
    """The word list file as normalised phrases, longest first."""
    path = Path(path) if path else wordlist_path()
    return phrases_from(path.read_text(encoding="utf-8").splitlines()) if path.exists() else []


def custom_words(session_dir):
    """The extra words typed under "Bleep profanity" on the upload page for this recording (upload.json bleep_words)."""
    p = Path(session_dir) / "upload.json"
    words = read_json(p).get("bleep_words") if p.exists() else None
    return [str(w) for w in words or [] if str(w).strip()]


def session_phrases(session_dir):
    """Everything bleeped in this recording: its word list (profanity.txt in the session folder, else
    configs/profanity.txt) plus the words typed at upload."""
    phrases = load_phrases(wordlist_path(session_dir))
    phrases += [p for p in phrases_from(custom_words(session_dir)) if p not in phrases]
    return sorted(phrases, key=len, reverse=True)


def bleep_enabled(session_dir):
    s = Path(session_dir)
    for name in ("session.json", "upload.json"):
        p = s / name
        if p.exists():
            v = read_json(p).get("bleep_profanity")
            if v is not None:
                return bool(v)
    return False


@lru_cache(maxsize=4096)
def word_forms(norm, first):
    """The normalised word plus what is left after one attached start (first word of a phrase only) and/or one
    feminine/plural ending: 'الغبيه' -> {'الغبيه', 'غبيه', 'الغبي', 'غبي'}."""
    heads = {norm}
    if first:
        heads |= {norm[len(p):] for p in PREFIXES if norm.startswith(p) and len(norm) - len(p) >= MIN_STEM}
    forms = set(heads)
    for h in heads:
        forms |= {h[:-len(s)] for s in SUFFIXES if h.endswith(s) and len(h) - len(s) >= MIN_STEM}
    return frozenset(forms)


def phrase_at(norms, i, phrase):
    return all(norms[i + k] == want or want in word_forms(norms[i + k], k == 0) for k, want in enumerate(phrase))


def match_tokens(tokens, phrases=None):
    """Greedy whole-token matches. tokens = [{'w', 'start', 'end'}, ...]. A token also matches when it is a listed
    word with an attached start (ال, و, ف, ب, يا ...) or a feminine/plural ending (ة, ين, ات)."""
    phrases = phrases if phrases is not None else load_phrases()
    norms = [normalize(t.get("w", "")) for t in tokens]
    hits, i = [], 0
    while i < len(tokens):
        n = next((len(p) for p in phrases if i + len(p) <= len(norms) and phrase_at(norms, i, p)), 0)
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


def _beep_volume(spans, fade=None):
    """Expression of t: 1 inside each span, with a short linear fade at each edge. The beep uses it as is and
    the speech uses 1 minus it, so the two cross-fade instead of switching in one sample."""
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
    """Fade the speech out on each span and a sine beep in, then back. `spans` are already padded.
    volume=eval=frame only updates once per audio frame (about 21 ms by default), which turned the fades into
    single steps and clicked; asetnsamples cuts the audio into 1 ms frames so the fades really ramp."""
    hz = HZ if hz is None else hz
    src, dst = Path(src), Path(dst)
    spans = merge_spans(spans)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not spans:
        run(["ffmpeg", "-y", "-i", src, "-vn", "-ac", "2", "-ar", "48000", dst])
        return dst
    dur = media_duration(src)
    tone = _beep_volume(spans)
    graph = (
        f"sine=f={hz}:d={dur:.4f}:r=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"asetnsamples=n=48:p=0[beep];"
        f"[0:a]aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=48000,asetnsamples=n=48:p=0,"
        f"volume=eval=frame:volume='max(0,1-({tone}))'[speech];"
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
    spans = pad_spans(match_transcript(rows, session_phrases(s)), duration=media_duration(src))
    if not spans:
        out.unlink(missing_ok=True)
        return None
    lists = [p for p in (wordlist_path(s), s / "upload.json") if p.exists()]     #the words typed at upload too
    newest = max(src.stat().st_mtime, (s / "transcript.json").stat().st_mtime, *(p.stat().st_mtime for p in lists))
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


# A bleeped word in the translation: the translator wraps the words that mean it in [[ ]]. The transcript keeps the
# real words; the row only remembers which translation words to star (row[MARKS]), for the text it was made from.
MARKS = "translation_bleep"
BRACKETS = re.compile(r"(\[\[|\]\])")


def mark_source(tokens, phrases):
    """The row's words with each bleeped word / phrase in [[ ]] (what the translator sees); None = nothing bleeped."""
    hits = match_tokens(tokens, phrases)
    if not hits:
        return None
    words = [t["w"] for t in tokens]
    for h in hits:
        words[h["i"]] = "[[" + words[h["i"]]
        words[h["i"] + h["n"] - 1] += "]]"
    return " ".join(words)


def split_marks(text):
    """'You are a [[failure]].' -> ('You are a failure.', [3]): the text without [[ ]] and the positions of the words
    that were inside them (a mark inside a word hides the whole word). Stray brackets are dropped."""
    chars, inside = [], False
    for piece in BRACKETS.split(str(text or "")):
        if piece in ("[[", "]]"):
            inside = piece == "[["
        else:
            chars += [(c, inside) for c in piece]
    plain = "".join(c for c, _ in chars)
    words, hide = [], []
    for m in re.finditer(r"\S+", plain):
        if any(chars[k][1] for k in range(m.start(), m.end())):
            hide.append(len(words))
        words.append(m.group())
    return " ".join(words), hide


def saved_marks(row):
    """The translation words to star for this row's bleeped words, or None when nothing is saved or it was saved for
    another text or translation (edited since)."""
    m = row.get(MARKS)
    if m and m.get("text") == row.get("text") and m.get("translation") == row.get("translation"):
        return m.get("hide") or []
    return None


def save_marks(row, hide):
    row[MARKS] = {"text": row["text"], "translation": row["translation"], "hide": sorted(hide)}


def starred_translation(row):
    """The row's translation as words, the saved bleeped ones starred."""
    words = str(row.get("translation") or "").split()
    hide = set(saved_marks(row) or [])
    return [stars(w) if i in hide else w for i, w in enumerate(words)]
