# ai_director/highlights/interest.py — one "interest" number per second: loud + laughing + lively + many speaker changes
# Owner: Sara Walid (taken over by Ahmed Salama)
import numpy as np
import pandas as pd
import yaml

from ..common.io import read_json, read_jsonl
from ..common.paths import CONFIGS

CFG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["highlights"]


def interest_curve(s):
    """A table with one row per second: t, loud_z, laugh, energy, highlight, changes, interest."""
    ev = pd.DataFrame(read_json(s / "audio_events.json"))                # t, loudness_db, laugh (audio stage)
    ev["t"] = ev.t.astype(float)
    std = ev.loudness_db.std() or 1.0
    ev["loud_z"] = ((ev.loudness_db - ev.loudness_db.mean()) / std).clip(-2, 3)   # louder than usual = positive
    if (s / "scene.jsonl").exists():                                     # AI Brain (optional): every 5 s
        sc = pd.DataFrame(read_jsonl(s / "scene.jsonl"))[["t", "energy", "highlight"]]
        sc["t"] = sc.t.astype(float)
        ev = pd.merge_asof(ev.sort_values("t"), sc.sort_values("t"), on="t")      # the last scene line before t
    else:
        ev["energy"], ev["highlight"] = 0.0, False
    ev[["energy", "highlight"]] = ev[["energy", "highlight"]].fillna(0)
    starts = np.sort([d["start"] for d in read_json(s / "diarization.json")])     # a new speaker turn begins
    ev["changes"] = np.searchsorted(starts, ev.t, side="left") - np.searchsorted(starts, ev.t - 10, side="left")
    w = CFG["weights"]
    raw = (w["loud"] * ev.loud_z + w["laugh"] * ev.laugh + w["energy"] * ev.energy
           + w["highlight"] * ev.highlight.astype(float) + w["changes"] * ev.changes)
    ev["interest"] = raw.rolling(CFG["smooth_seconds"], center=True, min_periods=1).mean().round(4)
    return ev.reset_index(drop=True)
