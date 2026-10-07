# tests/test_translate.py — translation + captions without a model (a fake model answers)
import ai_director.audio.translate as tr
from ai_director.audio.asr import make_rows
from ai_director.audio.subtitles import RLM, caption_items
from ai_director.common.io import read_json, write_json


def session(tmp_path, texts, lang="ar", names=None):
    write_json(tmp_path / "session.json", {"language": lang, "speaker_names": names or {}})
    write_json(tmp_path / "transcript.json", [
        {"id": i, "start": float(i), "end": i + 0.9, "speaker": "SPEAKER_00", "text": t, "translation": "",
         "words": [{"w": w, "start": i + k * 0.2, "end": i + k * 0.2 + 0.15} for k, w in enumerate(t.split())]}
        for i, t in enumerate(texts)])
    return tmp_path


def fake_model(monkeypatch, batch, one):
    asked = []

    def chat_json(model, prompt, schema, think=None):
        asked.append(schema.__name__)
        assert think is False                                         # qwen3 must not "think"
        return batch(prompt) if schema is tr.Lines else tr.One(text=one(prompt))
    monkeypatch.setattr(tr, "chat_json", chat_json)
    monkeypatch.setattr(tr, "unload", lambda model: None)
    return asked


def test_numbers_are_removed_and_wrong_answers_asked_again(tmp_path, monkeypatch):
    s = session(tmp_path, ["أهلا بيكم", "النهارده", "شكرا ليك"])
    asked = fake_model(monkeypatch,
                       lambda p: tr.Lines(lines=[tr.Line(n=1, text="1. Welcome"),       # number copied into the text
                                                 tr.Line(n=2, text="النهارده")]),       # not translated; no row 3
                       lambda p: "2) Today" if "النهارده" in p else "Thanks")
    tr.run_translate(s)
    assert [x["translation"] for x in read_json(s / "transcript.json")] == ["Welcome", "Today", "Thanks"]
    assert asked == ["Lines", "One", "One"]                           # rows 2 and 3 asked again, alone


def test_a_row_that_fails_twice_stays_empty(tmp_path, monkeypatch):
    s = session(tmp_path, ["أهلا بيكم", "شكرا"])
    fake_model(monkeypatch, lambda p: tr.Lines.model_validate({}),     # the batch answer is unusable
               lambda p: "شكرا")                                      # and alone it is still Arabic
    tr.run_translate(s)
    assert [x["translation"] for x in read_json(s / "transcript.json")] == ["", ""]


def test_english_session_needs_arabic(tmp_path, monkeypatch):
    s = session(tmp_path, ["Welcome everyone"], lang="en")
    fake_model(monkeypatch, lambda p: tr.Lines(lines=[tr.Line(n=1, text="Welcome everyone")]),   # not translated
               lambda p: "أهلا بيكم كلكم")
    tr.run_translate(s)
    assert read_json(s / "transcript.json")[0]["translation"] == "أهلا بيكم كلكم"


def test_one_row_is_one_caption_with_its_whole_translation(tmp_path):
    s = session(tmp_path, ["أول حاجة السي في لازم يبقى صفحة"], names={"SPEAKER_00": "Guest"})
    rows = read_json(s / "transcript.json")
    rows[0]["translation"] = "First, your CV must be one page"
    write_json(s / "transcript.json", rows)
    items = caption_items(s)
    assert len(items) == 1
    assert items[0]["text"] == RLM + "Guest: أول حاجة السي في لازم يبقى صفحة\nFirst, your CV must be one page"
    assert caption_items(s, "en")[0]["text"] == "Guest: First, your CV must be one page"     # no RLM on English


def test_rows_end_at_caption_length_and_sentence_end():
    words, t = [], 0.0
    for w in "إحنا النهارده هنتكلم عن الجامعات الخاصه. وتأثيرها على سوق العمل في مصر والمرتبات كمان".split():
        words.append({"w": w, "start": t, "end": t + 0.3, "speaker": "SPEAKER_00"})
        t += 0.35
    rows = make_rows(words, max_seconds=5, max_chars=42)
    assert rows[0]["text"].endswith("الخاصه.")                        # a sentence end closes the row
    assert all(len(r["text"]) <= 42 and r["end"] - r["start"] <= 5 for r in rows)
    assert " ".join(r["text"] for r in rows) == " ".join(w["w"] for w in words)   # no word lost
