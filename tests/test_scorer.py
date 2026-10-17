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

def test_person_without_a_found_face_still_counts(tmp_path):
    """The transcript says camera 2's person talks but the face wasn't found (standing): a third of full strength.
    A face that WAS found but is small (panel distance) counts the same third, never less."""
    import shutil
    from ai_director.director.scorer import CFG, W
    s = tmp_path / "s00"
    shutil.copytree(MOCK, s)
    f = pd.read_parquet(s / "features.parquet")
    row = (f.cam == 2) & (f.t == 8.0)
    f.loc[row, ["face_area", "frontalness", "speaker_prob", "num_people", "gesture_score", "shake"]] = [0, 0, 1, 1, 0, 0]
    f.to_parquet(s / "features.parquet", index=False)
    got = score(s)
    r = f[row].iloc[0]
    quality = W["quality"] * (0.6 * r.sharpness + 0.4 * r.exposure_ok)
    assert float(got[(got.t == 8.0) & (got.cam == 2)].score.iloc[0]) == approx(
        (W["speaker"] * CFG["no_face_size"] + quality) * 1.0)               # conversation mode, close-up: x1.0
    f.loc[row, "face_area"] = 0.01                                          # found, but small: 0.01 / 0.15 = 0.07
    f.to_parquet(s / "features.parquet", index=False)
    small = float(score(s).query("t == 8.0 and cam == 2").score.iloc[0])
    assert small == approx((W["speaker"] * CFG["no_face_size"] + quality) * 1.0)   # still a third, not 0.07
    f.loc[row, "face_area"] = 0.15                                          # a big face: full strength
    f.to_parquet(s / "features.parquet", index=False)
    assert float(score(s).query("t == 8.0 and cam == 2").score.iloc[0]) == approx((W["speaker"] + quality) * 1.0)
    f.loc[row, ["face_area", "num_people"]] = [0, 0]                        # nobody there: no speaker points
    f.to_parquet(s / "features.parquet", index=False)
    assert float(score(s).query("t == 8.0 and cam == 2").score.iloc[0]) == approx(quality * 1.0)
