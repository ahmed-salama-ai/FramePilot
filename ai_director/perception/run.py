# ai_director/perception/run.py — stage ②: every camera, 10 times per second -> features.parquet + speaker_map.json
#   python -m ai_director.perception.run data/sessions/s01        full run (writes the files)
#   python -m ai_director.perception.run data/sessions/s01 20     quick test: first 20 s only, prints, saves nothing
# Owner: Sara Walid (taken over by Ahmed Salama)
import sys
import time

import cv2
import pandas as pd
from ultralytics import YOLO

from ..common.io import read_json, session_from_argv, write_json
from ..common.paths import ROOT
from ..common.schemas import FEATURE_COLUMNS
from .faces import faces, open_landmarker
from .people import people
from .quality import quality
from .speaker import add_speaker_prob, speaker_map

YOLO_MODEL = ROOT / "data" / "models" / "yolo11s.pt"   # downloaded there automatically the first time (19 MB)


def process_camera(path, cam, fps=30, seconds=None):
    """One camera video -> one row every 0.1 s (every 3rd frame at 30 fps)."""
    step = round(fps / 10)
    yolo, lm = YOLO(str(YOLO_MODEL)), open_landmarker()    # new models per camera = its own tracker + timestamps
    cap = cv2.VideoCapture(str(path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    rows, prev_gray, mouth_hist, prev_centers, i, t0 = [], None, [], {}, 0, time.time()
    while seconds is None or i < seconds * fps:
        if i % step:                                       # frames we skip: grab() is fast (no decoding)
            if not cap.grab():
                break
            i += 1
            continue
        ok, frame = cap.read()
        if not ok:
            break
        t = round(i / fps, 1)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        row = {"t": t, "cam": cam}
        row.update(people(yolo, frame, prev_centers))
        row.update(faces(lm, frame, t, mouth_hist))
        row.update(quality(gray, prev_gray))
        rows.append(row)
        prev_gray = gray
        i += 1
        if i % (60 * fps) == 1:                            # progress every minute of video
            print(f"    cam {cam}: {t / 60:4.1f} min done ({100 * i / max(total, 1):3.0f}%), "
                  f"{time.time() - t0:.0f} s so far")
    cap.release()
    lm.close()
    return rows


def main(s, seconds=None):
    meta = read_json(s / "session.json")
    cams = [c["id"] for c in meta["cameras"]]
    rows = []
    for c in cams:
        t0 = time.time()
        print(f"  camera {c} ...")
        rows += process_camera(s / f"video/cam{c}_640.mp4", c, meta["fps"], seconds)
        print(f"  camera {c} done in {time.time() - t0:.0f} s")
    df = pd.DataFrame(rows)
    add_speaker_prob(s, df)
    spk_map = speaker_map(s, df)
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
