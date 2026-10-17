# tests/test_eval.py — the evaluation (stage 8) on made-up data and on copies of the mock session (no models needed)
import json
import shutil

import numpy as np
import pandas as pd
import pytest

from ai_director.common.check import check_session
from ai_director.common.io import read_json, write_json
from ai_director.common.paths import MOCK
from ai_director.director.run import on_air_at as director_on_air
from eval.director_eval import edit_scores, evaluate_director, on_air_at


@pytest.fixture
def s(tmp_path):
    shutil.copytree(MOCK, tmp_path / "s00")               # never write into the mock
    return tmp_path / "s00"


def test_on_air_at_is_the_same_as_the_director(s):
    cuts, t = read_json(s / "cuts.json"), pd.read_csv(s / "labels.csv").t.values
    assert list(on_air_at(cuts, t)) == [director_on_air(cuts, x) for x in t]


def test_scores_by_hand():
    cuts = [{"start": 0.0, "end": 0.5, "cam": 1}, {"start": 0.5, "end": 1.0, "cam": 2}]
    times = np.round(np.arange(0, 1.0, 0.1), 2)                       # 10 moments
    speaking = np.array([-1, -1, 2, 2, 2, 2, 2, 3, 3, -1])            # nobody / camera 2's person / camera 3's
    human = np.array([1, 1, 1, 2, 2, 2, 2, 3, 3, 3])
    r = edit_scores(cuts, times, speaking, human)
    # on air: cam 1 at 0.0-0.4 s, cam 2 at 0.5-0.9 s
    assert r["agreement"] == 0.5                                      # same camera as the human at 0.0-0.2 and 0.5-0.6
    assert r["speaker_coverage"] == round(2 / 7, 3)                   # 7 speaking moments, the speaker's camera at 2
    assert (r["short_cuts"], r["avg_shot"], r["shots"]) == (1, 0.5, 2)   # the first shot is 0.5 s (the last one
    assert edit_scores(cuts, times, speaking)["agreement"] is None       # doesn't count); no labels -> no agreement


def test_the_ai_beats_the_baselines_on_the_mock(s):
    r = evaluate_director(s)
    assert r["ai"]["agreement"] > r["random"]["agreement"] > r["wide"]["agreement"]
    assert r["ai"]["speaker_coverage"] > 0.8 and r["wide"]["speaker_coverage"] == 0.0 and r["ai"]["short_cuts"] == 0
    assert r["human"]["agreement"] == 1.0 and r["wide"]["shots"] == 1
    (s / "labels.csv").unlink()                                       # no human labels yet
    r = evaluate_director(s)
    assert "human" not in r and r["ai"]["agreement"] is None and r["ai"]["speaker_coverage"] > 0.8


def test_eval_run_writes_metrics(s):
    import eval.run as er
    (s / "metrics.json").unlink()
    (s / "logs").mkdir(exist_ok=True)
    write_json(s / "logs" / "times.json", {"Ingest + Sync": 41.2, "Render": 63.0})
    m = er.evaluate(s)
    assert m["director"]["ai"]["agreement"] > 0.8 and m["highlights"] == {"precision_at_3": 0.5, "labels": 2}
    assert m["processing_seconds"]["Render"] == 63.0
    assert set(m) == {"director", "highlights", "processing_seconds"}
    write_json(s / "metrics.json", m)
    assert check_session(s) == []                                     # metrics.json follows the contract
    (s / "diarization.json").unlink()                                 # one part breaks -> the others still work
    m = er.evaluate(s)
    assert m["director"] is None and m["highlights"]["precision_at_3"] == 0.5
