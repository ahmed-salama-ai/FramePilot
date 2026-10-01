# tests/test_asr.py — the speech-to-text helpers that run without a GPU (Whisper itself is not needed here)
import shutil
from types import SimpleNamespace

import numpy as np
import soundfile as sf
from scipy.signal import correlate

from ai_director.audio.asr import EGYPTIAN_STYLE, asr_audio, hint_words, is_hallucination, split_by_speaker
from ai_director.common.io import write_json
from ai_director.common.paths import MOCK


def test_hint_words_come_from_the_session(tmp_path):
    assert hint_words(MOCK, "ar") == EGYPTIAN_STYLE + " Host Guest"          # dialect + speaker names
    write_json(tmp_path / "session.json", {"language": "en", "speaker_names": {"SPEAKER_00": "Mona"}})
    write_json(tmp_path / "upload.json", {"name": "Board meeting", "keywords": ["budget", "Q3"]})
    assert hint_words(tmp_path, "en") == "Board meeting budget Q3 Mona"      # no Egyptian text for English


def test_english_title_is_not_used_for_arabic(tmp_path):
    write_json(tmp_path / "session.json", {"language": "ar"})
    write_json(tmp_path / "upload.json", {"name": "Lecture 3", "keywords": ["الذكاء الاصطناعي"]})
    assert hint_words(tmp_path, "ar") == EGYPTIAN_STYLE + " الذكاء الاصطناعي"


def test_known_hallucinations_are_caught():
    assert is_hallucination("ترجمة نانسي قنقر")
    assert is_hallucination("اشتركوا في القناة")
    assert is_hallucination("ماذا ت首��ed")
    assert is_hallucination("Thanks for watching!")
    assert not is_hallucination("إحنا النهارده هنتكلم عن المرتبات")


def test_cleaned_audio_keeps_length_and_timing(tmp_path):
    shutil.copy(MOCK / "audio.wav", tmp_path)
    a, sr = sf.read(tmp_path / "audio.wav")
    b, sr2 = sf.read(asr_audio(tmp_path))
    assert sr2 == 16000 and len(b) == len(a)                                 # same length
    lag = np.argmax(correlate(b, a, mode="full", method="fft")) - (len(a) - 1)
    assert abs(lag) <= 16                                                    # shift <= 1 ms


def test_split_by_speaker():
    w = lambda text, a, b: SimpleNamespace(word=" " + text, start=a, end=b)
    seg = SimpleNamespace(words=[w("أهلا", 1.0, 1.4), w("بيكم", 1.5, 1.9), w("شكرا", 3.0, 3.4), w("ليك", 3.5, 3.8)])
    diar = [{"start": 0.0, "end": 2.5, "speaker": "SPEAKER_00"}, {"start": 2.5, "end": 5.0, "speaker": "SPEAKER_01"}]
    rows = split_by_speaker(seg, diar)
    assert [(r["speaker"], r["text"], r["start"], r["end"]) for r in rows] == [
        ("SPEAKER_00", "أهلا بيكم", 1.0, 1.9), ("SPEAKER_01", "شكرا ليك", 3.0, 3.8)]
