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


def test_lift_map_and_the_transcript(tmp_path):
    """Camera 3's mouth always moves (a lively listener) but camera 2's moves MORE THAN USUAL when SPEAKER_00 talks:
    the old rule ("moves most") gave SPEAKER_00 to camera 3, the lift gives camera 2. Then the transcript makes the
    talker's camera count as talking even without a moving mouth (face not found)."""
    from ai_director.perception.speaker import add_transcript_talk
    write_json(tmp_path / "session.json", {"cameras": [{"id": 1, "role": "wide"}, {"id": 2, "role": "closeup"},
                                                       {"id": 3, "role": "closeup"}]})
    write_json(tmp_path / "speech.json", [{"start": 0.0, "end": 4.0}])
    write_json(tmp_path / "diarization.json", [{"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
                                               {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_01"}])
    t = np.round(np.arange(0, 4, 0.1), 1)
    mouth = {1: np.zeros(len(t)), 2: np.where(t < 2, 0.02, 0.005), 3: np.where(t < 2, 0.025, 0.03)}
    df = pd.DataFrame([{"t": x, "cam": c, "mouth_motion": m, "face_area": 0.0 if c == 1 else 0.05}
                       for c in (1, 2, 3) for x, m in zip(t, mouth[c])])
    add_speaker_prob(tmp_path, df)
    smap = speaker_map(tmp_path, df)
    assert smap == {"SPEAKER_00": 2, "SPEAKER_01": 3}
    df.loc[(df.cam == 2) & (df.t < 1), "mouth_motion"] = 0.0                  # the face was lost for a second
    add_speaker_prob(tmp_path, df)
    add_transcript_talk(tmp_path, df, smap)
    assert df[(df.cam == 2) & (df.t < 2)].speaker_prob.min() == 1.0          # the transcript says camera 2 talks
    assert df[(df.cam == 2) & (df.t >= 2)].speaker_prob.max() < 1.0


def test_pose_gesture_hands_not_walking():
    """people(): the wrists moving against the body = a gesture; the whole person moving (walking) = not."""
    from ai_director.perception.people import people

    class Arr(list):                                   # what YOLO returns: .tolist(), .int()
        def tolist(self):
            return list(self)

        def int(self):
            return self

    class FakePose:                                     # one tracked person (id 7) per frame: box + 17 body points
        def __init__(self, frames):
            self.frames = iter(frames)

        def track(self, frame, **kw):
            box, wrist = next(self.frames)
            pts = [[0.0, 0.0] for _ in range(17)]
            pts[9] = pts[10] = wrist
            boxes = type("Boxes", (), {"__len__": lambda self: 1})()
            boxes.xyxy, boxes.id = Arr([box]), Arr([7])
            kp = SimpleNamespace(xy=Arr([pts]), conf=Arr([[0.9] * 17]))
            return [SimpleNamespace(boxes=boxes, keypoints=kp)]

    still, walk, wave = [0, 0, 100, 200], [30, 0, 130, 200], [0, 0, 100, 200]
    pose = FakePose([(still, [50, 100]), (walk, [80, 100]), (wave, [50, 160])])
    prev = {}
    numbers, persons = people(pose, None, prev)
    assert numbers == {"num_people": 1, "gesture_score": 0.0}
    assert [p[:2] for p in persons] == [(7, still)]                            # the person, for the head crop
    assert people(pose, None, prev)[0]["gesture_score"] == 0.0                # walked: the wrist moved WITH the body
    assert people(pose, None, prev)[0]["gesture_score"] == 1.0                # 0.45 of his height in 0.1 s: a gesture


def test_head_box_and_square_cut():
    """The head square comes from the face points (nose, eyes, ears) on the small frame, scaled to the full frame;
    a square that leaves the frame is filled with black, so the face is never stretched."""
    from ai_director.perception.faces import cut_square, head_box
    pts, conf = [[100, 50], [95, 45], [105, 45], [90, 48], [110, 48]] + [[0, 0]] * 12, [0.9] * 5 + [0.1] * 12
    cx, cy, side = head_box(pts, conf, [60, 30, 140, 230], scale=3)            # 640 px frame -> 1920 px
    assert (cx, cy) == pytest.approx((300, 141.6)) and side == pytest.approx(20 * 2.4 * 3)   # ears 20 px apart
    cx, cy, side = head_box(pts, [0.1] * 17, [60, 30, 140, 230])               # face points not seen: top of the box
    assert (cx, cy, side) == pytest.approx((100, 54, 64))                      # 40 px -> at least 64
    frame = np.full((100, 200, 3), 255, "uint8")
    sq = cut_square(frame, -20, 50, 80)                                        # 20 px left of the frame, 30 px below
    assert sq.shape == (80, 80, 3)
    assert sq[:50, 20:].min() == 255 and sq[:, :20].max() == 0 and sq[50:].max() == 0
    assert cut_square(frame, 300, 0, 50) is None


def test_faces_per_person():
    """faces(): every person's face from their own head crop. The camera's numbers = the biggest face, with face_x in
    the FULL frame; the mouth movement is kept per person (two people on one camera are not mixed)."""
    pytest.importorskip("mediapipe")
    from ai_director.perception.faces import faces

    def face(mouth, size):                                    # a face filling `size` of the crop, lips `mouth` apart
        pts = [SimpleNamespace(x=0.5, y=0.5) for _ in range(478)]
        h = size / 2
        for i, (x, y) in {33: (0.5 - h, 0.45), 263: (0.5 + h, 0.45), 1: (0.5, 0.5), 10: (0.5, 0.5 - h),
                          152: (0.5, 0.5 + h), 13: (0.5, 0.6), 14: (0.5, 0.6 + mouth)}.items():
            pts[i] = SimpleNamespace(x=x, y=y)
        return pts

    class FakeLandmarker:                                     # answers the head crops in the order they are asked
        def __init__(self, answers):
            self.answers = iter(answers)

        def detect(self, image):
            return SimpleNamespace(face_landmarks=[a] if (a := next(self.answers)) else [])

    frame = np.zeros((1080, 1920, 3), "uint8")
    head = lambda x: [[x, 100], [x - 5, 95], [x + 5, 95], [x - 10, 98], [x + 10, 98]] + [[0, 0]] * 12  # noqa: E731
    persons = [(i, [x - 40, 80, x + 40, 300], head(x), [0.9] * 5 + [0.1] * 12) for i, x in ((1, 100), (2, 500))]
    answers = []
    for k in range(4):                                        # person 1: big, still mouth; person 2: small, talks
        answers += [face(0.02, 0.6), face(0.02 + 0.05 * (k % 2), 0.4)]
    lm, hists = FakeLandmarker(answers), {}
    for k in range(4):
        cam, rows = faces(lm, frame, persons, 3.0, hists)
    side = 20 * 2.4 * 3                                       # the head square in full-frame pixels (144 px)
    assert cam["face_area"] == pytest.approx(0.6 * 0.6 * side * side / (1920 * 1080), abs=1e-4)   # person 1
    assert cam["face_x"] == pytest.approx(300 / 1920, abs=1e-4) and cam["mouth_motion"] == 0.0
    assert [r["id"] for r in rows] == [1, 2] and [r["x"] for r in rows] == [0.1562, 0.7812]
    assert rows[0]["mouth_motion"] == 0.0 and rows[1]["mouth_motion"] > 0.02  # person 2's own mouth
    assert np.isnan(faces(FakeLandmarker([None, None]), frame, persons, 3.0, {})[1][0]["mouth_motion"])


def test_person_map_two_people_on_one_camera(tmp_path):
    """Camera 2 shows two people. Camera-level, they share one mouth number; per person, SPEAKER_00 is the one on the
    right and SPEAKER_02 the one on the left. A speaker nobody's face was seen for -> the camera-level map."""
    from ai_director.perception.speaker import person_map
    write_json(tmp_path / "session.json", {"cameras": [{"id": 1, "role": "wide"}, {"id": 2, "role": "closeup"},
                                                       {"id": 3, "role": "closeup"}]})
    write_json(tmp_path / "speech.json", [{"start": 0.0, "end": 9.0}])
    write_json(tmp_path / "diarization.json", [{"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00"},
                                               {"start": 3.0, "end": 6.0, "speaker": "SPEAKER_01"},
                                               {"start": 6.0, "end": 9.0, "speaker": "SPEAKER_02"}])
    t = np.round(np.arange(0, 9, 0.1), 1)
    talks = {(2, 1): t >= 6, (2, 2): t < 3, (3, 5): (t >= 3) & (t < 6), (1, 9): t < 9}   # (camera, person id)
    xs = {(2, 1): 0.2, (2, 2): 0.8, (3, 5): 0.5, (1, 9): 0.5}
    persons = pd.DataFrame([{"t": x, "cam": c, "id": i, "x": xs[c, i], "found": True,
                             "mouth_motion": 0.03 if talk else 0.004}
                            for (c, i), m in talks.items() for x, talk in zip(t, m)])
    who = person_map(tmp_path, persons)
    assert {k: (v["cam"], v["x"]) for k, v in who.items()} == {"SPEAKER_00": (2, 0.8), "SPEAKER_01": (3, 0.5),
                                                              "SPEAKER_02": (2, 0.2)}       # never the wide camera
    assert person_map(tmp_path, persons[persons.t < 6]).keys() == {"SPEAKER_00", "SPEAKER_01"}
    df = pd.DataFrame([{"t": x, "cam": c, "mouth_motion": 0.03 if (c == 3 and x >= 6) else 0.004, "face_area": 0.05}
                       for c in (1, 2, 3) for x in t])
    add_speaker_prob(tmp_path, df)
    assert speaker_map(tmp_path, df, person_map(tmp_path, persons[persons.t < 6])) == {
        "SPEAKER_00": 2, "SPEAKER_01": 3, "SPEAKER_02": 3}    # SPEAKER_02 unknown per person -> camera-level lift
    assert person_map(tmp_path, pd.DataFrame()) == {}


def test_follow_the_talker(tmp_path):
    """Camera 2 shows the host (bigger face, right) and a guest (left): while the guest talks, camera 2's face numbers
    are the guest's (and the 9:16 crop goes to the guest); when nobody on it talks, the biggest face stays."""
    from ai_director.perception.speaker import follow_talker
    write_json(tmp_path / "diarization.json", [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_01"}])
    host = {"id": 1, "x": 0.8, "found": True, "face_area": 0.03, "face_x": 0.8, "frontalness": 0.5, "mouth_motion": 0.001}
    guest = {"id": 2, "x": 0.21, "found": True, "face_area": 0.02, "face_x": 0.2, "frontalness": 0.9,
             "mouth_motion": float("nan")}                                      # just found: not measurable yet
    t = [0.0, 0.5, 1.5]
    persons = pd.DataFrame([{"t": x, "cam": 2, **p} for x in t for p in (host, guest)])
    df = pd.DataFrame([{"t": x, "cam": c, **{k: host[k] for k in ("face_area", "face_x", "frontalness", "mouth_motion")}}
                       for x in t for c in (2, 3)])
    follow_talker(tmp_path, df, persons, {"SPEAKER_01": {"cam": 2, "x": 0.2, "lift": 3.0}})
    cam2 = df[df.cam == 2].set_index("t")
    assert cam2.loc[0.0, "face_x"] == 0.2 and cam2.loc[0.5, "frontalness"] == 0.9 and cam2.loc[0.5, "mouth_motion"] == 0
    assert cam2.loc[1.5, "face_x"] == 0.8                                      # nobody on camera 2 talks: the biggest
    assert (df[df.cam == 3].face_x == 0.8).all()                               # other cameras untouched
    follow_talker(tmp_path, df, persons, {})                                   # no person map: nothing changes


def test_cameras_at_the_same_time_give_the_same_numbers(tmp_path):
    """run.main with 3 cameras at once = one after another (each camera has its own models and tracker)."""
    import shutil

    from ai_director.common.paths import MOCK
    from ai_director.perception.faces import FACE_MODEL
    from ai_director.perception.run import POSE_MODEL, main
    if not (POSE_MODEL.exists() and FACE_MODEL.exists()):
        pytest.skip("the YOLO-pose / face models are not downloaded")
    for f in ("session.json", "speech.json", "diarization.json"):
        shutil.copy(MOCK / f, tmp_path)
    shutil.copytree(MOCK / "video", tmp_path / "video")
    one, three = main(tmp_path, seconds=1, workers=1), main(tmp_path, seconds=1, workers=3)
    pd.testing.assert_frame_equal(one, three)
    assert len(one) == 3 * 10 and not (tmp_path / "features.parquet").exists()   # quick test: nothing saved
