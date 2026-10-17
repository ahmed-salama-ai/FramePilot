import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mpt
from mediapipe.tasks.python import vision

from ..common.paths import ROOT

FACE_MODEL = ROOT / "data" / "models" / "face_landmarker.task"
NO_FACE = {"face_area": 0.0, "face_x": 0.5, "frontalness": 0.0, "mouth_motion": 0.0}
CROP = 256               # head crops are enlarged to the landmark model's own input size (256x256)
HEAD = 2.4               # the head square = 2.4 x the spread of the face points (nose, eyes, ears)


def open_landmarker():
    """IMAGE mode, one face per head crop: every crop is looked at on its own (no tracking, so no tracking luck)."""
    if not FACE_MODEL.exists():
        raise FileNotFoundError(f"{FACE_MODEL} is missing: download face_landmarker.task")
    opts = vision.FaceLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=str(FACE_MODEL)),
        running_mode=vision.RunningMode.IMAGE, num_faces=1)
    return vision.FaceLandmarker.create_from_options(opts)


def head_box(pts, conf, box, scale=1.0):
    """Where one person's head is: (centre x, centre y, side of the square) in full-frame pixels. pts/conf/box come
    from YOLO-pose on a smaller frame (scale = full width / that width). From the face points (nose, eyes, ears) when
    2+ are seen, else the top of the person's box."""
    seen = [pts[j] for j in range(5) if conf[j] > 0.3]
    if len(seen) >= 2:
        xs, ys = [p[0] for p in seen], [p[1] for p in seen]
        cx, cy = float(np.mean(xs)), float(np.mean(ys))
        side = max(max(xs) - min(xs), max(ys) - min(ys), 0.25 * (box[2] - box[0])) * HEAD
    else:
        cx, cy, side = (box[0] + box[2]) / 2, box[1] + 0.12 * (box[3] - box[1]), 0.5 * (box[2] - box[0])
    return cx * scale, cy * scale, max(side * scale, 64)


def cut_square(frame, x0, y0, side):
    """The side x side square at (x0, y0); where it leaves the frame it is filled with black (stays square, so the
    face is not stretched). None if it is completely outside."""
    h, w = frame.shape[:2]
    a, b, c, d = max(x0, 0), max(y0, 0), min(x0 + side, w), min(y0 + side, h)
    if c <= a or d <= b:
        return None
    return cv2.copyMakeBorder(frame[b:d, a:c], b - y0, y0 + side - d, a - x0, x0 + side - c, cv2.BORDER_CONSTANT)


def head_face(lm, frame, cx, cy, side):
    """One head (from head_box): cut it out of the full frame, enlarge it to 256x256, find the face in it ->
    face_area, face_x (0..1 of the FULL frame, like before), frontalness, mouth_open; None if no face is found."""
    side = int(round(side))
    x0, y0 = int(round(cx - side / 2)), int(round(cy - side / 2))
    crop = cut_square(frame, x0, y0, side)
    if crop is None:
        return None
    crop = cv2.resize(crop, (CROP, CROP), interpolation=cv2.INTER_LINEAR)
    res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
    if not res.face_landmarks:
        return None
    f = face_info(res.face_landmarks[0])
    h, w = frame.shape[:2]
    return {"face_area": f["face_area"] * side * side / (w * h), "face_x": (x0 + f["face_x"] * side) / w,
            "frontalness": f["frontalness"], "mouth_open": f["mouth_open"]}


def mouth_motion(hist, mouth_open):
    """How much the mouth opening changed in the last 0.5 s (this person's last 5 samples). mouth_open None = no face
    (the history starts again). None = not measurable yet (fewer than 3 samples)."""
    if mouth_open is None:
        hist.clear()
        return None
    hist.append(mouth_open)
    del hist[:-5]
    return float(np.std(hist)) if len(hist) >= 3 else None


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


def faces(lm, frame, persons, scale, hists):
    """One full frame + the people YOLO-pose found -> (the camera's numbers, one row per person).
    persons = [(track id, box, body points, point confidences)] on the small frame (scale = full width / its width);
    hists = {track id: their last mouth openings}. The camera's numbers = the biggest face (main face, as before);
    mouth movement is measured PER PERSON, so two people on one camera are never mixed."""
    w, main, rows = frame.shape[1], None, []
    for tid, box, pts, conf in persons:
        cx, cy, side = head_box(pts, conf, box, scale)
        f = head_face(lm, frame, cx, cy, side)
        mm = mouth_motion(hists.setdefault(tid, []), f["mouth_open"] if f else None)
        rows.append({"id": tid, "x": round(cx / w, 4), "found": f is not None,
                     "mouth_motion": float("nan") if mm is None else round(mm, 4),
                     **{k: round(f[k], 4) if f else NO_FACE[k] for k in ("face_area", "face_x", "frontalness")}})
        if f and (main is None or f["face_area"] > main["face_area"]):
            main = {"face_area": f["face_area"], "face_x": f["face_x"], "frontalness": f["frontalness"],
                    "mouth_motion": mm or 0.0}
    return ({k: round(float(v), 4) for k, v in main.items()} if main else dict(NO_FACE)), rows
