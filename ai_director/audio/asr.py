# ai_director/audio/asr.py — Whisper speech -> text with word times + speaker per segment -> transcript.json
# Owner: Nada Ali (edited by Ahmed Salama: model per language, cleaner audio, session-based hint words,
# hallucination filter)
import re
from pathlib import Path

import soundfile as sf
import yaml

from ..common.io import read_json, run, write_json
from ..common.paths import CONFIGS

CFG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["audio"]

# Neutral everyday Egyptian phrases (no topic, no "podcast"): they only show Whisper the DIALECT and its
# spelling, so it writes "إحنا / النهارده / عشان" instead of the formal "نحن / اليوم / لأن".
EGYPTIAN_STYLE = "إزيك؟ عامل إيه؟ إحنا النهارده بنتكلم، عشان كده لازم نشوف الموضوع ده دلوقتي، يعني مش كده."

# Text Whisper is known to INVENT on noise or silence (it learned it from YouTube subtitles)
HALLUCINATIONS = ("ترجمة نانسي", "نانسي قنقر", "اشتركوا في القناة", "اشترك في القناة", "لا تنسوا الاشتراك",
                  "شكرا للمشاهدة", "شكراً للمشاهدة", "thanks for watching", "subscribe to", "subtitles by")
GARBAGE = re.compile(r"[　-鿿가-힯�]")      # Chinese/Japanese/Korean letters, broken "�"
ARABIC = re.compile(r"[؀-ۿ]")


def pick_device():
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def hint_words(s: Path, lang):
    """Hint text for Whisper, built only from what we know about THIS session (works for any kind of video)."""
    meta = read_json(s / "session.json")
    up = read_json(s / "upload.json") if (s / "upload.json").exists() else {}
    parts = [EGYPTIAN_STYLE] if lang == "ar" else []
    for text in [up.get("name", ""), *(meta.get("keywords") or up.get("keywords") or [])]:
        if text and (lang != "ar" or ARABIC.search(text)):          # an English title would confuse Arabic
            parts.append(text)
    names = (meta.get("speaker_names") or up.get("speaker_names") or {}).values()
    parts += [n for n in names if n]                                 # helps Whisper spell the names
    return " ".join(parts) or None


def is_hallucination(text):
    low = text.lower()
    return bool(GARBAGE.search(text)) or any(h in low for h in HALLUCINATIONS)


def asr_audio(s: Path):
    """The audio Whisper listens to: a cleaned COPY of audio.wav (same length, so the times do not change)."""
    if not CFG["clean_audio"]:
        return s / "audio.wav"
    (s / "tmp").mkdir(exist_ok=True)
    run(["ffmpeg", "-y", "-i", "audio.wav", "-af", CFG["asr_filter"], "-ac", "1", "-ar", "16000",
         "tmp/audio_asr.wav"], cwd=s)
    return s / "tmp" / "audio_asr.wav"


def transcribe(model, audio, lang, hints):
    """The Whisper settings used everywhere (pipeline AND bake-off, so the bake-off measures the real thing)."""
    segments, _ = model.transcribe(audio, language=lang, word_timestamps=True, vad_filter=True, beam_size=5,
                                   condition_on_previous_text=False,     # stops repeated-sentence loops
                                   hotwords=hints,                       # added to EVERY 30 s window
                                   hallucination_silence_threshold=2.0)  # skip text invented over silence
    return [seg for seg in segments if seg.text.strip()]         # list(): Whisper really runs here


def speaker_for(diar, a, b):
    """The speaker who talks most inside [a, b]."""
    ov = {}
    for d in diar:
        o = min(b, d["end"]) - max(a, d["start"])
        if o > 0:
            ov[d["speaker"]] = ov.get(d["speaker"], 0) + o
    return max(ov, key=ov.get) if ov else None


def split_by_speaker(seg, diar):
    """One Whisper segment -> one row per speaker turn. Every word gets the speaker talking at that moment,
    so a long segment with two people in it becomes two rows with the right names."""
    rows, cur = [], None
    for w in (seg.words or []):
        spk = speaker_for(diar, w.start, w.end) or (cur["speaker"] if cur else None)
        word = {"w": w.word.strip(), "start": round(w.start, 2), "end": round(w.end, 2)}
        if cur and spk == cur["speaker"]:
            cur["words"].append(word)
        else:
            cur = {"speaker": spk, "words": [word]}
            rows.append(cur)
    for r in rows:
        r["start"], r["end"] = r["words"][0]["start"], r["words"][-1]["end"]
        r["text"] = " ".join(w["w"] for w in r["words"])
    return rows


def run_asr(s: Path, model_id=None, device=None):
    out = s / "transcript.json"
    if out.exists():
        return
    from faster_whisper import WhisperModel                         # heavy import, only when needed
    device = device or pick_device()
    lang = read_json(s / "session.json")["language"]
    model = WhisperModel(model_id or CFG["asr_models"][lang], device=device,
                         compute_type="int8_float16" if device == "cuda" else "int8")
    audio, sr = sf.read(asr_audio(s), dtype="float32")            # numpy array: avoids PyAV decoding
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    diar = read_json(s / "diarization.json")
    rows = []
    for seg in transcribe(model, audio, lang, hint_words(s, lang)):
        if is_hallucination(seg.text):
            continue                                                # invented text: drop it
        for part in split_by_speaker(seg, diar):
            rows.append({"id": len(rows), "start": part["start"], "end": part["end"], "speaker": part["speaker"],
                         "text": part["text"], "translation": "", "words": part["words"]})
    write_json(out, rows)
