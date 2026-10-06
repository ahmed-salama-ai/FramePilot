# ai_director/perception/debug_video.py — draw the numbers on each camera video, to SEE if perception is right
#   python -m ai_director.perception.debug_video data/sessions/s01        -> debug/cam1_debug.mp4, ...
# Owner: Sara Walid (taken over by Ahmed Salama)
import cv2
import pandas as pd

from ..common.io import read_json, session_from_argv

FONT = cv2.FONT_HERSHEY_SIMPLEX


def debug_video(s, cam, fps=30):
    df = pd.read_parquet(s / "features.parquet")
    rows = df[df.cam == cam].set_index("t")
    cap = cv2.VideoCapture(str(s / f"video/cam{cam}_640.mp4"))
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    (s / "debug").mkdir(exist_ok=True)
    out = cv2.VideoWriter(str(s / f"debug/cam{cam}_debug.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        r = rows.loc[min(round(i / fps, 1), rows.index.max())]          # the row of this moment
        cv2.rectangle(frame, (10, h - 20), (10 + int(200 * r.speaker_prob), h - 8), (0, 200, 0), -1)  # green bar
        cv2.rectangle(frame, (10, h - 20), (210, h - 8), (255, 255, 255), 1)
        if r.speaker_prob > 0.5:
            cv2.putText(frame, "SPEAKING", (10, 30), FONT, 1, (0, 0, 255), 2)
        cv2.putText(frame, f"cam {cam}  t={i / fps:5.1f}  people={int(r.num_people)}  face={r.face_area:.3f}  "
                           f"front={r.frontalness:.2f}  sharp={r.sharpness:.2f}  shake={r.shake:.2f}",
                    (10, h - 28), FONT, 0.4, (255, 255, 255), 1)
        out.write(frame)
        i += 1
    cap.release()
    out.release()


if __name__ == "__main__":
    s = session_from_argv()
    meta = read_json(s / "session.json")
    for c in meta["cameras"]:
        print(f"  camera {c['id']} ...")
        debug_video(s, c["id"], meta["fps"])
    print("  done: open the files in the debug/ folder (VLC plays them)")
