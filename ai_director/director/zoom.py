from pathlib import Path

import yaml

from ai_director.common.io import read_json
from ai_director.common.paths import CONFIGS

CFG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8")).get("zoom") or {"enabled": False}
FPS = 30
FACE_Y = 0.42          # faces sit in the upper half of our close-ups (features have no face height): push in there


def loudness_z(events):
    """{second: how much louder than usual (z-score, the same as the highlights' interest curve)}."""
    import numpy as np
    db = np.array([e["loudness_db"] for e in events], dtype=float)
    std = db.std() or 1.0
    return {e["t"]: (x - db.mean()) / std for e, x in zip(events, db)}


def zoom_plan(session_dir, cuts, cfg=None):
    """{shot index: {"t0": edit time the push starts, "x": face x 0..1, "why": "laughter" | "strong"}}."""
    cfg = cfg or CFG
    s = Path(session_dir)
    if not cfg.get("enabled") or not cuts or not (s / "audio_events.json").exists():
        return {}
    meta = read_json(s / "session.json")
    roles = {c["id"]: c["role"] for c in meta["cameras"]}
    events = read_json(s / "audio_events.json")
    laugh = {e["t"]: e.get("laugh", 0.0) for e in events}
    loud = loudness_z(events)
    feats = None
    if (s / "features.parquet").exists():
        import pandas as pd
        feats = pd.read_parquet(s / "features.parquet", columns=["t", "cam", "face_area", "face_x"])
    found = []
    for i, c in enumerate(cuts):
        if c.get("split") or roles.get(c["cam"]) != "closeup" or c["end"] - c["start"] < cfg["min_shot"]:
            continue
        secs = range(int(c["start"]) + 1, int(c["end"] - 1) + 1)      # whole seconds inside the shot (not the edges)
        best = None
        for t in secs:
            lg = laugh.get(t, 0.0)
            ld = sum(loud.get(k, 0.0) for k in (t - 1, t, t + 1)) / 3       # 3-second average: not one loud word
            if lg >= cfg["laugh"]:
                score, why = 2 + lg, "laughter"
            elif ld >= cfg["loud"]:
                score, why = ld / cfg["loud"], "strong"
            else:
                continue
            if best is None or score > best[0]:
                best = (score, t, why)
        if best:
            t0 = max(c["start"], best[1] - 1.0)                              # the push starts ~1 s before the moment
            if c["end"] - t0 < 2.0:
                t0 = max(c["start"], c["end"] - 2.0)
            x = 0.5
            if feats is not None:
                f = feats[(feats.cam == c["cam"]) & feats.t.between(c["start"], c["end"]) & (feats.face_area > 0)]
                if len(f):
                    x = round(float(f.face_x.median()), 3)
            found.append((best[0], i, {"t0": round(t0, 2), "x": x, "why": best[2]}))
    limit = max(1, int(meta["duration"] / 60 * cfg["per_minute"]))
    plan = {}
    for _, i, z in sorted(found, key=lambda f: -f[0]):                       # the strongest first
        if len(plan) >= limit:
            break
        if all(abs(z["t0"] - p["t0"]) >= cfg["min_gap"] for p in plan.values()):
            plan[i] = z
    return dict(sorted(plan.items()))


def zoom_filter(z, start, w, h, cfg=None):
    """The perspective filter for one piece of a zoomed shot that starts at edit time `start` (frame 0 of the piece):
    1.0 until z["t0"], then a smooth push to zoom.scale over zoom.seconds s, then it holds. Centred on the face."""
    cfg = cfg or CFG
    p = f"clip(({start:.3f}+in/{FPS}-{z['t0']:.3f})/{cfg['seconds']:.3f},0,1)"
    k = f"(1+{cfg['scale'] - 1:.4f}*({p})*({p})*(3-2*({p})))"                # smoothstep: starts and ends gently
    vw, vh = f"({w}/{k})", f"({h}/{k})"                                       # the part of the picture shown
    x = f"clip({z['x'] * w:.1f}-{vw}/2,0,{w}-{vw})"
    y = f"clip({FACE_Y * h:.1f}-{vh}/2,0,{h}-{vh})"
    corners = {"x0": x, "y0": y, "x1": f"{x}+{vw}", "y1": y, "x2": x, "y2": f"{y}+{vh}", "x3": f"{x}+{vw}",
               "y3": f"{y}+{vh}"}
    return "perspective=" + ":".join(f"{n}='{v}'" for n, v in corners.items()) + ":interpolation=cubic:eval=frame"
