import json
import shutil
import subprocess

import pytest

from ai_director.common.io import read_json
from ai_director.common.paths import MOCK
from ai_director.director import thumbnail
from ai_director.highlights import article, trailer
from ai_director.ingest.probe import probe


@pytest.fixture
def s(tmp_path):
    shutil.copytree(MOCK, tmp_path / "s00")
    return tmp_path / "s00"


def fake_trailer(pairs, title_ar="عنوان الحلقة", title_en="Episode name"):
    def ask(prompt):
        assert "[0]" in prompt and "TRAILER" in prompt                     # the numbered transcript lines
        return trailer.Answer(moments=[trailer._Moment(first=a, last=b) for a, b in pairs], title_ar=title_ar,
                              title_en=title_en)
    return ask


def test_trailer_moments_are_checked(s):
    rows = read_json(s / "transcript.json")
    moments, ta, te = trailer.choose(s, fake_trailer([(1, 1), (1, 2), (99, 100), (5, 4), (6, 6)]))
    assert ta == "عنوان الحلقة" and te == "Episode name"
    assert all(3 - 0.5 <= b - a <= 12 + 0.5 for a, b in moments)              # trailer.piece
    assert all(not (a < d and c < b) for i, (a, b) in enumerate(moments) for c, d in moments[i + 1:])   # no overlap
    assert any(abs(a - rows[1]["start"]) < 0.01 for a, _ in moments)
    fallback, _, te2 = trailer.choose(s, lambda p: (_ for _ in ()).throw(RuntimeError("no model")))
    assert fallback and te2 == read_json(s / "upload.json")["name"]          # no model: the interest curve


def test_trailer_files(s):
    out = trailer.make_trailer(s, ask=fake_trailer([(1, 1), (6, 6), (9, 9)]))
    secs = sum(m["end"] - m["start"] for m in out["moments"])
    for fmt, size in (("16:9", (1280, 720)), ("9:16", (720, 1280))):
        info = probe(s / out["files"][fmt])
        assert (info["width"], info["height"]) == size
        assert abs(info["duration"] - (secs + trailer.CFG["end_card"])) < 0.4
    assert read_json(s / "trailer.json")["title_en"] == "Episode name"
    again = trailer.make_trailer(s, again=False)                              # the same moments, no model asked
    assert again["moments"] == out["moments"]


def test_trailer_with_brand_music(s):
    (s / "brand").mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=5", s / "brand/music.mp3"],
                   check=True)
    (s / "brand.json").write_text(json.dumps({"music": "brand/music.mp3"}), encoding="utf-8")
    out = trailer.make_trailer(s, ask=fake_trailer([(1, 1), (6, 6)]))
    secs = sum(m["end"] - m["start"] for m in out["moments"]) + trailer.CFG["end_card"]
    assert abs(probe(s / out["files"]["16:9"])["duration"] - secs) < 0.4    # the music loops, then stops with it


def test_article_goes_into_the_publish_kit(s):
    (s / "publish.json").write_text(json.dumps({"summary_en": "kept"}), encoding="utf-8")
    seen = {}

    def ask(prompt):
        seen["prompt"] = prompt
        return article.Answer(article_ar="```markdown\n# عنوان\nنص\n```", article_en="# Title\n\nText\n")
    a = article.make_article(s, ask=ask)
    assert a == {"article_ar": "# عنوان\nنص", "article_en": "# Title\n\nText"}
    p = read_json(s / "publish.json")
    assert p["summary_en"] == "kept" and p["article_en"].startswith("# Title")
    assert "SPEAKER_00 = Host (host)" in seen["prompt"]
    with pytest.raises(ValueError):
        article.make_article(s, ask=lambda p: article.Answer(article_ar=" ", article_en=""))


def test_thumbnails_without_face_models(s, monkeypatch):
    monkeypatch.setattr(thumbnail.Faces, "__init__", lambda self: setattr(self, "ok", False))
    hl = [{"id": "h1", "start": 12.0, "end": 27.0, "title_ar": "أول وظيفة", "title_en": "The first job"}]
    items = thumbnail.make_thumbnails(s, highlights=hl)
    assert len(items) == 1 and items[0]["cam"] in (2, 3) and 13 <= items[0]["t"] <= 26
    for lang in ("ar", "en"):
        info = probe(s / items[0]["files"][lang])
        assert (info["width"], info["height"]) == (1280, 720)
    assert read_json(s / "thumbnails.json") == items
    with pytest.raises(ValueError, match="highlights"):
        thumbnail.make_thumbnails(s, highlights=[])


def test_crop_box_leaves_room_for_the_title():
    box, place = thumbnail.crop_box(500, 400, 300, 1920, 1080)               # a face on the left
    assert place[0] == "right" and place[1] >= 380
    x, y, w, h = box
    assert w / h == pytest.approx(16 / 9, abs=0.01) and 0 <= x <= 1920 - w and 0 <= y <= 1080 - h
    _, place = thumbnail.crop_box(960, 400, 1000, 1920, 1080)                # a huge face in the middle
    assert place[0] == "bottom"


def test_a_moment_ends_at_a_sentence_end():
    rows = [{"start": 0.0, "end": 4.0, "text": "first part and"}, {"start": 4.0, "end": 7.0, "text": "the end."},
            {"start": 7.0, "end": 9.0, "text": "more"}, {"start": 9.0, "end": 23.0, "text": "a long line."}]
    assert trailer.fit(rows, 0, 0, 3, 12) == (0.0, 7.0)                       # "and" -> on to "the end."
    assert trailer.fit(rows, 0, 2, 3, 12) == (0.0, 7.0)                       # "more" -> back to "the end."
    assert trailer.fit(rows, 3, 3, 3, 12) is None                             # one 14 s line: too long

