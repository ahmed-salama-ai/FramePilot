import json
import shutil
import subprocess

import pytest

from ai_director.audio.subtitles import FORCE_STYLE
from ai_director.common.io import read_json
from ai_director.common.paths import MOCK
from ai_director.director import render
from ai_director.director.brand import ass_colour, force_style, load_brand
from ai_director.director.cards import name_cards
from ai_director.ingest.probe import probe


@pytest.fixture
def s(tmp_path):
    shutil.copytree(MOCK, tmp_path / "s00")
    return tmp_path / "s00"


def name_people(s, names):
    """speakers.json names typed by the user -> name cards."""
    sp = read_json(s / "speakers.json")
    for x in sp:
        x["name"], x["name_source"] = names.get(x["speaker"], x["name"]), "user" if x["speaker"] in names else ""
    (s / "speakers.json").write_text(json.dumps(sp, ensure_ascii=False), encoding="utf-8")


def test_no_brand_gives_the_old_caption_style(s):
    assert force_style(s) == FORCE_STYLE
    assert "FontSize=9" in force_style(s, vertical=True)
    assert ass_colour("#EF8A2C") == "&H002C8AEF" and ass_colour("#000000", 0x80) == "&H80000000"
    with pytest.raises(ValueError):
        ass_colour("orange")


