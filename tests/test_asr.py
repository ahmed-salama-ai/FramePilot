# tests/test_asr.py — Gemini 3.5 Transcribe answers -> transcript.json / diarization.json, WITHOUT calling Google
import os
import shutil

import numpy as np
import soundfile as sf
from pydantic import TypeAdapter

import ai_director.audio.asr as asr
from ai_director.audio.asr import make_diarization, make_rows, piece_times, read_words, seconds
from ai_director.audio.gemini import key_names, with_keys
from ai_director.audio.voices import link_speakers
from ai_director.common import schemas as S
from ai_director.common.env import load_env
from ai_director.common.io import read_json, write_json
from ai_director.common.paths import MOCK


def word(text, a, b, spk):
    return {"type": "word_info", "text": text, "start_offset": f"{a:.3f}s", "end_offset": f"{b:.3f}s", "speaker": spk}


def answer(*words):
    """The shape of a real answer: words are "word_info" annotations deep inside steps -> content -> annotations."""
    return {"id": "x", "steps": [{"content": [{"type": "text", "text": "...", "annotations": list(words)}]}]}


ANSWER = answer(word("أهلا", 1.0, 1.4, "spk_1"), word("بيكم", 1.5, 1.9, "spk_1"),
                {"type": "word_info", "text": "النهارده", "start_offset": "2.0s", "end_offset": "2.4s"},  # no speaker
                word("شكرا", 3.0, 3.4, "spk_0"), word("ليك", 3.5, 3.8, "spk_0"),
                word("يا", 6.0, 6.2, "spk_1"), word("جماعة", 6.3, 6.8, "spk_1"))


def test_seconds():
    assert seconds("12.340s") == 12.34
    assert seconds(12.34) == 12.34
    assert seconds({"seconds": 12, "nanos": 340000000}) == 12.34
    assert seconds("1:02.5") == 62.5
    assert seconds("abc") is None and seconds(None) is None


def test_read_words_keeps_the_pieces_own_labels():
    words = read_words(ANSWER, offset=10.0)
    assert [w["speaker"] for w in words] == ["spk_1"] * 3 + ["spk_0"] * 2 + ["spk_1"] * 2   # no speaker -> previous
    assert words[0] == {"w": "أهلا", "start": 11.0, "end": 11.4, "speaker": "spk_1"}        # piece offset added


def test_rows_and_diarization():
    rows = make_rows([{**w, "speaker": w["speaker"].replace("spk_", "SPEAKER_0")} for w in read_words(ANSWER)])
    assert [(r["speaker"], r["text"], r["start"], r["end"]) for r in rows] == [
        ("SPEAKER_01", "أهلا بيكم النهارده", 1.0, 2.4), ("SPEAKER_00", "شكرا ليك", 3.0, 3.8),
        ("SPEAKER_01", "يا جماعة", 6.0, 6.8)]
    assert make_diarization(rows)[1] == {"start": 3.0, "end": 3.8, "speaker": "SPEAKER_00"}
    long = [{"w": "x", "start": t, "end": t + 0.5, "speaker": "SPEAKER_00"} for t in np.arange(0, 20, 0.6)]
    assert all(r["end"] - r["start"] <= 15 for r in make_rows(long, max_seconds=15))     # max 15 s per row


def test_pieces_are_cut_in_silences():
    sr = 100
    x = np.random.default_rng(0).normal(size=200 * sr).astype("float32")
    speech = [{"start": 0.0, "end": 55.0}, {"start": 56.0, "end": 66.0}, {"start": 67.0, "end": 121.0},
              {"start": 122.0, "end": 200.0}]                 # silences around 55.5, 66.5, 121.5 s
    p = piece_times(200.0, speech, x, sr, chunk=60, search=10)
    assert p[0] == (0.0, 55.5) and p[1] == (55.5, 121.5)    # the silence nearest to each minute mark
    assert p[-1][1] == 200.0 and all(p[i][1] == p[i + 1][0] for i in range(len(p) - 1))
    x[118 * sr:118 * sr + 10] = 0                              # no silence near 115.5 s -> quietest 50 ms instead
    assert 118.0 <= piece_times(200.0, speech[:2], x, sr, chunk=60, search=10)[1][1] <= 118.1
    assert piece_times(60.0, [], x[:60 * sr], sr) == [(0.0, 60.0)]                         # short: one piece
    assert piece_times(200.0, speech, x, sr, chunk=0) == [(0.0, 200.0)]                     # 0 = full session


