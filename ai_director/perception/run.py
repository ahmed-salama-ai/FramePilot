# ai_director/perception/run.py — stage ②: every camera, 10 times per second -> features.parquet + speaker_map.json
#   python -m ai_director.perception.run data/sessions/s01        full run (writes the files)
#   python -m ai_director.perception.run data/sessions/s01 20     quick test: first 20 s only, prints, saves nothing
# Owner: Sara Walid (taken over by Ahmed Salama; 2026-10-08: YOLO-pose, lift map, the transcript in speaker_prob.
# 2026-10-09: the cameras at the same time, faces from head crops, the map per person. Tested on s01-s03, see CLAUDE.md)
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import cv2
import pandas as pd
import yaml
from ultralytics import YOLO

from ..common.io import read_json, session_from_argv, write_json
from ..common.paths import CONFIGS, ROOT
from ..common.schemas import FEATURE_COLUMNS
from .faces import NO_FACE, faces, open_landmarker
from .people import people
from .quality import quality
from .speaker import add_speaker_prob, add_transcript_talk, follow_talker, person_map, speaker_map

CFG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["perception"]
POSE_MODEL = ROOT / "data" / "models" / "yolo11s-pose.pt"   # downloaded there automatically the first time (20 MB)
SMALL = 640              # people + picture quality on a 640 px copy (YOLO looks at 640 px anyway; quality is tuned for it)


def process_camera(path, cam, fps=30, seconds=None, find_faces=True):
    """One camera video (video/camN.mp4, 1080p) -> (one row every 0.1 s (every 3rd frame at 30 fps), one row per
    person every 0.1 s). Each frame is decoded once at full size: people and quality on a 640 px copy, faces on head
    crops cut from the FULL frame (the AI models only look at small pictures, so the 1080p detail is used by cutting
    the heads out first). find_faces=False: no faces (NO_FACE), e.g. the wide camera."""
    step = round(fps / 10)
    pose = YOLO(str(POSE_MODEL))                           # new models per camera = its own tracker
    lm = open_landmarker() if find_faces else None
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open {path}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    rows, persons, prev_gray, hists, prev_centers, i, t0 = [], [], None, {}, {}, 0, time.time()
    while seconds is None or i < seconds * fps:
        if i % step:                                       # frames we skip: grab() is fast (no picture made)
            if not cap.grab():
                break
            i += 1
            continue
        ok, frame = cap.read()
        if not ok:
            break
        t = round(i / fps, 1)
        small = cv2.resize(frame, (SMALL, round(SMALL * frame.shape[0] / frame.shape[1])), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        row = {"t": t, "cam": cam}
        numbers, found = people(pose, small, prev_centers)
        row.update(numbers)
        if lm:
            face, who = faces(lm, frame, found, frame.shape[1] / SMALL, hists)
            persons += [{"t": t, "cam": cam, **p} for p in who]
        else:
            face = dict(NO_FACE)
        row.update(face)
        row.update(quality(gray, prev_gray))
        rows.append(row)
        prev_gray = gray
        i += 1
        if i % (60 * fps) == 1:                            # progress every minute of video
            print(f"    cam {cam}: {t / 60:4.1f} min done ({100 * i / max(total, 1):3.0f}%), "
                  f"{time.time() - t0:.0f} s so far", flush=True)
    cap.release()
    if lm:
        lm.close()
    print(f"  camera {cam} done in {time.time() - t0:.0f} s", flush=True)
    return rows, persons


def main(s, seconds=None, workers=None):
    meta = read_json(s / "session.json")
    roles = {c["id"]: c["role"] for c in meta["cameras"]}
    jobs = [(s / f"video/cam{c}.mp4", c, meta["fps"], seconds, roles[c] in CFG["face_roles"]) for c in roles]
    workers = min(workers or CFG["workers"], len(jobs))
    t0 = time.time()
    print(f"  {len(jobs)} cameras, {workers} at the same time ...", flush=True)
    if workers > 1:                                        # each camera in its own process (own CPU core + GPU share)
        with ProcessPoolExecutor(workers) as ex:
            done = [f.result() for f in [ex.submit(process_camera, *j) for j in jobs]]
    else:
        done = [process_camera(*j) for j in jobs]
    print(f"  all cameras done in {time.time() - t0:.0f} s")
    df = pd.DataFrame([r for rows, _ in done for r in rows])
    persons = pd.DataFrame([p for _, ps in done for p in ps])
    who = person_map(s, persons)                           # speaker -> the person whose mouth moves when they talk
    follow_talker(s, df, persons, who)                     # two people on a camera: the face of the one who talks
    add_speaker_prob(s, df)                                # the mouth ...
    spk_map = speaker_map(s, df, who)                      # (speakers person_map doesn't know: camera-level lift)
    add_transcript_talk(s, df, spk_map)                    # ... or the transcript says this camera's person talks
    for k, v in who.items():
        print(f"  {k}: camera {v['cam']}, the person at x = {v['x']} (lift {v['lift']})")
    df = df[FEATURE_COLUMNS]                               # the contract columns, in the contract order
    if seconds:                                            # quick test: show, do not save
        pd.set_option("display.width", 200)
        print(df.groupby("cam").describe().T.round(3).to_string())
        print("speaker map (on these seconds only):", spk_map)
        return df
    df.to_parquet(s / "features.parquet", index=False)
    write_json(s / "speaker_map.json", spk_map)            # LAST: the "done" file of the perception stage
    print("  speaker_map.json:", spk_map)
    return df


if __name__ == "__main__":
    main(session_from_argv(), float(sys.argv[2]) if len(sys.argv) > 2 else None)