def test_brand_file_missing_is_ignored(s):
    (s / "brand.json").write_text(json.dumps({"logo": "brand/logo.png", "captions": {"text_color": "#FFE066"}}),
                                  encoding="utf-8")
    b = load_brand(s)
    assert b["logo"] is None and b["logo_corner"] == "top-right"           # the logo file does not exist
    assert "PrimaryColour=&H0066E0FF" in force_style(s)
    (s / "brand.json").write_text(json.dumps({"captions": {"text_color": "orange"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="RRGGBB"):
        load_brand(s)


def test_name_cards_only_for_names_the_user_typed(s):
    cuts = read_json(s / "cuts.json")
    assert name_cards(s, cuts) == []                           # the mock's names have no name_source "user"
    name_people(s, {"SPEAKER_00": "Dr. Mona Adel"})
    cards = name_cards(s, cuts)
    assert [(c["name"], c["role"]) for c in cards] == [("Dr. Mona Adel", "مقدم البرنامج")]
    c = cards[0]
    shot = next(x for x in cuts if x["start"] <= c["start"] < x["end"])
    assert shot["cam"] == read_json(s / "speaker_map.json")["SPEAKER_00"]   # her camera is on air during the card
    assert 2.0 <= c["end"] - c["start"] <= 4.0 and c["end"] <= shot["end"]


def test_cards_never_overlap(s):
    name_people(s, {"SPEAKER_00": "Mona", "SPEAKER_01": "Islam"})
    cards = name_cards(s, read_json(s / "cuts.json"))
    assert len(cards) == 2
    assert cards[0]["end"] + 0.5 <= cards[1]["start"]


def test_program_with_brand_cards_intro_and_outro(s):
    """The whole program.mp4: intro (with sound) + the video with captions, cards, logo + outro (no sound)."""
    (s / "brand").mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:d=1.5:r=25",
                    "-f", "lavfi", "-i", "sine=f=440:d=1.5", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", s / "brand/intro.mp4"], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=1920x1080:d=1:r=30",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", s / "brand/outro.mp4"], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=white:s=64x64:d=0.1",
                    "-frames:v", "1", s / "brand/logo.png"], check=True)
    (s / "brand.json").write_text(json.dumps({"logo": "brand/logo.png", "intro": "brand/intro.mp4",
                                              "outro": "brand/outro.mp4"}), encoding="utf-8")
    name_people(s, {"SPEAKER_00": "Mona"})
    cuts = read_json(s / "cuts.json")
    assert render.finish(s, "program_nocaps.mp4", "out.mp4", cuts, clean="out_clean.mp4") == 1
    for name in ("out.mp4", "out_clean.mp4"):                   # with and without captions: intro + video + outro
        info = probe(s / name)
        assert abs(info["duration"] - (1.5 + 60.0 + 1.0)) < 0.3 and (info["width"], info["height"]) == (1280, 720)
        assert render.has_audio(s / name)
    assert render.intro_seconds(s) == 1.5
    assert not list((s / "tmp").glob("*.ass"))                  # the subtitle files are cleaned up
    # the frame of a caption: the two videos differ only where the captions are (the bottom of the picture)
    frame = lambda name: subprocess.run(["ffmpeg", "-v", "error", "-ss", "20", "-i", s / name, "-frames:v", "1", "-vf",
                                         "scale=64:36,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    a, b = frame("out.mp4"), frame("out_clean.mp4")
    rows = [sum(abs(x - y) for x, y in zip(a[r * 64:(r + 1) * 64], b[r * 64:(r + 1) * 64])) for r in range(36)]
    assert sum(rows[:18]) < sum(rows[24:]) and sum(rows[24:]) > 0


def test_ass_file_has_captions_and_cards(s):
    name_people(s, {"SPEAKER_01": "Islam"})
    path = s / "tmp" / "t.ass"
    path.parent.mkdir(exist_ok=True)
    assert render.write_ass(s, path, read_json(s / "cuts.json")) == 1
    text = path.read_text(encoding="utf-8-sig")
    assert "PlayResY: 288" in text and text.count(",Card,,") == 1 and text.count(",Caption,,") > 5
    assert "Islam" in text and "ضيف الحلقة" in text and "\\fad(300,300)" in text
    assert render.write_ass(s, path, read_json(s / "cuts.json"), captions=False) == 1   # the video without captions
    text = path.read_text(encoding="utf-8-sig")
    assert text.count(",Card,,") == 1 and text.count(",Caption,,") == 0


def test_card_next_to_its_person(s):
    """Two people on one camera: the card goes on the side where the talking person sits (their face position)."""
    import pandas as pd
    name_people(s, {"SPEAKER_00": "Mona"})
    cuts = read_json(s / "cuts.json")
    f = pd.read_parquet(s / "features.parquet")
    for x, side in ((0.2, "left"), (0.8, "right"), (0.5, None)):
        f.loc[f.cam == 2, "face_x"] = x                         # SPEAKER_00 is on camera 2
        f.to_parquet(s / "features.parquet", index=False)
        assert name_cards(s, cuts)[0]["side"] == side
    split = [{**c, "split": [3, 2], "split_x": [0.5, 0.5]} if c["cam"] == 2 else c for c in cuts]
    assert name_cards(s, split)[0]["side"] == "right"           # a split screen: camera 2 is the right half
    path = s / "tmp" / "t.ass"
    path.parent.mkdir(exist_ok=True)
    render.write_ass(s, path, split)
    assert "{\\an3\\fad(300,300)}" in path.read_text(encoding="utf-8-sig")


def test_loudness_is_measured_once(s, monkeypatch):
    monkeypatch.setattr(render, "LOUDNESS", -14)
    f = render.loudness_filter(s)
    assert f.startswith("loudnorm=I=-14") and "linear=true" in f
    assert read_json(s / "tmp/loudness.json")["target"] == -14
    assert render.loudness_filter(s) == f                       # the second call reads the saved measurement
    monkeypatch.setattr(render, "LOUDNESS", None)
    assert render.loudness_filter(s) is None and render.audio_args(s) == ["-c:a", "aac", "-b:a", "192k"]


def test_clip_with_logo(s):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=white:s=64x64:d=0.1",
                    "-frames:v", "1", s / "logo.png"], check=True)
    (s / "brand.json").write_text(json.dumps({"logo": "logo.png", "logo_corner": "bottom-left"}), encoding="utf-8")
    out = render.render_clip(s, 10, 16, "clips/x.mp4", fmt="9:16", source=3, crop_x=0.5, langs="ar")
    info = probe(out)
    assert (info["width"], info["height"]) == (720, 1280) and abs(info["duration"] - 6.0) < 0.2
