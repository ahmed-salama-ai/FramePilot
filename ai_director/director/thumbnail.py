import subprocess
from pathlib import Path

import numpy as np

from ai_director.common.io import read_json, run, session_from_argv, write_json
from ai_director.common.paths import ROOT
from ai_director.director.brand import load_brand, logo_overlay

W, H = 1280, 720
HEAD = 0.55 
CANDIDATES = 6
LAUGH = 0.25


def frame_at(s, cam, t):
    """One RGB frame of video/camN.mp4 at t s (numpy array)."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", f"video/cam{cam}.mp4", "-frames:v", "1",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], cwd=s, capture_output=True, check=True)
    from ai_director.ingest.probe import probe
    size = probe(Path(s) / f"video/cam{cam}.mp4")
    return np.frombuffer(r.stdout, np.uint8).reshape(size["height"], size["width"], 3)


def candidates(s, a, b, feats, laugh, spk_cam):
    """The best-looking moments a..b on the close-ups by the perception numbers: [(score, t, cam, face_x)]."""
    f = feats[feats.t.between(a + 1, b - 1) & (feats.face_area > 0) & feats.cam.isin(set(spk_cam.values()))]
    if f.empty:
        return []
    score = (f.frontalness + 0.5 * (f.mouth_motion / 0.03).clip(upper=1) + 0.5 * f.speaker_prob
             + 0.5 * f.t.astype(int).map(lambda t: laugh.get(t, 0.0) >= LAUGH) + 0.3 * f.sharpness)
    out = []
    for i in score.sort_values(ascending=False).index:
        t = float(f.t[i])
        if all(abs(t - x[1]) >= 1.0 for x in out):
            out.append((float(score[i]), t, int(f.cam[i]), float(f.face_x[i])))
        if len(out) == CANDIDATES:
            break
    return out


class Faces:
    """YOLO+MediaPipe"""
    def __init__(self):
        self.ok = False
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mpt
            from mediapipe.tasks.python import vision
            from ultralytics import YOLO
            from ai_director.perception.faces import FACE_MODEL
            pose = ROOT / "data" / "models" / "yolo11s-pose.pt"
            if not pose.exists() or not FACE_MODEL.exists():
                return
            self.mp, self.pose = mp, YOLO(str(pose))
            self.lm = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
                base_options=mpt.BaseOptions(model_asset_path=str(FACE_MODEL)), running_mode=vision.RunningMode.IMAGE,
                num_faces=1, output_face_blendshapes=True))
            self.ok = True
        except Exception as e:                                   #no models / packages: the simple crop
            print(f"  thumbnails: face models not used ({type(e).__name__}: {str(e)[:80]})")

    def look(self, img, face_x):
        """The head nearest face_x: (cx, cy, side, expression score) in pixels, or None."""
        import cv2
        from ai_director.perception.faces import cut_square, face_info, head_box
        r = self.pose.predict(img[:, :, ::-1], conf=0.4, verbose=False)[0]
        if r.keypoints is None or not len(r.boxes):
            return None
        heads = [head_box(p, c, bx) for p, c, bx in zip(r.keypoints.xy.tolist(), r.keypoints.conf.tolist(),
                                                         r.boxes.xyxy.tolist())]
        cx, cy, side = min(heads, key=lambda h: abs(h[0] / img.shape[1] - face_x))
        side = int(round(side))
        crop = cut_square(img, int(round(cx - side / 2)), int(round(cy - side / 2)), side)
        if crop is None:
            return None
        crop = cv2.resize(np.ascontiguousarray(crop), (256, 256))
        res = self.lm.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=crop))
        if not res.face_landmarks:
            return None
        bs = {c.category_name: c.score for c in res.face_blendshapes[0]} if res.face_blendshapes else {}
        smile = (bs.get("mouthSmileLeft", 0) + bs.get("mouthSmileRight", 0)) / 2
        blink = max(bs.get("eyeBlinkLeft", 0), bs.get("eyeBlinkRight", 0))
        front = face_info(res.face_landmarks[0])["frontalness"]
        return cx, cy, side, front + smile + 0.4 * bs.get("jawOpen", 0) - 1.5 * max(blink - 0.3, 0)


def crop_box(cx, cy, side, w, h):
    """The 16:9 part of the frame (x, y, width, height) with the head HEAD of its height at about 1/3 of the width, and
    where the title goes: ("right" / "left", free width in thumbnail pixels), or ("bottom", W) when the head leaves
    too little room beside it."""
    ch = int(min(max(side / HEAD, h / 2), h))
    cw = int(min(ch * 16 / 9, w))
    ch = int(cw * 9 / 16)
    right = cx < w / 2                                           # the face on the left half -> the title on the right
    x = int(min(max(cx - (0.3 if right else 0.7) * cw, 0), w - cw))
    y = int(min(max(cy - 0.45 * ch, 0), h - ch))
    k = W / cw
    free = W - (cx + side / 2 - x) * k - 30 if right else (cx - side / 2 - x) * k - 30
    if free < 380:
        return (x, y, cw, ch), ("bottom", W)
    return (x, y, cw, ch), ("right" if right else "left", int(free))


def ass_title(path, title, place, arabic, brand):
    """The title as a .ass file on a 1280x720 canvas: big bold letters in the brand's text colour with a thick outline,
    in the free place beside the head (or at the bottom)."""
    from ai_director.audio.subtitles import FONT, RLM
    from ai_director.director.brand import ass_colour
    side, free = place
    n = len(title)
    size = 112 if n <= 16 else 94 if n <= 30 else 76 if n <= 50 else 60
    c = brand["captions"]
    if side == "bottom":
        align, ml, mr, mv = 2, 60, 60, 46
        size = min(size, 84)
    else:
        align = 6 if arabic else 4                              # Arabic hangs on the right edge, English on the left
        ml, mr, mv = (W - free + 10, 50, 40) if side == "right" else (50, W - free + 10, 40)
    text = (RLM if arabic else "") + title.replace("{", "(").replace("}", ")").replace("\\", "/")
    Path(path).write_text("\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "ScaledBorderAndShadow: yes",
        "WrapStyle: 0", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Title,{FONT},{size},{ass_colour(c['text_color'])},&H000000FF,{ass_colour(c['box_color'])},"
        f"&H64000000,-1,0,0,0,100,100,0,0,1,6,4,{align},{ml},{mr},{mv},-1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,0:00:00.00,0:00:10.00,Title,,0,0,0,,{text}", ""]), encoding="utf-8-sig")


def render(s, cam, t, box, place, title, lang, out, brand):
    """One thumbnail: crop + scale to 1280x720, a dark fade where the title goes, the title, the logo -> JPG."""
    x, y, cw, ch = box
    ass = s / "tmp" / f"{Path(out).stem}.ass"
    ass.parent.mkdir(exist_ok=True)
    ass_title(ass, title, place, lang == "ar", brand)
    side, free = place
    ramp = {"right": f"(X-({W - free}-0.12*W))/(0.2*W)", "left": f"(({free}+0.12*W)-X)/(0.2*W)",
            "bottom": "(Y-0.5*H)/(0.3*H)"}[side]
    graph = [f"[0:v]crop={cw}:{ch}:{x}:{y},scale={W}:{H}:flags=lanczos,setsar=1,format=rgba[pic]",
             f"color=black:s={W}x{H},format=rgba,geq=r=0:g=0:b=0:a='200*clip({ramp},0,1)'[fade]",
             f"[pic][fade]overlay,subtitles=tmp/{ass.name}[t]"]
    inputs, last = ["-ss", f"{t:.3f}", "-i", f"video/cam{cam}.mp4"], "t"
    if brand["logo"]:
        inputs += ["-i", brand["logo"]]
        scale, over = logo_overlay(brand, 1, W, "v")
        graph.append(scale + "[t][logo]" + over)
        last = "v"
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(graph), "-map", f"[{last}]", "-frames:v", "1",
         "-q:v", "2", out], cwd=s)
    ass.unlink(missing_ok=True)


def make_thumbnails(session_dir, count=3, highlights=None):
    """thumbnails/thumb_<n>_<lang>.jpg for the first `count` highlights (both languages) + thumbnails.json
    [{n, highlight, t, cam, files: {ar, en}}]. highlights = the highlights.json items (read from the file if None).
    Returns that list."""
    import pandas as pd
    s = Path(session_dir)
    hl = highlights if highlights is not None else \
        read_json(s / "highlights.json") if (s / "highlights.json").exists() else []
    if not hl:
        raise ValueError("no highlights yet: thumbnails use the highlights' moments and titles")
    feats = pd.read_parquet(s / "features.parquet")
    laugh = {e["t"]: e.get("laugh", 0.0) for e in read_json(s / "audio_events.json")} \
        if (s / "audio_events.json").exists() else {}
    spk_cam = read_json(s / "speaker_map.json") if (s / "speaker_map.json").exists() else {}
    brand = load_brand(s)
    faces = Faces()
    (s / "thumbnails").mkdir(exist_ok=True)
    items = []
    for n, h in enumerate(hl[:count], 1):
        cands = candidates(s, h["start"], h["end"], feats, laugh, spk_cam)
        if not cands:
            continue
        best = None
        for score, t, cam, fx in cands:
            img = frame_at(s, cam, t)
            hh, ww = img.shape[:2]
            seen = faces.look(img, fx) if faces.ok else None
            if seen:
                cx, cy, side, expr = seen
                total = expr + 0.3 * score
            else:                                              # the simple crop: the face from features.parquet
                area = float(feats[(feats.cam == cam) & (feats.t == t)].face_area.iloc[0])
                cx, cy, side, total = fx * ww, 0.4 * hh, (area * ww * hh) ** 0.5 * 2.4, score
            if best is None or total > best[0]:
                best = (total, t, cam, crop_box(cx, cy, side, ww, hh))
        _, t, cam, (box, place) = best
        files = {}
        for lang in ("ar", "en"):
            title = (h.get(f"title_{lang}") or h.get("title_en") or h.get("title_ar") or "").strip()
            out = f"thumbnails/thumb_{n}_{lang}.jpg"
            render(s, cam, t, box, place, title, lang, out, brand)
            files[lang] = out
        items.append({"n": n, "highlight": h["id"], "t": round(t, 2), "cam": cam, "files": files})
        print(f"  thumbnail {n}: {h['id']} at {t:.1f} s, camera {cam}")
    write_json(s / "thumbnails.json", items)
    return items


if __name__ == "__main__":
    print(make_thumbnails(session_from_argv()))
