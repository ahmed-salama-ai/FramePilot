import json
import shutil

import pandas as pd

from ai_director.common.io import read_json
from ai_director.common.paths import MOCK
from ai_director.director.baselines import random_cuts, wide_cuts
from ai_director.director.render import render_program
from ai_director.director.run import make_timeline
from ai_director.ingest.probe import probe


def test_timeline_matches_mock():
    sc = pd.read_parquet(MOCK / "scores.parquet")
    ours = make_timeline(sc, read_json(MOCK / "cuts.json"))
    assert json.loads(json.dumps(ours)) == read_json(MOCK / "timeline.json")


def test_random_baseline():
    cuts = random_cuts(60.0, [1, 2, 3], seed=0)
    assert cuts == random_cuts(60.0, [1, 2, 3], seed=0)                 # same seed -> same edit
    assert cuts[0]["start"] == 0.0 and cuts[-1]["end"] == 60.0
    assert all(a["end"] == b["start"] and a["cam"] != b["cam"] for a, b in zip(cuts, cuts[1:]))
    assert all(2.0 <= c["end"] - c["start"] <= 8.0 for c in cuts[:-1])


def test_wide_baseline():
    assert wide_cuts(60.0, 1) == [{"start": 0.0, "end": 60.0, "cam": 1}]


def test_render_program(tmp_path):
    shutil.copytree(MOCK / "video", tmp_path / "video")                 # a small copy of the mock session
    shutil.copy(MOCK / "session.json", tmp_path)
    cuts = [{"start": 0.0, "end": 2.0, "cam": 1}, {"start": 2.0, "end": 4.0, "cam": 2},
            {"start": 4.0, "end": 6.0, "cam": 3}]
    out = render_program(tmp_path, cuts)
    info = probe(out)
    assert (info["width"], info["height"]) == (1280, 720)
    assert abs(info["duration"] - 6.0) < 0.1                             # 3 shots x 2 s
    assert not list((tmp_path / "tmp").glob("seg*.mp4"))                 # shot files cleaned up

def clip_session(tmp_path):
    """A copy of the mock files render_clip needs (never write into samples/mock_s00)."""
    shutil.copytree(MOCK / "video", tmp_path / "video")
    for f in ("session.json", "upload.json", "transcript.json", "program_nocaps.mp4"):
        shutil.copy(MOCK / f, tmp_path)
    return tmp_path


def test_render_clip_both_formats(tmp_path):
    from ai_director.director.render import render_clip
    s = clip_session(tmp_path)
    wide = probe(render_clip(s, 12.0, 27.0, "clips/a_169.mp4"))                       # 16:9, the AI edit, captions
    assert (wide["width"], wide["height"]) == (1280, 720) and abs(wide["duration"] - 15.0) < 0.1
    tall = probe(render_clip(s, 12.0, 27.0, "clips/b_916.mp4", fmt="9:16", source=3, crop_x=0.62))
    assert (tall["width"], tall["height"]) == (720, 1280) and abs(tall["duration"] - 15.0) < 0.1
    assert probe(render_clip(s, 38.0, 52.0, "clips/c.mp4", langs="none"))["duration"] > 13.9   # no captions
    assert not list((s / "tmp").glob("*.srt"))                                          # caption files cleaned up


def test_render_clip_refuses_bad_times(tmp_path):
    import pytest
    from ai_director.director.render import render_clip
    s = clip_session(tmp_path)
    for a, b in ((50.0, 70.0), (20.0, 10.0), (-1.0, 5.0)):
        with pytest.raises(ValueError):
            render_clip(s, a, b, "clips/x.mp4")
    with pytest.raises(ValueError):
        render_clip(s, 1.0, 5.0, "clips/x.mp4", fmt="1:1")


def test_make_cuts_boost_and_mode(tmp_path):
    from ai_director.director.run import make_cuts
    s = tmp_path / "s00"
    shutil.copytree(MOCK, s)
    share = lambda cuts, cam: sum(c["end"] - c["start"] for c in cuts if c["cam"] == cam)
    normal = make_cuts(s, out="cuts_normal.json")
    boosted = make_cuts(s, boost={"cam": 3, "factor": 1.5}, out="cuts_v2.json")     # what the agent's restyle does
    wide = make_cuts(s, force_mode="wide_energy", out="cuts_wide_energy.json")
    assert share(boosted, 3) > share(normal, 3)                                      # more camera 3
    assert share(wide, 1) > share(normal, 1)                                         # more wide shot
    assert (s / "cuts_v2.json").exists() and read_json(s / "cuts.json") == read_json(MOCK / "cuts.json")  # done file untouched
