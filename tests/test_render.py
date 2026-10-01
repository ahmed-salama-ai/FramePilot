# tests/test_render.py — timeline, baselines and rendering on the mock session
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