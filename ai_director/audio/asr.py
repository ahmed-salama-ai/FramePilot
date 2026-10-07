# ai_director/audio/asr.py — Gemini 3.5 Transcribe: text + word times + WHO speaks -> transcript.json, diarization.json
# Owner: Nada Ali (rewritten by Ahmed Salama, 2026-10-05: Gemini 3.5 Transcribe replaces Whisper AND pyannote;
# chosen with the Colab notebooks in notebooks/, parts 1-8). It hears the ORIGINAL audio.wav (no filter).
# The audio is cut into ~1-minute pieces at silences (speech.json), the pieces are shared between ALL the Gemini keys
# (each key works on its own piece at the same time), and voices.py gives the same person one name in every piece.
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf

from ..common.io import read_json, write_json
from .gemini import CFG, clients, with_keys
from .voices import link_speakers

# Text speech models are known to INVENT on noise or silence (learned from YouTube subtitles): such rows are dropped
HALLUCINATIONS = ("ترجمة نانسي", "نانسي قنقر", "اشتركوا في القناة", "اشترك في القناة", "لا تنسوا الاشتراك",
                  "شكرا للمشاهدة", "شكراً للمشاهدة", "thanks for watching", "subscribe to", "subtitles by")
SENTENCE_END = (".", "?", "!", "؟")                      # ؟ = the Arabic question mark
GARBAGE = re.compile(r"[　-鿿가-힯�]")      # Chinese/Japanese/Korean letters, broken "�"


def is_hallucination(text):
    low = text.lower()
    return bool(GARBAGE.search(text)) or any(h in low for h in HALLUCINATIONS)


def quietest(audio, sr, a, b):
    """The middle of the quietest 50 ms between a and b seconds."""
    hop = int(0.05 * sr)
    i0, i1 = int(max(a, 0) * sr), min(int(b * sr), len(audio)) - hop
    best = min(range(i0, max(i1, i0 + 1), hop), key=lambda i: float(np.mean(audio[i:i + hop] ** 2)))
    return (best + hop / 2) / sr


def piece_times(total, speech, audio, sr, chunk=60.0, search=10.0):
    """[(start, end)] pieces of about `chunk` seconds that never cut a word: each cut is placed in the middle of the
    silence (a gap between two speech.json parts) nearest to the planned place, within +-search s. Only if there is
    no silence there, it goes at the quietest 50 ms. chunk = 0 -> the full session in one piece."""
    if chunk <= 0:
        return [(0.0, round(total, 2))]
    gaps =[(a["end"] + b["start"]) / 2 for a, b in zip(speech, speech[1:]) if b["start"] > a["end"]]
    cuts = [0.0]
    while total - cuts[-1] > chunk + search:
        planned = cuts[-1] + chunk
        near = [g for g in gaps if abs(g - planned) <= search and g > cuts[-1] + 1]
        cut = min(near, key=lambda g: abs(g - planned)) if near else quietest(audio, sr, planned - search, planned + search)
        cuts.append(round(cut, 2))
    return list(zip(cuts, cuts[1:] + [round(total, 2)]))


def request_config(lang):
    """Verbatim text (every word as said) + speakers + word times, in the session's language."""
    return {"transcription_config": {
        "language_codes": CFG["language_codes"].get(lang, []),
        "mode": {"type": "verbatim", "diarization_mode": "speaker", "timestamp_granularities": ["word"]},
    }}


def to_dict(o):
    """The SDK's answer object -> plain dicts/lists (so it can be saved as JSON)."""
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json", exclude_none=True)
    return json.loads(json.dumps(o, default=lambda z: getattr(z, "__dict__", str(z))))


def ask_gemini(path, lang, start=0, keyed=None):
    """Upload one audio file (Files API) and transcribe it, starting with key number `start`.
    Returns (answer as dict, key name)."""
    def call(client):
        f = client.files.upload(file=str(path))
        try:
            r = client.interactions.create(
                model=CFG["asr_model"], generation_config=request_config(lang),
                input=[{"type": "audio", "uri": f.uri, "mime_type": f.mime_type or "audio/wav"}])
            return to_dict(r)
        finally:
            try:
                client.files.delete(name=f.name)                      # do not leave the audio on Google's side
            except Exception:
                pass
    return with_keys(call, start=start, keyed=keyed)


def find_words(o):
    """Every item with type == 'word_info', anywhere inside Gemini's answer."""
    if isinstance(o, dict):
        if o.get("type") == "word_info":
            yield o
        for v in o.values():
            yield from find_words(v)
    elif isinstance(o, list):
        for v in o:
            yield from find_words(v)