def test_any_number_of_keys(tmp_path, monkeypatch):
    env = {"GEMINI_API_KEY_10": "k10", "GEMINI_API_KEY": "k1", "GEMINI_API_KEY_2": "k2", "GEMINI_API_KEY_3": "",
           "GEMINI_API_KEY_OLD": "x", "OTHER": "y"}
    assert key_names(env) == ["GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_10"]    # empty / others skipped
    (tmp_path / ".env").write_text("﻿# comment\nHF_TOKEN=hf_abc\nTEST_FP_KEY = \"q\"\nTEST_FP_EMPTY=\n",
                                   encoding="utf-8")
    monkeypatch.delenv("TEST_FP_KEY", raising=False)
    monkeypatch.setenv("HF_TOKEN", "already-set")
    load_env(tmp_path / ".env")
    assert os.environ["TEST_FP_KEY"] == "q" and os.environ["HF_TOKEN"] == "already-set"     # Windows value wins
    assert "TEST_FP_EMPTY" not in os.environ
    monkeypatch.delenv("TEST_FP_KEY")


def test_keys_take_turns():
    seen = []

    def fn(client):
        seen.append(client)
        if client == "a":
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
        return "ok"
    assert with_keys(fn, keyed=[("KEY1", "a"), ("KEY2", "b")], wait=0) == ("ok", "KEY2")   # busy -> next key
    assert seen == ["a", "b"]

    def daily(client):
        raise RuntimeError("429 GenerateRequestsPerDayPerProjectPerModel")
    try:
        with_keys(daily, keyed=[("KEY1", "a")], wait=0)
        assert False, "should have raised"
    except RuntimeError as e:
        assert "no key can be used" in str(e)


def fake_voices(sr):
    """Fake fingerprints: the loudness of the clip says who it is (test audio: 0.1 = A, 0.5 = B, 0.9 = C)."""
    table = {1: np.array([1.0, 0, 0]), 5: np.array([0, 1.0, 0]), 9: np.array([0, 0, 1.0])}

    def embed(clips, _sr):
        return np.stack([table[int(round(float(np.abs(c).mean()) * 10))] for c in clips])
    return embed


def test_link_speakers_same_voice_same_name():
    sr = 100
    audio = np.concatenate([np.full(10 * sr, v, "float32") for v in (0.1, 0.5, 0.5, 0.1, 0.9, 0.1)])  # 10 s each
    pieces = [{"spk_0": [(0, 10)], "spk_1": [(10, 20)]},          # piece 0: A, B
              {"spk_0": [(20, 30)], "spk_1": [(30, 40)]},         # piece 1: Gemini swapped the labels: B, A
              {"spk_0": [(40, 50)], "spk_1": [(50, 60)], "spk_2": [(55, 55.1)]}]   # piece 2: C (new), A, tiny
    link = link_speakers(pieces, audio, sr, n_speakers=3, embed=fake_voices(sr))
    assert link[(0, "spk_0")] == link[(1, "spk_1")] == link[(2, "spk_1")]       # A everywhere
    assert link[(0, "spk_1")] == link[(1, "spk_0")]                              # B
    assert link[(2, "spk_0")] not in (link[(0, "spk_0")], link[(0, "spk_1")])    # C is a new person
    assert link[(2, "spk_2")] is None                                            # 0.1 s: too short to recognise


