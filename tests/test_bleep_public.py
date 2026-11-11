# tests/test_bleep_public.py — bleeped words stay out of what people read: titles, posts, the article, ... (fake model)
import json

import pandas as pd

import ai_director.highlights.run as highlights_run
import ai_director.highlights.trailer as trailer
from ai_director.audio.bleep import Bleeped, save_marks
from ai_director.common.io import read_json, write_json
from ai_director.highlights import article, publish
from ai_director.highlights.select import Pick, Picks, pick

BAD = ("فاشل", "الخاصة", "الخاصه", "failure", "private")      # said (or its translation) and bleeped in session()


def row(i, text, translation, hide=None):
    r = {"id": i, "start": i * 10.0, "end": i * 10.0 + 3, "speaker": "SPEAKER_00", "text": text,
         "translation": translation,
         "words": [{"w": w, "start": i * 10.0 + k * 0.3, "end": i * 10.0 + k * 0.3 + 0.25}
                   for k, w in enumerate(text.split())]}
    if hide is not None:
        save_marks(r, hide)
    return r


def session(tmp_path, bleep=True):
    """Arabic; فاشل is on the standard list, الخاصه was typed at upload. Their translations were marked."""
    write_json(tmp_path / "session.json", {"id": "t", "language": "ar", "duration": 60.0, "bleep_profanity": bleep})
    write_json(tmp_path / "upload.json", {"name": "Episode 1", "language": "ar", "bleep_profanity": bleep,
                                          "bleep_words": ["الخاصه"]})
    write_json(tmp_path / "transcript.json", [
        row(0, "انت انسان فاشل.", "You are a failure.", [3]),
        row(1, "الجامعات الخاصه مشكله كبيره", "Private universities are a big problem", [0]),
        row(2, "صح كده", "That's right")])
    return tmp_path


def clean_of_bleeped(text):
    low = text.lower()
    return not [w for w in BAD if w in low]


# --- the helper ----------------------------------------------------------------------------------------------

def test_star_keeps_lines_markdown_and_hashtags(tmp_path):
    b = Bleeped(session(tmp_path))
    text = "# عنوان\n\n## الجامعات الخاصة\n> انت فاشل!\n#الجامعات_الخاصة #تعليم\nPrivate schools and a failure."
    assert b.star(text) == ("# عنوان\n\n## الجامعات ******\n> انت *****\n#الجامعات_****** #تعليم\n"
                            "******* schools and a ********")
    assert b.found("He is a failure") and not b.found("He is fine")


def test_the_note_names_what_was_said_and_its_translation(tmp_path):
    note = Bleeped(session(tmp_path)).note()
    assert all(w in note for w in ("فاشل", "الخاصه", "failure", "Private")) and "never write" in note
    assert "غبي" not in note                                          # listed but never said here: not named


def test_nothing_changes_when_bleeping_is_off(tmp_path):
    b = Bleeped(session(tmp_path, bleep=False))
    assert b.note() == "" and b.star("You are a failure.") == "You are a failure." and not b.found("failure")


# --- highlight titles ----------------------------------------------------------------------------------------

def cands():
    return [{"id": k, "start": k * 10.0, "end": k * 10.0 + 30, "text": "انت انسان فاشل. الجامعات الخاصه",
             "translation": "You are a failure. Private universities"} for k in range(4)]


def test_highlight_titles_are_starred_and_the_model_is_told(tmp_path):
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return Picks(picks=[Pick(id=0, title_ar="انسان فاشل", title_en="A failure", hook="Why a failure?")])
    chosen = pick(cands(), "ar", ask, bleeped=Bleeped(session(tmp_path)))
    assert "never write" in prompts[0] and "failure" in prompts[0]
    assert chosen[0][1] == {"title_ar": "انسان ****", "title_en": "A *******", "hook": "Why a ********"}
    assert len(chosen) == 3 and all(clean_of_bleeped(json.dumps(t, ensure_ascii=False)) for _, t in chosen)


def test_titles_without_a_model_are_starred_too(tmp_path):
    def ask(prompt):
        raise ConnectionError("offline")
    chosen = pick(cands(), "ar", ask, bleeped=Bleeped(session(tmp_path)))
    assert chosen and all(clean_of_bleeped(json.dumps(t, ensure_ascii=False)) for _, t in chosen)


