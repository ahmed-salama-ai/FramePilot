# eval/ab_test.py — Days 13-14: the A/B viewer test. Do people prefer the AI edit or the always-wide shot?
#   python -m eval.ab_test make data/sessions/s01    -> ab_test/pair1_A.mp4, pair1_B.mp4, ... + ab_test/key.json
#   python -m eval.ab_test score data/sessions/s01   -> reads ab_test/answers.csv (the Google Form answers)
# Put each pair in a Google Form ("Which one would you rather watch? A / B"), send it to 10+ people, download the
# answers, and save them as ab_test/answers.csv with one column per pair (pair1, pair2, pair3) holding A or B.
# The viewers must not know which one is the AI edit: key.json (the answer key) stays with us.
# Owner: Ahmed Salama
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ai_director.common.io import read_json, write_json
from ai_director.common.paths import CONFIGS
from ai_director.director.render import render_clip

CFG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["eval"]


def pick_windows(cuts, duration, n, length):
    """n moments of `length` seconds (not overlapping) where the AI edit cuts the most: where editing matters most."""
    starts = np.arange(0, max(duration - length, 0) + 0.01, 5.0)
    count = [sum(a < c["start"] < a + length for c in cuts) for a in starts]
    chosen = []
    for i in sorted(range(len(starts)), key=lambda i: (-count[i], starts[i])):
        if all(abs(starts[i] - b) >= length for b in chosen):
            chosen.append(round(float(starts[i]), 2))
        if len(chosen) == n:
            break
    return sorted(chosen)


def make(s, n=None, length=None, seed=7):
    """Render the pairs. In every pair, A or B (chosen at random) is the AI edit, the other the wide camera; both have
    the same sound and the same captions, so only the editing is different."""
    n, length = n or CFG["ab_pairs"], length or CFG["ab_seconds"]
    meta = read_json(s / "session.json")
    wide = next(c["id"] for c in meta["cameras"] if c["role"] == "wide")
    rng, key = random.Random(seed), []
    for k, a in enumerate(pick_windows(read_json(s / "cuts.json"), meta["duration"], n, length), 1):
        ai, b = rng.choice("AB"), round(min(a + length, meta["duration"]), 2)
        for side in "AB":
            render_clip(s, a, b, f"ab_test/pair{k}_{side}.mp4", source="program" if side == ai else wide)
        key.append({"pair": k, "start": a, "end": b, "ai": ai})
    write_json(s / "ab_test" / "key.json", key)
    return key


def score(s):
    """Share of the answers that chose the AI edit (all pairs together, and per pair)."""
    key = {f"pair{x['pair']}": x["ai"] for x in read_json(s / "ab_test" / "key.json")}
    ans = pd.read_csv(s / "ab_test" / "answers.csv")
    per_pair, votes = {}, []
    for col, ai in key.items():
        if col in ans:
            picks = ans[col].dropna().astype(str).str.strip().str.upper()
            hits = (picks == ai).tolist()
            per_pair[col] = round(sum(hits) / len(hits), 3) if hits else None
            votes += hits
    return {"prefer_ai": round(sum(votes) / len(votes), 3) if votes else None, "answers": len(votes),
            "people": len(ans), **per_pair}


if __name__ == "__main__":
    what, s = sys.argv[1], Path(sys.argv[2]).resolve()
    if what == "make":
        for x in make(s):
            print(f"  pair {x['pair']}: {x['start']}-{x['end']} s  (the AI edit is {x['ai']})")
        print("Put ab_test/pair*_A.mp4 and pair*_B.mp4 in the form. Keep ab_test/key.json to yourself.")
    else:
        r = score(s)
        print(f"{r['answers']} answers from {r['people']} people: {100 * r['prefer_ai']:.0f}% chose the AI edit")
