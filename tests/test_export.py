import json
import shutil
import xml.etree.ElementTree as ET
import zipfile

import pytest

from ai_director.common.io import read_json, write_json
from ai_director.common.paths import MOCK
from ai_director.director.export import edl, export_package, fcp_xml, frames, timecode
from ai_director.director.versions import add_version, delete_version, get_version, list_versions, new_version
from ai_director.highlights.publish import Answer, clean_chapters, make_publish


@pytest.fixture
def s(tmp_path):
    shutil.copytree(MOCK, tmp_path / "s00")
    return tmp_path / "s00"


def test_timecode():
    assert frames(2.4) == 72 and timecode(72) == "00:00:02:12" and timecode(30 * 3661 + 5) == "01:01:01:05"


def test_fcp_xml_has_every_shot_from_its_camera(s):
    cuts = read_json(s / "cuts.json")
    cuts[3] = {**cuts[3], "split": [3, 2], "split_x": [0.5, 0.5]}           # one split-screen shot
    root = ET.fromstring(fcp_xml(s, cuts, "test").split("\n", 2)[2])        # after the <?xml?> and DOCTYPE lines
    v1, v2 = root.findall("./sequence/media/video/track")
    items = v1.findall("clipitem")
    assert len(items) == len(cuts)
    for item, c in zip(items, cuts):
        assert item.find("name").text == f"cam{c['cam']}.mp4"
        assert int(item.find("start").text) == int(item.find("in").text) == frames(c["start"])   # synced files
        assert int(item.find("end").text) == frames(c["end"])
    assert [i.find("enabled").text for i in v2.findall("clipitem")] == ["FALSE"]   # the other split camera, off
    assert len(root.findall("./sequence/marker")) == 1
    urls = [f.find("pathurl").text for f in root.iter("file") if f.find("pathurl") is not None]
    assert len(urls) == len({c["cam"] for c in cuts} | {2, 3}) and all(u.startswith("file://localhost/") for u in urls)
    assert len(root.findall("./sequence/media/audio/track")) == 2


def test_edl_lines(s):
    cuts = read_json(s / "cuts.json")
    text = edl(s, cuts, "test")
    events = [l for l in text.splitlines() if l[:3].isdigit()]
    assert len(events) == len(cuts) + 1 and events[0].startswith("001  CAM1 ") and " AA " in events[-1]


def test_export_package(s):
    z = zipfile.ZipFile(export_package(s, "v1"))
    assert sorted(z.namelist()) == ["README.txt", "captions_ar.srt", "captions_en.srt", "s00_v1.edl", "s00_v1.xml"]
    assert "Premiere Pro" in z.read("README.txt").decode()


def test_versions(s, tmp_path):
    assert [v["id"] for v in list_versions(s)] == ["v1"]                   # no versions.json: the pipeline's edit
    v = new_version(s, "agent", "show the guest more")
    assert v["id"] == "v2" and (s / "versions/v2").is_dir()
    write_json(s / v["cuts"], read_json(s / "cuts.json"))
    add_version(s, v)
    assert new_version(s, "agent")["id"] == "v3"
    assert get_version(s, "v2")["note"] == "show the guest more"
    with pytest.raises(ValueError):
        delete_version(s, "v1", tmp_path / "trash")
    left = delete_version(s, "v2", tmp_path / "trash")
    assert [x["id"] for x in left] == ["v1"] and not (s / "versions/v2").exists()
    assert len(list((tmp_path / "trash").iterdir())) == 1                  # moved, not erased


def test_an_update_shares_its_base_and_keeps_it(s, tmp_path):
    v1 = get_version(s, "v1")
    v2 = new_version(s, "update", "updated from v1", base=v1)
    assert (v2["cuts"], v2["nocaps"]) == ("cuts.json", "program_nocaps.mp4")       # the same edit, not copied
    assert (v2["program"], v2["clean"]) == ("versions/v2/program.mp4", "versions/v2/program_clean.mp4")
    add_version(s, v2)
    assert get_version(s, "latest")["id"] == "v2" and get_version(s, "v1")["program"] == "program.mp4"
    restyle = new_version(s, "agent", "show the guest more")                        # a new edit: its own files
    write_json(s / restyle["cuts"], read_json(s / "cuts.json"))
    add_version(s, restyle)
    update = new_version(s, "update", "updated from v3", base=restyle)
    add_version(s, update)
    with pytest.raises(ValueError, match="delete v4 first"):                        # v4 uses v3's edit
        delete_version(s, "v3", tmp_path / "trash")
    delete_version(s, "v4", tmp_path / "trash")
    assert [v["id"] for v in delete_version(s, "v3", tmp_path / "trash")] == ["v1", "v2"]
    assert (s / "cuts.json").exists() and (s / "program_nocaps.mp4").exists()      # v2's shared files are v1's


def test_old_restyle_is_version_2(s):
    shutil.copy(s / "program.mp4", s / "program_v2.mp4")                   # made before version history
    assert [v["id"] for v in list_versions(s)] == ["v1", "v2"]
    v = new_version(s, "agent")
    assert v["id"] == "v3"
    add_version(s, v)
    assert [x["id"] for x in read_json(s / "versions.json")] == ["v1", "v2", "v3"]   # the old one is kept


def test_chapters_follow_youtube_rules():
    rows = [{"start": float(t)} for t in range(0, 600, 7)]
    ch = lambda t, x="x": type("C", (), {"start": t, "title_ar": x, "title_en": x})   # noqa: E731
    got = clean_chapters([ch(12), ch(100), ch(110), ch(300), ch(590)], rows, 600)
    assert [c["start"] for c in got] == [0.0, 98.0, 301.0]       # first at 0:00, 30 s apart, snapped, none at the end
    assert clean_chapters([ch(0), ch(200)], rows, 600) == []      # fewer than 3: YouTube shows none


def test_make_publish_with_a_fake_model(s):
    hl = read_json(s / "highlights.json")
    answer = Answer.model_validate({
        "chapters": [{"start": 0, "title_ar": "البداية", "title_en": "Intro"},
                     {"start": 18.4, "title_ar": "السي في", "title_en": "The CV"},
                     {"start": 40, "title_ar": "المرتبات", "title_en": "Salaries"}],
        "summary_ar": "حلقة عن الشغل.", "summary_en": "An episode about work.",
        "key_points_ar": ["سي في صفحة واحدة"], "key_points_en": ["A one-page CV"],
        "posts": [{"highlight": hl[0]["id"], "text_ar": "شوف", "text_en": "Watch", "hashtags": ["career tips", "#CV"]},
                  {"highlight": "h99", "text_ar": "x", "text_en": "x", "hashtags": []}]})
    prompts = []
    p = make_publish(s, ask=lambda prompt: prompts.append(prompt) or answer)
    assert "[00:01] SPEAKER_00:" in prompts[0] and hl[0]["id"] in prompts[0]
    assert len(p["posts"]) == 1 and p["posts"][0]["hashtags"] == ["#careertips", "#CV"]   # unknown h99 dropped
    assert p["chapters"] == [] or p["chapters"][0]["start"] == 0.0         # the 60 s mock: chapters too close
    assert p["description_en"].startswith("An episode about work.") and "#careertips" in p["description_en"]
    assert read_json(s / "publish.json") == p