def test_run_asr_shares_pieces_between_keys(tmp_path, monkeypatch):
    sr = 16000
    audio = np.concatenate([np.full(65 * sr, 0.1, "float32"), np.full(65 * sr, 0.5, "float32")])
    sf.write(tmp_path / "audio.wav", audio, sr)
    shutil.copy(MOCK / "upload.json", tmp_path)
    write_json(tmp_path / "session.json", {**read_json(MOCK / "session.json"), "num_speakers": 2})
    write_json(tmp_path / "speech.json", [{"start": 0.0, "end": 59.0}, {"start": 61.0, "end": 130.0}])
    calls = []

    def fake_gemini(path, lang, start=0, keyed=None):
        calls.append((start, path.name))
        if start == 0:      # piece 0 (0-60 s): voice A is "spk_0"
            return answer(word("أهلا", 1.0, 1.4, "spk_0"), word("بيكم", 1.5, 50.0, "spk_0")), keyed[0][0]
        return answer(word("شكرا", 6.0, 6.4, "spk_0"), word("ليك", 6.5, 69.0, "spk_0")), keyed[1][0]  # voice B
    monkeypatch.setattr(asr, "ask_gemini", fake_gemini)
    monkeypatch.setattr(asr, "clients", lambda: [("GEMINI_API_KEY", "a"), ("GEMINI_API_KEY_2", "b")])
    monkeypatch.setitem(asr.CFG, "chunk_seconds", 60)                         # pieces mode
    asr.run_asr(tmp_path, embed=fake_voices(sr))
    assert sorted(calls) == [(0, "asr_piece_000.wav"), (1, "asr_piece_001.wav")]   # piece k starts at key k
    rows = read_json(tmp_path / "transcript.json")
    TypeAdapter(list[S.TranscriptSegment]).validate_python(rows)
    TypeAdapter(list[S.DiarSegment]).validate_python(read_json(tmp_path / "diarization.json"))
    assert [(r["speaker"], r["text"]) for r in rows] == [                   # both "spk_0", different voices
        ("SPEAKER_00", "أهلا"), ("SPEAKER_00", "بيكم"), ("SPEAKER_01", "شكرا"), ("SPEAKER_01", "ليك")]
    assert rows[2]["start"] == 66.0                                           # piece 2 starts at 60 s
    (tmp_path / "transcript.json").unlink()
    asr.run_asr(tmp_path, embed=fake_voices(sr))                                # saved answers are reused
    assert len(calls) == 2


def test_run_asr_full_session(tmp_path, monkeypatch):
    for f in ("session.json", "upload.json", "audio.wav", "speech.json"):
        shutil.copy(MOCK / f, tmp_path)
    calls = []

    def fake_gemini(path, lang, start=0, keyed=None):
        calls.append(path.name)
        return ANSWER, keyed[start % len(keyed)][0]
    monkeypatch.setattr(asr, "ask_gemini", fake_gemini)
    monkeypatch.setattr(asr, "clients", lambda: [("GEMINI_API_KEY", "a"), ("GEMINI_API_KEY_2", "b")])
    monkeypatch.setitem(asr.CFG, "chunk_seconds", 0)                          # full session
    asr.run_asr(tmp_path)                                                     # one piece: no voice model needed
    assert calls == ["asr_piece_000.wav"]
    rows = read_json(tmp_path / "transcript.json")
    assert [r["speaker"] for r in rows] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"]   # by first appearance


def test_extra_voices_join_only_the_same_person():
    """One request: Gemini sometimes makes one person two labels. The smallest label joins a voice only if it is
    nearly the same (measured: same person 0.98, two different men 0.89-0.93)."""
    from ai_director.audio.voices import merge_extra_voices
    vec = {"A": [1.0, 0.0, 0.0], "B": [0.99, 0.141, 0.0], "C": [0.0, 1.0, 0.0], "D": [0.93, 0.0, 0.368]}
    fake = lambda clips, sr: np.array([vec[c] for c in clips])                 # the "audio" is the label's name
    audio = None
    spans = {"A": [(0, 100)], "B": [(100, 110)], "C": [(110, 160)]}
    say = lambda a, sr, s: {(0, 100): "A", (100, 110): "B", (110, 160): "C", (160, 170): "D"}[s[0]]
    import ai_director.audio.voices as V
    old = V.speaker_audio
    V.speaker_audio = say
    try:
        assert merge_extra_voices(spans, audio, 16000, 2, embed=fake) == {"B": "A"}                # 0.99: joins
        assert merge_extra_voices(spans, audio, 16000, 3, embed=fake) == {}                        # count is right
        assert merge_extra_voices({**spans, "D": [(160, 170)]}, audio, 16000, 3, embed=fake) == {"B": "A"}
        assert merge_extra_voices({"A": [(0, 100)], "D": [(160, 170)]}, audio, 16000, 1, embed=fake) == {}   # 0.93: two men
    finally:
        V.speaker_audio = old
