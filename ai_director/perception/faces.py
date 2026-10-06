# ai_director/perception/faces.py — the main face: size, position, looking at the camera, mouth movement
# (MediaPipe Face Landmarker: 478 points per face, x and y are 0..1 of the image)
# Owner: Sara Walid (taken over by Ahmed Salama)
import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mpt
from mediapipe.tasks.python import vision

from ..common.paths import ROOT

FACE_MODEL = ROOT / "data" / "models" / "face_landmarker.task"
NO_FACE = {"face_area": 0.0, "face_x": 0.5, "frontalness": 0.0, "mouth_motion": 0.0}


def open_landmarker():
    """A NEW landmarker for every camera: in VIDEO mode it needs increasing timestamps."""
    if not FACE_MODEL.exists():
        raise FileNotFoundError(f"{FACE_MODEL} is missing: download face_landmarker.task (see the guide).")
    opts = vision.FaceLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=str(FACE_MODEL)),
        running_mode=vision.RunningMode.VIDEO, num_faces=4)
    return vision.FaceLandmarker.create_from_options(opts)


def dist(a, b):
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def face_info(lms):
    """478 face points -> size, centre, how frontal (1 = looks straight), how open the mouth is."""
    xs, ys = [p.x for p in lms], [p.y for p in lms]
    left, right, nose = lms[33], lms[263], lms[1]                     # eye corners and nose tip
    r = (nose.x - left.x) / max(right.x - left.x, 1e-6)               # 0.5 = nose exactly between the eyes
    return {"face_area": (max(xs) - min(xs)) * (max(ys) - min(ys)),
            "face_x": (min(xs) + max(xs)) / 2,
            "frontalness": max(0.0, 1 - abs(r - 0.5) * 2),
            "mouth_open": dist(lms[13], lms[14]) / max(dist(lms[10], lms[152]), 1e-6)}   # lips / face height


def faces(lm, frame, t, mouth_hist):
    """One frame -> the biggest face's numbers. mouth_motion = how much the mouth opening changed in 0.5 s."""
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    res = lm.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), int(round(t * 1000)))
    if not res.face_landmarks:
        mouth_hist.clear()
        return dict(NO_FACE)
    f = max((face_info(l) for l in res.face_landmarks), key=lambda d: d["face_area"])   # main face = biggest
    mouth_hist.append(f.pop("mouth_open"))
    del mouth_hist[:-5]                                               # keep the last 5 samples = 0.5 s
    f["mouth_motion"] = float(np.std(mouth_hist)) if len(mouth_hist) >= 3 else 0.0
    return {k: round(float(v), 4) for k, v in f.items()}
