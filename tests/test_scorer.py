# tests/test_scorer.py — the scorer on the mock session
import pandas as pd
from pytest import approx

from ai_director.common.paths import MOCK
from ai_director.director.scorer import score


def test_same_scores_as_mock():
    ours = score(MOCK).sort_values(["t", "cam"]).reset_index(drop=True)
    mock = pd.read_parquet(MOCK / "scores.parquet").sort_values(["t", "cam"]).reset_index(drop=True)
    assert len(ours) == len(mock)
    assert list(ours["mode"]) == list(mock["mode"])
    assert list(ours["score"]) == approx(list(mock["score"]))


def test_speaker_camera_wins():
    df = score(MOCK)
    at = lambda t: df[df.t == t].set_index("cam").score
    assert at(20.0).idxmax() == 3        # the guest talks at 20 s -> camera 3
    assert at(8.0).idxmax() == 2         # the host talks at 8 s   -> camera 2


def test_boost_and_force_mode():
    plain = score(MOCK)
    boosted = score(MOCK, boost={"cam": 2, "factor": 1.3})
    cam2 = plain.cam == 2
    assert list(boosted[cam2].score) == approx(list(plain[cam2].score * 1.3))
    assert list(boosted[~cam2].score) == approx(list(plain[~cam2].score))
    assert set(score(MOCK, force_mode="wide_energy")["mode"]) == {"wide_energy"}