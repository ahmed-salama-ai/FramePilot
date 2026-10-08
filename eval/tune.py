# eval/tune.py — Day 11: try a few director settings on the TUNING sessions (they need labels.csv) and print the best.
#   python -m eval.tune
# Sessions: configs eval.tuning_sessions (s01, s02). The test session (s03) is never used here: its numbers must come
# from settings that never saw it. Nothing is changed: copy the best values into configs/default.yaml yourself, run
# the Switching + Render stages again, then  python -m eval.run  on every session.
# Owner: Ahmed Salama
import itertools
import sys
from contextlib import contextmanager

import numpy as np
import pandas as pd

import ai_director.director.run as director
import ai_director.director.scorer as scorer
from ai_director.common.paths import SESSIONS

from .director_eval import CFG, edit_scores, speaking_cams

GRID = {"speaker": [2.0, 3.0, 4.0],       # scorer weight: how much "this camera shows the person talking" counts
        "margin": [0.1, 0.2, 0.3],        # switcher: how much better a camera must be ...
        "hold": [0.2, 0.4, 0.8],          # ... and for how long, before a cut
        "min_shot": [1.5, 2.0, 3.0]}      # switcher: the shortest shot


@contextmanager
def settings(values):
    """Use other weights / rules for a moment, then put the old ones back (configs/default.yaml is not touched)."""
    old_w, old_r = dict(scorer.W), dict(director.RULES)
    for k, v in values.items():
        (scorer.W if k in scorer.W else director.RULES)[k] = v
    try:
        yield
    finally:
        scorer.W.clear(); scorer.W.update(old_w)
        director.RULES.clear(); director.RULES.update(old_r)


def try_setting(sessions, values):
    """The director with these settings on every session, compared with its labels.csv: the mean numbers."""
    with settings(values):
        rows = []
        for s in sessions:
            labels = pd.read_csv(s / "labels.csv")
            cuts, _ = director.decide(s)
            rows.append(edit_scores(cuts, labels.t.values, speaking_cams(s, labels.t.values), labels.cam.values))
    mean = lambda k: round(float(np.mean([r[k] for r in rows if r[k] is not None])), 3)
    return {"agreement": mean("agreement"), "speaker_coverage": mean("speaker_coverage"),
            "short_cuts": sum(r["short_cuts"] for r in rows), "avg_shot": mean("avg_shot")}


def tune(sessions, grid=GRID):
    """Every combination of the grid (3 x 3 x 3 x 3 = 81), best first: highest agreement, then fewest short cuts."""
    out = [(dict(zip(grid, combo)), try_setting(sessions, dict(zip(grid, combo))))
           for combo in itertools.product(*grid.values())]
    return sorted(out, key=lambda x: (-x[1]["agreement"], x[1]["short_cuts"]))


if __name__ == "__main__":
    names = [n for n in CFG["tuning_sessions"] if n != CFG["test_session"]]
    sessions = [SESSIONS / n for n in names if (SESSIONS / n / "labels.csv").exists()]
    if not sessions:
        sys.exit(f"No labels.csv in {names} yet: label them with the web app's labelling tool first")
    now = {k: scorer.W.get(k, director.RULES.get(k)) for k in GRID}
    print(f"tuning on {[s.name for s in sessions]}; now: {now} -> {try_setting(sessions, now)}")
    ranked = tune(sessions)
    for values, r in ranked[:10]:
        print(f"  {values}  agreement {100 * r['agreement']:.1f}%  speaker coverage {100 * r['speaker_coverage']:.1f}%"
              f"  cuts < 1 s {r['short_cuts']}  average shot {r['avg_shot']:.1f} s")
    print("\nBest -> configs/default.yaml:", ranked[0][0])
