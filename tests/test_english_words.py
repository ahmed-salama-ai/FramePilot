# tests/test_english_words.py — the English words step on a tiny made-up Arabic session (a fake Gemini, no internet)
import numpy as np
import pytest

from ai_director.audio import english_words as ew
from ai_director.common.io import read_json, write_json

sf = pytest.importorskip("soundfile")


def session(tmp_path, language="ar"):
    write_json(tmp_path / "session.json", {"language": language})
    sf.write(tmp_path / "audio.wav", np.zeros(16000 * 90, "float32"), 16000)
    rows = [{"id": 0, "start": 1.0, "end": 3.0, "speaker": "SPEAKER_00", "text": "شركه عامله موديل اسمه",
             "translation": "A company made a model named", "words": []},
            {"id": 1, "start": 3.5, "end": 5.5, "speaker": "SPEAKER_00", "text": "طلع معانا ايكورسي حلوه",
             "translation": "It gave us nice ايكورسي", "words": []},
            {"id": 2, "start": 70.0, "end": 72.0, "speaker": "SPEAKER_01", "text": "تمام كده",
             "translation": "OK then", "words": []}]
    write_json(tmp_path / "transcript.json", rows)
    return tmp_path


class FakeGemini:
    """Answers like gemini-3.5-flash; remembers every prompt and model it was asked. no_quota = models that fail."""
    def __init__(self, answers, no_quota=()):
        self.answers, self.prompts, self.models, self.no_quota = answers, [], [], no_quota

    def __call__(self, path, prompt, model, start=0, keyed=None):
        assert path.exists()
        self.models.append(model)
        if model in self.no_quota:
            raise RuntimeError("Gemini: no key can be used right now (rate or daily limits).")
        self.prompts.append(prompt)
        return self.answers[len(self.prompts) - 1], "FAKE_KEY"


def test_no_quota_left_uses_the_fallback_model(tmp_path):
    """gemini-3.5-flash has only 20 requests a day: without quota the fallback model answers, and the next windows
    don't try the main model again; its saved answers count on the next run."""
    s = session(tmp_path)
    main, fallback = ew.CFG["english_words_model"], ew.CFG["english_words_fallback"]
    fake = FakeGemini([{1: "شركة عاملة موديل اسمه Qwen"}, {}], no_quota=(main,))
    assert ew.fix_english_words(s, ask=fake) == 1
    assert fake.models == [main, fallback, fallback]                 # window 1: main fails -> fallback; window 2: fallback
    assert read_json(s / "tmp" / "gemini_words_000.json")["model"] == fallback

    def no_internet(*a, **k):
        raise AssertionError("asked Gemini again")
    assert ew.fix_english_words(s, ask=no_internet) == 0             # the fallback's saved answers are used


def test_windows_never_cut_a_row():
    rows = [{"start": s, "end": s + 4} for s in (0, 10, 50, 58, 130)]
    assert [[r["start"] for r in g] for g in ew.windows(rows, 60)] == [[0, 10, 50], [58], [130]]


def test_plausible_ignores_spelling_but_catches_a_slid_line():
    assert ew.plausible("فيهم شركه عامله موديل جامد جدا حاليا", "فيهم شركة عاملة موديل جامد جداً حالياً اسمه")
    assert not ew.plausible("فيهم شركه عامله موديل", "ما طلعش معانا accuracy حلوة")     # another line's words
    assert ew.plausible("ايه بقى؟", "ليه بقى؟")                                            # short draft: always OK


def test_english_words_put_back(tmp_path):
    s = session(tmp_path)
    fake = FakeGemini([{1: "شركة عاملة موديل اسمه Qwen", 2: "طلع معانا accuracy حلوة"}, {1: "تمام كده"}])
    assert ew.fix_english_words(s, ask=fake) == 2
    rows = read_json(s / "transcript.json")
    assert [r["text"] for r in rows] == ["شركة عاملة موديل اسمه Qwen", "طلع معانا accuracy حلوة", "تمام كده"]
    assert [w["w"] for w in rows[0]["words"]] == rows[0]["text"].split()
    assert rows[0]["words"][0]["start"] == 1.0 and rows[0]["words"][-1]["end"] == 3.0     # the row's own time
    assert rows[0]["translation"] == "" and rows[2]["translation"] == "OK then"          # only changed rows
    assert [(r["id"], r["start"], r["end"], r["speaker"]) for r in rows] == [
        (0, 1.0, 3.0, "SPEAKER_00"), (1, 3.5, 5.5, "SPEAKER_00"), (2, 70.0, 72.0, "SPEAKER_01")]
    assert "0.5-2.5 s, SPEAKER_00 | draft: شركه عامله موديل اسمه" in fake.prompts[0]      # times inside its window
    assert len(fake.prompts) == 2                                                          # 0-6 s and 70-72 s


def test_a_window_hears_the_lines_around_it(tmp_path):
    """A word right after a window edge needs what was said before it: the 2 nearby lines before / after are sent as
    context (in the audio and the prompt, not to be returned); far-away lines are not."""
    s = session(tmp_path)
    rows = [{"id": i, "start": a, "end": b, "speaker": "SPEAKER_00", "text": t, "translation": "", "words": []}
            for i, (a, b, t) in enumerate([(1, 3, "اهلا بيكم"), (50, 55, "شركه عامله موديل اسمه"),
                                           (58, 62, "اسمه هنستخدمه"), (63, 65, "تمام كده")])]
    write_json(s / "transcript.json", rows)
    fake = FakeGemini([{}, {}])
    ew.fix_english_words(s, ask=fake)
    first, second = fake.prompts
    assert "Context only" in first and "- 57.5-61.5 s, SPEAKER_00 | draft: اسمه هنستخدمه" in first  # the next lines
    assert "- 0.5-5.5 s, SPEAKER_00 | draft: شركه عامله موديل اسمه" in second                        # audio from 49.5 s
    assert "اهلا بيكم" not in second                                                                  # 55 s too far
    assert "1. 8.5-12.5 s, SPEAKER_00 | draft: اسمه هنستخدمه" in second


def test_second_run_is_free_and_changes_nothing(tmp_path):
    s = session(tmp_path)
    ew.fix_english_words(s, ask=FakeGemini([{1: "شركة عاملة موديل اسمه Qwen"}, {}]))
    rows = read_json(s / "transcript.json")
    rows[0]["translation"] = "A company made a model named Qwen"                           # translated meanwhile
    write_json(s / "transcript.json", rows)

    def no_internet(*a, **k):
        raise AssertionError("asked Gemini again")
    assert ew.fix_english_words(s, ask=no_internet) == 0                                  # the saved answers
    assert read_json(s / "transcript.json") == rows                                       # translation kept


def test_slid_or_empty_answers_keep_the_draft(tmp_path):
    s = session(tmp_path)
    fake = FakeGemini([{1: "ما طلعش معانا accuracy حلوة خالص", 2: ""}, {}])                # line 1 got line 2's text
    assert ew.fix_english_words(s, ask=fake) == 0
    assert [r["text"] for r in read_json(s / "transcript.json")] == ["شركه عامله موديل اسمه", "طلع معانا ايكورسي حلوه",
                                                                      "تمام كده"]


def test_english_sessions_are_left_alone(tmp_path):
    s = session(tmp_path, language="en")

    def no_call(*a, **k):
        raise AssertionError("an English session was sent")
    assert ew.fix_english_words(s, ask=no_call) == 0
