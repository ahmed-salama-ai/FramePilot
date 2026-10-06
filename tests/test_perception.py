# tests/test_perception.py — the perception maths on made-up images and numbers (no YOLO / no video needed)
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from ai_director.common.io import write_json
from ai_director.perception.quality import quality
from ai_director.perception.speaker import add_speaker_prob, speaker_map, speech_mask

cv2 = pytest.importorskip("cv2")


def test_quality_sharp_blurry_dark_shaky():
    rng = np.random.default_rng(0)
    sharp = (rng.random((360, 640)) * 120 + 60).astype("uint8")          # lots of fine detail, normal brightness
    blurry = cv2.GaussianBlur(sharp, (31, 31), 10)
    q = quality(sharp, None)
    assert q["sharpness"] == 1.0 and q["exposure_ok"] == 1.0 and q["shake"] == 0.0
    assert quality(blurry, None)["sharpness"] < 0.1
    assert quality(np.full((360, 640), 20, "uint8"), None)["exposure_ok"] == 0.4                # too dark
    moved = np.roll(blurry, 4, axis=1)                                                         # 4 px to the right
    assert 0.4 < quality(moved, blurry)["shake"] < 0.6                                          # 4 / 8 = 0.5
    assert quality(blurry, blurry)["shake"] < 0.01                                              # still camera


def test_face_info_numbers():
    pytest.importorskip("mediapipe")
    from ai_director.perception.faces import face_info
    pts = [SimpleNamespace(x=0.5, y=0.5) for _ in range(478)]
    for i, (x, y) in {33: (0.40, 0.40), 263: (0.60, 0.40), 1: (0.50, 0.50), 10: (0.50, 0.30), 152: (0.50, 0.70),
                      13: (0.50, 0.60), 14: (0.50, 0.62)}.items():
        pts[i] = SimpleNamespace(x=x, y=y)
    f = face_info(pts)
    assert f["face_area"] == pytest.approx(0.2 * 0.4)        # box 0.40-0.60 wide x 0.30-0.70 high
    assert f["face_x"] == pytest.approx(0.5) and f["frontalness"] == pytest.approx(1.0)   # nose in the middle
    assert f["mouth_open"] == pytest.approx(0.02 / 0.4)      # lips 0.02 apart, face 0.4 high
    pts[1] = SimpleNamespace(x=0.58, y=0.5)                   # head turned: nose near one eye
    assert face_info(pts)["frontalness"] == pytest.approx(0.2)


def test_speech_mask():
    t = np.array([0.0, 0.5, 1.0, 1.5, 2.0])
    assert speech_mask(t, [{"start": 0.5, "end": 1.5}]).tolist() == [False, True, True, False, False]


def test_speaker_prob_and_map(tmp_path):
    write_json(tmp_path / "session.json", {"cameras": [{"id": 1, "role": "wide"}, {"id": 2, "role": "closeup"},
                                                       {"id": 3, "role": "closeup"}]})
    write_json(tmp_path / "speech.json", [{"start": 0.0, "end": 2.0}])                    # silence after 2 s
    write_json(tmp_path / "diarization.json", [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
                                               {"start": 1.0, "end": 2.0, "speaker": "SPEAKER_01"}])
    t = np.round(np.arange(0, 3, 0.1), 1)
    mouth = {1: np.zeros(len(t)),                                                         # wide: no faces
             2: np.where(t < 1, 0.03, 0.002),                                             # cam 2 talks first
             3: np.where((t >= 1) & (t < 2), 0.03, 0.002) + np.where(t >= 2, 0.03, 0)}   # cam 3, then laughs
    df = pd.DataFrame([{"t": x, "cam": c, "mouth_motion": m} for c in (1, 2, 3) for x, m in zip(t, mouth[c])])
    add_speaker_prob(tmp_path, df)
    assert df[(df.cam == 3) & (df.t >= 2)].speaker_prob.max() == 0       # moving mouth in silence = not talking
    assert df[(df.cam == 2) & (df.t < 1)].speaker_prob.min() > 0.9
    assert speaker_map(tmp_path, df) == {"SPEAKER_00": 2, "SPEAKER_01": 3}
