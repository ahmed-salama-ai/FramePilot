# ai_director/director/baselines.py — two "dumb" editors that the AI must beat
#   python -m ai_director.director.baselines data/sessions/s01
import random

from ai_director.common.io import read_json, session_from_argv, write_json


def random_cuts(duration, cams, seed=0, shortest=2.0, longest=8.0):
    """A random camera every 2-8 s (never the same camera twice in a row)."""
    rng = random.Random(seed)                           # same seed -> same "random" edit every time
    cuts, t, cam = [], 0.0, rng.choice(cams)
    while t < duration:
        end = min(round(t + rng.uniform(shortest, longest), 1), duration)
        cuts.append({"start": t, "end": end, "cam": cam})
        t, cam = end, rng.choice([c for c in cams if c != cam])
    return cuts


def wide_cuts(duration, wide_cam):
    """The whole video on the wide shot: one single segment."""
    return [{"start": 0.0, "end": duration, "cam": wide_cam}]


if __name__ == "__main__":
    s = session_from_argv()
    meta = read_json(s / "session.json")
    cams = [c["id"] for c in meta["cameras"]]
    wide = next(c["id"] for c in meta["cameras"] if c["role"] == "wide")
    write_json(s / "cuts_random.json", random_cuts(meta["duration"], cams))
    write_json(s / "cuts_wide.json", wide_cuts(meta["duration"], wide))
    print("done:", s / "cuts_random.json", "and", s / "cuts_wide.json")