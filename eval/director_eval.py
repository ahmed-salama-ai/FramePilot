# eval/director_eval.py — Day 10: how good is the AI edit? Compared with the human edit (labels.csv from the labelling
# tool) and two "dumb" editors (random cuts, always the wide shot). The main numbers of the results table.
#   python -m eval.director_eval data/sessions/s01
# Owner: Ahmed Salama
import numpy as np
import pandas as pd
import yaml

from ai_director.common.io import read_json, session_from_argv
from ai_director.common.paths import CONFIGS
from ai_director.director.baselines import random_cuts, wide_cuts
from ai_director.director.run import to_segments

CFG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["eval"]
STEP = 0.1


def on_air_at(cuts, times):
    """The camera on air at every time (binary search in the shot starts; the last shot also covers the very end)."""
    starts = np.array([c["start"] for c in cuts])
    cams = np.array([c["cam"] for c in cuts])
    i = np.searchsorted(starts, np.asarray(times, dtype=float) + 1e-9, side="right") - 1
    return cams[np.clip(i, 0, len(cuts) - 1)]


def second_cam_at(cuts, times):
    """Split screen (2026-10-09): the OTHER camera on screen at every time (-1 = no split): both people are seen."""
    starts = np.array([c["start"] for c in cuts])
    other = np.array([next((x for x in c["split"] if x != c["cam"]), -1) if c.get("split") else -1 for c in cuts])
    i = np.searchsorted(starts, np.asarray(times, dtype=float) + 1e-9, side="right") - 1
    return other[np.clip(i, 0, len(cuts) - 1)]


def speaking_cams(s, times):
    """For every time: the close-up camera of the person talking, or -1 (nobody talks, or that person has no
    close-up camera in speaker_map.json)."""
    spk_map = read_json(s / "speaker_map.json") if (s / "speaker_map.json").exists() else {}
    times, out = np.asarray(times, dtype=float), np.full(len(times), -1)
    for d in read_json(s / "diarization.json"):
        cam = spk_map.get(d["speaker"])
        if cam is not None:
            out[(times >= d["start"]) & (times < d["end"])] = cam
    return out


def edit_scores(cuts, times, speaking, human=None):
    """The 4 numbers of the results table for one edit (a cut list)."""
    shots = [c["end"] - c["start"] for c in cuts]
    on = on_air_at(cuts, times)
    seen = (on == speaking) | (second_cam_at(cuts, times) == speaking)    # a split screen shows both close-ups
    talking = speaking >= 0
    return {"agreement": round(float((on == human).mean()), 3) if human is not None else None,
            "speaker_coverage": round(float(seen[talking].mean()), 3) if talking.any() else None,
            "short_cuts": int(sum(x < CFG["short_cut"] for x in shots[:-1])),   # the last shot may end with the video
            "avg_shot": round(float(np.mean(shots)), 2),
            "shots": len(cuts)}


def average(scores):
    """The mean of several score dicts (the random baseline: 10 random edits)."""
    out = {}
    for k in scores[0]:
        vals = [x[k] for x in scores if x[k] is not None]
        out[k] = round(float(np.mean(vals)), 3) if vals else None
    out["short_cuts"], out["shots"] = round(out["short_cuts"]), round(out["shots"])
    return out


def evaluate_director(s):
    """{"ai": {...}, "random": {...}, "wide": {...}} (+ "human" when labels.csv exists).
    Without labels.csv, agreement is None (it needs the human edit); the other numbers are still measured."""
    meta = read_json(s / "session.json")
    dur, cams = meta["duration"], [c["id"] for c in meta["cameras"]]
    wide = next(c["id"] for c in meta["cameras"] if c["role"] == "wide")
    human = None
    if (s / "labels.csv").exists():
        labels = pd.read_csv(s / "labels.csv")                      # t, cam every 0.1 s (the human director)
        times, human = labels.t.values, labels.cam.values
    else:
        times = np.round(np.arange(0, dur, STEP), 2)
    speaking = speaking_cams(s, times)
    out = {"ai": edit_scores(read_json(s / "cuts.json"), times, speaking, human),
           "random": average([edit_scores(random_cuts(dur, cams, seed=k), times, speaking, human)
                              for k in range(CFG["random_seeds"])]),
           "wide": edit_scores(wide_cuts(dur, wide), times, speaking, human)}
    if human is not None:
        out["human"] = edit_scores(to_segments(list(zip(times, (int(c) for c in human)))), times, speaking, human)
    return out


if __name__ == "__main__":
    s = session_from_argv()
    res = evaluate_director(s)
    print(f"{'edit':8s} {'agreement':>10s} {'speaker cov.':>13s} {'cuts < 1 s':>11s} {'avg shot':>9s} {'shots':>6s}")
    for name, r in res.items():
        pct = lambda v: "-" if v is None else f"{100 * v:.1f}%"
        print(f"{name:8s} {pct(r['agreement']):>10s} {pct(r['speaker_coverage']):>13s} {r['short_cuts']:>11d} "
              f"{r['avg_shot']:>8.1f}s {r['shots']:>6d}")
    if "human" not in res:
        print("(agreement needs labels.csv: the human edit from the labelling tool)")
