# ai_director/director/scorer.py — one score per camera every 0.1 s (Architecture §5)
import pandas as pd
import yaml

from ai_director.common.io import read_json, session_from_argv
from ai_director.common.paths import CONFIGS

CFG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["scorer"]
MODES = yaml.safe_load((CONFIGS / "modes.yaml").read_text(encoding="utf-8"))
W = CFG["weights"]          # speaker 3.0, frontal 1.0, quality 0.8, gesture 0.5, shake 1.0


def load_modes(session_dir, times):
    """Mode at every time t, from scene.jsonl (default 'conversation')."""
    p = session_dir / "scene.jsonl"
    if not p.exists():
        return ["conversation"] * len(times)
    sc = pd.read_json(p, lines=True)[["t", "mode"]].sort_values("t")
    sc["t"] = sc["t"].astype(float)
    m = pd.merge_asof(pd.DataFrame({"t": times}), sc, on="t")
    return m["mode"].fillna("conversation").values


def score(session_dir, boost=None, force_mode=None):
    f = pd.read_parquet(session_dir / "features.parquet").sort_values(["t", "cam"]).reset_index(drop=True)
    roles = {c["id"]: c["role"] for c in read_json(session_dir / "session.json")["cameras"]}

    size = (f.face_area / CFG["face_full"]).clip(upper=1)
    someone = (f.num_people > 0) | (f.face_area > 0)
    size = size.clip(lower=CFG["no_face_size"]).where(someone, 0.0)   # someone on camera: at least a third, a big face more
    base = (W["speaker"] * f.speaker_prob * size
            + W["frontal"] * f.frontalness
            + W["quality"] * (0.6 * f.sharpness + 0.4 * f.exposure_ok)
            + W["gesture"] * f.gesture_score
            - W["shake"] * f.shake).clip(lower=0.01)

    f["mode"] = force_mode or load_modes(session_dir, f.t.values)
    mult = [MODES[m][roles[c]] for m, c in zip(f["mode"], f.cam)]
    f["score"] = base * mult

    if boost:                                   # used by the agent: {"cam": 3, "factor": 1.3}
        f.loc[f.cam == boost["cam"], "score"] *= boost["factor"]
    return f[["t", "cam", "score", "mode"]]


if __name__ == "__main__":      # python -m ai_director.director.scorer samples/mock_s00
    s = session_from_argv()
    df = score(s)
    print(df.head(6))
    print(df.groupby("cam").score.describe().round(2))