def test_the_highlights_stage_uses_the_session_words(tmp_path, monkeypatch):
    s = session(tmp_path)
    made = []
    monkeypatch.setattr(highlights_run, "interest_curve", lambda s: pd.DataFrame({"t": [0.0], "interest": [1.0]}))
    monkeypatch.setattr(highlights_run, "candidates", lambda ev, segs, duration: cands())
    monkeypatch.setattr(highlights_run, "make_clips", lambda s, chosen: made.extend(chosen) or [])
    highlights_run.main(s, ask=lambda p: Picks(picks=[Pick(id=0, title_ar="فاشل", title_en="Failure", hook="")]),
                        extras=False)
    assert made and all(clean_of_bleeped(json.dumps(t, ensure_ascii=False)) for _, t in made)


# --- trailer name ---------------------------------------------------------------------------------------------

def test_the_trailer_name_is_starred(tmp_path, monkeypatch):
    s = session(tmp_path)
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return trailer.Answer(moments=[trailer._Moment(first=0, last=1)], title_ar="الفاشل", title_en="The failure")
    monkeypatch.setattr(trailer, "strongest", lambda s, rows, taken=(): list(taken) or [(0.0, 13.0)])
    _, ta, te = trailer.choose(s, ask)
    assert (ta, te) == ("******", "The *******") and "never write" in prompts[0]


# --- the publish kit and the article ---------------------------------------------------------------------------

def test_the_publish_kit_is_starred_description_included(tmp_path):
    s = session(tmp_path)
    write_json(s / "session.json", {**read_json(s / "session.json"), "duration": 200.0})    # room for 3 chapters
    write_json(s / "transcript.json", [row(0, "انت انسان فاشل.", "You are a failure.", [3]),
                                       row(4, "الجامعات الخاصه مشكله كبيره", "Private universities are a big problem",
                                           [0]),
                                       row(8, "صح كده", "That's right")])
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return publish.Answer(
            chapters=[publish._Chapter(start=0, title_ar="مقدمة", title_en="Intro"),
                      publish._Chapter(start=40, title_ar="الجامعات الخاصة", title_en="Private universities"),
                      publish._Chapter(start=80, title_ar="انت فاشل", title_en="You are a failure")],
            summary_ar="ضيف بيقول انت فاشل", summary_en="A guest calls him a failure.",
            key_points_ar=["الجامعات الخاصة مشكلة"], key_points_en=["Private universities are a problem"],
            posts=[publish._Post(highlight="h1", text_ar="شوف الفاشل", text_en="Watch the failure",
                                 hashtags=["الجامعات_الخاصة", "failure"])])
    publish.make_publish(s, highlights=[{"id": "h1", "start": 0.0, "end": 30.0, "title_ar": "x", "title_en": "y"}],
                         ask=ask)
    p = read_json(s / "publish.json")
    saved = json.dumps(p, ensure_ascii=False)
    assert clean_of_bleeped(saved) and "never write" in prompts[0]
    assert len(p["chapters"]) == 3 and "universities" in saved                    # only the bleeped word starred
    assert p["posts"][0]["hashtags"] == ["#الجامعات_******"]                      # a hashtag of stars only: dropped


def test_the_article_is_starred(tmp_path):
    s = session(tmp_path)
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return article.Answer(article_ar="# الجامعات الخاصة\n\n> انت فاشل", article_en="# Private universities\n\n"
                                                                                  "> You are a failure.")
    out = article.make_article(s, ask=ask)
    assert out["article_ar"] == "# الجامعات ******\n\n> انت ****"
    assert out["article_en"] == "# ******* universities\n\n> You are a ********"
    assert clean_of_bleeped(json.dumps(read_json(s / "publish.json"), ensure_ascii=False))
    assert "never write" in prompts[0]


def test_bleeping_off_leaves_the_article_and_prompt_alone(tmp_path):
    s = session(tmp_path, bleep=False)
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return article.Answer(article_ar="انت فاشل", article_en="You are a failure.")
    assert article.make_article(s, ask=ask)["article_en"] == "You are a failure."
    assert "never write" not in prompts[0]
