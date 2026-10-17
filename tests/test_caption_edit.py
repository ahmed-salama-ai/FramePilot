import shutil

import pytest

from ai_director.audio.edit import edit_rows, history, restore_original, undo
from ai_director.common.io import read_json
from ai_director.common.paths import MOCK


@pytest.fixture
def s(tmp_path):
    shutil.copytree(MOCK, tmp_path / "s00")
    return tmp_path / "s00"


def test_edit_a_row(s):
    rows = read_json(s / "transcript.json")
    r = rows[1]
    (s / "search_index.npy").write_bytes(b"x")
    n = edit_rows(s, [{"id": r["id"], "text": "  نص   جديد خالص "}, {"id": 9999, "text": "no such row"}])
    assert n == 1
    new = next(x for x in read_json(s / "transcript.json") if x["id"] == r["id"])
    assert new["text"] == "نص جديد خالص" and new["translation"] == r["translation"]     # translation kept
    assert [w["w"] for w in new["words"]] == ["نص", "جديد", "خالص"]
    # fewer words: they share the time the old words were spoken
    assert new["words"][0]["start"] == r["words"][0]["start"] and new["words"][-1]["end"] == r["words"][-1]["end"]
    srt = (s / "captions_ar.srt").read_text(encoding="utf-8")                           # caption files made again
    assert all(w in srt for w in ("نص", "جديد", "خالص")) and r["text"] not in srt
    assert not (s / "search_index.npy").exists()                                       # the agent's search: rebuilt
    assert (s / "history/transcript_original.json").exists() and len(history(s)) == 1


def test_a_typo_keeps_every_word_time(s):
    r = read_json(s / "transcript.json")[1]
    words = r["text"].split()
    fixed = " ".join(words[:-1] + ["والمرتّبات"])                                          # same number of words
    edit_rows(s, [{"id": r["id"], "text": fixed}])
    new = next(x for x in read_json(s / "transcript.json") if x["id"] == r["id"])
    assert [(w["start"], w["end"]) for w in new["words"]] == [(w["start"], w["end"]) for w in r["words"]]
    assert "والمرتّبات" in (s / "captions.vtt").read_text(encoding="utf-8")


def test_edit_translation_only(s):
    r = read_json(s / "transcript.json")[0]
    assert edit_rows(s, [{"id": r["id"], "translation": "Hello and welcome"}]) == 1
    new = read_json(s / "transcript.json")[0]
    assert new["translation"] == "Hello and welcome" and new["words"] == r["words"]       # the words stay
    assert edit_rows(s, [{"id": r["id"], "translation": "Hello and welcome"}]) == 0       # no change: no new save
    assert len(history(s)) == 1


def test_undo_and_restore(s):
    original = read_json(s / "transcript.json")
    rid = original[2]["id"]
    edit_rows(s, [{"id": rid, "text": "أول تعديل"}])
    edit_rows(s, [{"id": rid, "text": "تاني تعديل"}])
    assert undo(s)                                                                      # back to the first edit
    assert next(x for x in read_json(s / "transcript.json") if x["id"] == rid)["text"] == "أول تعديل"
    assert restore_original(s)
    assert read_json(s / "transcript.json") == original
    assert undo(s)                                                                      # undo the restore
    assert next(x for x in read_json(s / "transcript.json") if x["id"] == rid)["text"] == "أول تعديل"
    assert undo(s)
    assert read_json(s / "transcript.json") == original
    assert not undo(s)
