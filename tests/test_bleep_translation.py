# tests/test_bleep_translation.py — a bleeped word is starred in the translation too (a fake model answers)
import ai_director.audio.edit as edit
import ai_director.audio.translate as tr
from ai_director.audio.bleep import load_phrases, mark_source, split_marks
from ai_director.audio.subtitles import caption_items, write_all_captions
from ai_director.common.io import read_json, write_json
from ai_director.common.paths import CONFIGS

PHRASES = load_phrases(CONFIGS / "profanity.txt")


def row(i, text, translation=""):
    return {"id": i, "start": i * 10.0, "end": i * 10.0 + 3, "speaker": "SPEAKER_00", "text": text,
            "translation": translation,
            "words": [{"w": w, "start": i * 10.0 + k * 0.3, "end": i * 10.0 + k * 0.3 + 0.25}
                      for k, w in enumerate(text.split())]}


def session(tmp_path, rows, lang="ar", bleep=True):
    write_json(tmp_path / "session.json", {"id": "t", "language": lang, "duration": 60.0, "bleep_profanity": bleep})
    write_json(tmp_path / "transcript.json", rows)
    return tmp_path


def fake_model(monkeypatch, translate=None, mark=None):
    """translate(prompt) -> the batch's lines; mark(prompt) -> the separate call's lines. Returns the calls made."""
    calls = []

    def chat_json(model, prompt, schema, think=None):
        kind = {tr.Lines: "translate", tr.MarkedLines: "mark", tr.One: "one"}[schema]
        calls.append((kind, prompt))
        if kind == "one":
            raise AssertionError("no row should be translated alone here")
        texts = (translate if kind == "translate" else mark)(prompt)
        return schema(lines=[tr.Line(n=k, text=t) for k, t in enumerate(texts, 1)])
    monkeypatch.setattr(tr, "chat_json", chat_json)
    monkeypatch.setattr(tr, "unload", lambda model: None)
    monkeypatch.setattr(tr, "GEMINI_MODEL", None)
    return calls


def kinds(calls):
    return [k for k, _ in calls]


def english_srt(s):
    write_all_captions(s)
    return (s / "captions_en.srt").read_text(encoding="utf-8")


# --- the marks ---------------------------------------------------------------------------------------------------

def test_split_marks_gives_the_clean_text_and_the_marked_words():
    assert split_marks("You are a [[failure]].") == ("You are a failure.", [3])
    assert split_marks("[[good for nothing]] guy") == ("good for nothing guy", [0, 1, 2])
    assert split_marks("a[[b]]c d") == ("abc d", [0])                     # a mark inside a word hides the word
    assert split_marks("no marks here") == ("no marks here", [])
    assert split_marks("[[oops and]] more]]") == ("oops and more", [0, 1])   # a stray bracket is dropped


def test_mark_source_wraps_each_bleeped_phrase_once():
    assert mark_source(row(0, "انت انسان فاشل.")["words"], PHRASES) == "انت انسان [[فاشل.]]"
    assert mark_source(row(0, "قالي يا ابن اللذينة كده")["words"], PHRASES) == "قالي [[يا ابن اللذينة]] كده"
    assert mark_source(row(0, "صباح الخير")["words"], PHRASES) is None


# --- upload: the marks travel with the translation request ----------------------------------------------------

def test_upload_translation_marks_the_bleeped_word(tmp_path, monkeypatch):
    s = session(tmp_path, [row(0, "انت انسان فاشل."), row(1, "صح")])
    calls = fake_model(monkeypatch, translate=lambda p: ["You are a [[failure]].", "True."])
    tr.run_translate(s)
    prompt = calls[0][1]
    assert "1. انت انسان [[فاشل.]]" in prompt and "2. صح" in prompt and "will be bleeped" in prompt
    rows = read_json(s / "transcript.json")
    assert [r["translation"] for r in rows] == ["You are a failure.", "True."]   # the transcript keeps the word
    assert kinds(calls) == ["translate"]                                          # no second call needed
    srt = english_srt(s)
    assert "failure" not in srt and "You are a ********" in srt and "True." in srt


def test_a_bleeped_row_without_marks_gets_the_separate_call(tmp_path, monkeypatch):
    s = session(tmp_path, [row(0, "انت انسان فاشل."), row(1, "صح")])
    calls = fake_model(monkeypatch, translate=lambda p: ["You are a failure.", "True."],
                       mark=lambda p: ["You are a [[failure]]."])
    tr.run_translate(s)
    assert kinds(calls) == ["translate", "mark"]
    mark_prompt = calls[1][1]
    assert "انت انسان [[فاشل.]]" in mark_prompt and "You are a failure." in mark_prompt and "صح" not in mark_prompt
    assert read_json(s / "transcript.json")[0]["translation"] == "You are a failure."
    assert "failure" not in english_srt(s)