def seconds(v):
    """'12.340s' / 12.34 / {'seconds': 12, 'nanos': 340000000} / '1:02.5' -> seconds (None if unreadable)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        return float(v.get("seconds", 0)) + float(v.get("nanos", 0)) / 1e9
    try:
        t = 0.0
        for p in str(v).strip().rstrip("s").split(":"):
            t = t * 60 + float(p)
        return t
    except ValueError:
        return None


def read_words(answer, offset=0.0):
    """Gemini's words -> [{"w", "start", "end", "speaker"}] in session time, with Gemini's OWN speaker label of that
    piece ("spk_1"). A word without a speaker gets the speaker of the word before it."""
    out, prev = [], None
    for w in find_words(answer):
        a, b = seconds(w.get("start_offset")), seconds(w.get("end_offset"))
        text = str(w.get("text", "")).strip()
        if not text or a is None:
            continue
        if b is None or b <= a:
            b = a + 0.2
        spk = str(w["speaker"]) if w.get("speaker") not in (None, "") else prev
        prev = spk
        out.append({"w": text, "start": round(offset + a, 2), "end": round(offset + b, 2), "speaker": spk})
    return out


def make_rows(words, max_seconds=15.0, pause=1.0, max_chars=None):
    """Words -> transcript.json rows: a new row at a speaker change, a pause > `pause` s, or after `max_seconds`.
    With max_chars (= the caption length), a row also ends before it gets longer than max_chars and after a word
    that ends a sentence (. ? ! ؟), so ONE row = ONE caption and its translation fits exactly that caption."""
    rows = []
    for w in words:
        c = rows[-1] if rows else None
        word = {"w": w["w"], "start": w["start"], "end": w["end"]}
        fits = max_chars is None or (c is not None and len(" ".join(x["w"] for x in c["words"] + [word])) <= max_chars
                                     and not c["words"][-1]["w"].endswith(SENTENCE_END))
        if (c and w["speaker"] == c["speaker"] and w["start"] - c["words"][-1]["end"] <= pause
                and w["end"] - c["words"][0]["start"] <= max_seconds and fits):
            c["words"].append(word)
        else:
            rows.append({"speaker": w["speaker"], "words": [word]})
    return [{"id": i, "start": r["words"][0]["start"], "end": r["words"][-1]["end"], "speaker": r["speaker"],
             "text": " ".join(w["w"] for w in r["words"]), "translation": "", "words": r["words"]}
            for i, r in enumerate(rows)]


def make_diarization(rows, gap=0.5):
    """transcript rows -> diarization.json: who talks when (same speaker less than `gap` s apart = one turn)."""
    out = []
    for r in sorted((r for r in rows if r["speaker"]), key=lambda r: r["start"]):
        if out and r["speaker"] == out[-1]["speaker"] and r["start"] - out[-1]["end"] <= gap:
            out[-1]["end"] = max(out[-1]["end"], r["end"])
        else:
            out.append({"start": r["start"], "end": r["end"], "speaker": r["speaker"]})
    return out


def transcribe_pieces(s, parts, audio, sr, lang, keyed):
    """Every piece -> Gemini's answer. One worker per key, piece k starts with key k % (number of keys), so the
    keys share the work. Each answer is saved in tmp/ at once: a re-run (e.g. after a limit) only does what is left."""
    def one(k):
        a, b = parts[k]
        raw = s / "tmp" / f"gemini_asr_{k:03d}.json"
        if raw.exists():
            saved = read_json(raw)
            if saved.get("piece") == [a, b]:
                return saved["answer"]
        path = s / "tmp" / f"asr_piece_{k:03d}.wav"
        sf.write(path, audio[int(a * sr):int(b * sr)], sr, subtype="PCM_16")
        answer, key = ask_gemini(path, lang, start=k, keyed=keyed)
        write_json(raw, {"piece": [a, b], "key": key, "answer": answer})
        path.unlink(missing_ok=True)
        print(f"    piece {k + 1}/{len(parts)} ({a:.0f}-{b:.0f} s) done with {key}")
        return answer
    with ThreadPoolExecutor(max_workers=len(keyed)) as pool:
        return list(pool.map(one, range(len(parts))))


def run_asr(s: Path, embed=None):
    out = s / "transcript.json"
    if out.exists():
        return
    meta = read_json(s / "session.json")
    up = read_json(s / "upload.json") if (s / "upload.json").exists() else {}
    lang, n_speakers = meta["language"], meta.get("num_speakers") or up.get("num_speakers")
    audio, sr = sf.read(s / "audio.wav", dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    speech = read_json(s / "speech.json") if (s / "speech.json").exists() else []
    parts = piece_times(len(audio) / sr, speech, audio, sr, CFG["chunk_seconds"], CFG["cut_search_seconds"])
    keyed = clients()
    if len(parts) == 1 and len(audio) / sr > 30 * 60:
        print("    WARNING: over 30 min in one request is more than Gemini allows -> set audio.chunk_seconds: 60")
    print(f"    {len(parts)} piece(s), {len(keyed)} Gemini key(s)")
    (s / "tmp").mkdir(exist_ok=True)
    answers = transcribe_pieces(s, parts, audio, sr, lang, keyed)

    # the same voice in different pieces -> one name
    words = [read_words(ans, a) for ans, (a, b) in zip(answers, parts)]
    spans = [{} for _ in parts]
    for k, ws in enumerate(words):
        for w in ws:
            if w["speaker"]:
                spans[k].setdefault(w["speaker"], []).append((w["start"], w["end"]))
    if len(parts) == 1:
        link = {(0, l): i for i, l in enumerate(spans[0])}
    else:
        link = link_speakers(spans, audio, sr, n_speakers, CFG["same_voice"], **({"embed": embed} if embed else {}))
    flat, prev = [], None
    for k, ws in enumerate(words):
        for w in ws:
            g = link.get((k, w["speaker"]))
            g = prev if g is None else g                           # too short to recognise: the speaker before it
            prev = g
            flat.append({**w, "speaker": g})
    if not flat:
        raise RuntimeError(f"Gemini returned no words. Look at the files in {s / 'tmp'} (gemini_asr_*.json).")
    flat.sort(key=lambda w: w["start"])
    order = list(dict.fromkeys(w["speaker"] for w in flat if w["speaker"] is not None))   # first appearance
    name = {g: f"SPEAKER_{i:02d}" for i, g in enumerate(order)}
    flat = [{**w, "speaker": name.get(w["speaker"])} for w in flat]
    rows = [r for r in make_rows(flat, CFG["segment_max_seconds"], max_chars=CFG.get("segment_max_chars"))
            if not is_hallucination(r["text"])]
    rows = [{**r, "id": i} for i, r in enumerate(rows)]
    write_json(s / "diarization.json", make_diarization(rows))
    write_json(out, rows)                                              # transcript.json last