def test_stray_marks_are_removed_from_rows_without_bleeped_words(tmp_path, monkeypatch):
    s = session(tmp_path, [row(0, "صح")])
    fake_model(monkeypatch, translate=lambda p: ["[[True]]."])
    tr.run_translate(s)
    r = read_json(s / "transcript.json")[0]
    assert r["translation"] == "True." and "translation_bleep" not in r


def test_no_marks_in_the_prompt_when_bleeping_is_off(tmp_path, monkeypatch):
    s = session(tmp_path, [row(0, "انت انسان فاشل.")], bleep=False)
    calls = fake_model(monkeypatch, translate=lambda p: ["You are a failure."])
    tr.run_translate(s)
    assert "[[" not in calls[0][1] and "bleeped" not in calls[0][1] and kinds(calls) == ["translate"]
    assert "You are a failure." in english_srt(s)


def test_english_session_stars_the_arabic_translation(tmp_path, monkeypatch):
    s = session(tmp_path, [row(0, "you are an idiot")], lang="en")
    calls = fake_model(monkeypatch, translate=lambda p: ["انت [[أحمق]]"])
    tr.run_translate(s)
    assert "you are an [[idiot]]" in calls[0][1]
    assert read_json(s / "transcript.json")[0]["translation"] == "انت أحمق"
    write_all_captions(s)
    ar = (s / "captions_ar.srt").read_text(encoding="utf-8")
    assert "أحمق" not in ar and "انت ****" in ar
    assert "idiot" not in (s / "captions_en.srt").read_text(encoding="utf-8")


# --- caption edits: the separate call -----------------------------------------------------------------------

def edited_session(tmp_path, monkeypatch):
    monkeypatch.setattr(edit, "write_bleeped_audio", lambda s: None)          # no soundtrack in these tests
    return session(tmp_path, [row(0, "انت انسان كويس.", "You are a failure."), row(1, "صح", "True.")])


def test_an_edit_that_adds_a_bleeped_word_marks_the_translation(tmp_path, monkeypatch):
    s = edited_session(tmp_path, monkeypatch)
    calls = fake_model(monkeypatch, mark=lambda p: ["You are a [[failure]]."])
    assert edit.edit_rows(s, [{"id": 0, "text": "انت انسان فاشل."}]) == 1
    assert kinds(calls) == ["mark"]
    assert "failure" not in (s / "captions_en.srt").read_text(encoding="utf-8")


def test_an_edit_without_bleeped_words_asks_nothing(tmp_path, monkeypatch):
    s = edited_session(tmp_path, monkeypatch)
    calls = fake_model(monkeypatch)
    edit.edit_rows(s, [{"id": 1, "text": "صح كده"}])
    assert calls == []


def test_a_changed_answer_is_asked_again_then_left_as_before(tmp_path, monkeypatch, capsys):
    s = edited_session(tmp_path, monkeypatch)
    calls = fake_model(monkeypatch, mark=lambda p: ["You are a total [[failure]]."])   # the wording changed
    edit.edit_rows(s, [{"id": 0, "text": "انت انسان فاشل."}])
    assert kinds(calls) == ["mark", "mark"]
    assert "translation_bleep" not in read_json(s / "transcript.json")[0]
    assert "You are a failure." in (s / "captions_en.srt").read_text(encoding="utf-8")   # as before this change
    assert "WARNING" in capsys.readouterr().out


def test_a_model_error_does_not_stop_the_edit(tmp_path, monkeypatch, capsys):
    s = edited_session(tmp_path, monkeypatch)
    monkeypatch.setattr(tr, "GEMINI_MODEL", None)
    monkeypatch.setattr(tr, "chat_json", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("offline")))
    assert edit.edit_rows(s, [{"id": 0, "text": "انت انسان فاشل."}]) == 1
    assert read_json(s / "transcript.json")[0]["text"] == "انت انسان فاشل."
    assert "WARNING" in capsys.readouterr().out


# --- captions ------------------------------------------------------------------------------------------------

def test_saved_marks_only_count_for_the_text_they_were_made_for(tmp_path):
    r = row(0, "انت انسان فاشل.", "You are a failure.")
    r["translation_bleep"] = {"text": r["text"], "translation": "You are a loser.", "hide": [3]}   # older translation
    s = session(tmp_path, [r])
    assert "You are a failure." in english_srt(s)


def test_a_long_row_split_into_pieces_stars_the_right_word(tmp_path):
    text = "احنا النهارده هنتكلم عن حاجات كتير جدا وانت انسان فاشل جدا في الكلام"
    trans = "Today we will talk about many things and you are a failure at talking"
    r = row(0, text, trans)
    r["translation_bleep"] = {"text": text, "translation": trans, "hide": [11]}
    s = session(tmp_path, [r])
    items = caption_items(s, "en")
    english = " ".join(x["text"] for x in items)
    assert len(items) == 2 and "failure" not in english and "*******" in english
    assert "talking" in english and "Today" in english
