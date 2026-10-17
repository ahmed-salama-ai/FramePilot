from pathlib import Path

import yaml

from ai_director.common.io import read_json
from ai_director.common.paths import CONFIGS

_ALL = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))
CFG = _ALL.get("pauses") or {"cut": False}
LAUGH = (_ALL.get("zoom") or {}).get("laugh", 0.25)     #laughing is not a pause
GRID = 0.1                                               #cut points on the 0.1 s grid of the cut list (3 frames)
MIN_PIECE = 1.0                                          #never leave a piece of a shot shorter than this (a flash)
NEAR = 2.0                                               #a camera change this close to a removed piece moves into it
WORTH = 0.3                                              #shorter savings are not worth a cut


def snap(t):
    return round(round(t / GRID) * GRID, 2)


def busy_spans(s):
    """Times when somebody talks or laughs"""
    s = Path(s)
    spans = []
    for name in ("diarization.json", "speech.json"):
        if (s / name).exists():
            spans += [(float(x["start"]), float(x["end"])) for x in read_json(s / name)]
    if (s / "audio_events.json").exists():
        spans += [(e["t"] - 0.5, e["t"] + 0.5) for e in read_json(s / "audio_events.json") if e.get("laugh", 0) >= LAUGH]
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def silences(s, min_pause=None):
    """[(start, end)] of every silence longer than min_pause between two busy spans"""
    min_pause = CFG.get("min_pause", 1.5) if min_pause is None else min_pause
    busy = busy_spans(s)
    return [(a[1], b[0]) for a, b in zip(busy, busy[1:]) if b[0] - a[1] > min_pause]


def fit_one(cuts, r0, r1):
    """The cut list with the camera change nearest to the removed"""
    changes = [k for k in range(1, len(cuts)) if r0 - NEAR <= cuts[k]["start"] <= r1 + NEAR]
    if not changes or any(r0 <= cuts[k]["start"] <= r1 for k in changes):
        return cuts
    k = min(changes, key=lambda k: abs(cuts[k]["start"] - (r0 + r1) / 2))
    m = snap((r0 + r1) / 2)
    if not cuts[k - 1]["start"] < m < cuts[k]["end"]:
        return cuts                                      # it would jump over another change
    out = [dict(c) for c in cuts]
    out[k - 1]["end"], out[k]["start"] = m, m
    return out


def fit_cuts(cuts, removed):
    """Every removed piece nearest camera change moved into it"""
    for r0, r1 in removed or []:
        cuts = fit_one(cuts, r0, r1)
    return cuts


def shot_at(cuts, t):
    c = next((c for c in cuts if c["start"] <= t < c["end"]), cuts[-1])
    return c["cam"], tuple(c.get("split") or ())


def pieces_ok(cuts, r0, r1):
    """No shot is left with a piece shorter than MIN_PIECE"""
    for c in cuts:
        if c["end"] <= r0 or c["start"] >= r1:
            continue
        for p in (r0 - c["start"], c["end"] - r1):
            if 0.001 < p < MIN_PIECE:
                return False
    return True


def plan_pauses(s, cuts, on=None, jump_cuts=None):
    """The pieces to remove from this cut list: [[start, end], ...] in time order. [] when pauses.cut is off.
    Each silence keeps about pauses.keep s (half before, half after the cut); the camera before the cut and after it
    must be different (hidden cut), unless jump_cuts; no shot is left with a piece shorter than 1 s."""
    on = CFG.get("cut", False) if on is None else on
    jump_cuts = CFG.get("jump_cuts", False) if jump_cuts is None else jump_cuts
    if not on or not cuts:
        return []
    keep = CFG.get("keep", 0.4)
    out, cur = [], cuts
    for g0, g1 in silences(s):
        lo, hi = snap(g0 + GRID), snap(g1 - GRID)          # the removed piece stays inside the silence
        r0, r1 = snap(g0 + keep / 2), snap(g1 - keep / 2)
        fitted = fit_one(cur, r0, r1)
        for c in fitted:                                   # a short leftover of a shot: shorten the removed piece
            if c["start"] < r0 < c["end"] and r0 - c["start"] < MIN_PIECE:
                r0 = snap(c["start"] + MIN_PIECE)
            if c["start"] < r1 < c["end"] and c["end"] - r1 < MIN_PIECE:
                r1 = snap(c["end"] - MIN_PIECE)
        if r1 - r0 < WORTH or r0 < lo or r1 > hi:
            continue
        fitted = fit_one(cur, r0, r1)
        if not pieces_ok(fitted, r0, r1):
            continue
        if shot_at(fitted, r0 - 0.05) == shot_at(fitted, r1 + 0.05) and not jump_cuts:
            continue                                       # the same camera on both sides: a visible jump
        out.append([r0, r1])
        cur = fitted
    return out


def out_time(t, removed):
    """Edit time -> time in the shortened video (a time inside a removed piece -> where that piece was)."""
    return t - sum(max(0.0, min(t, b) - a) for a, b in removed or [] if t > a)


def keep_parts(a, b, removed):
    """The parts of a..b that are not removed: [(start, end), ...]."""
    parts, cur = [], a
    for r0, r1 in sorted(removed or []):
        if r1 <= cur or r0 >= b:
            continue
        if r0 > cur:
            parts.append((cur, r0))
        cur = max(cur, r1)
    if cur < b:
        parts.append((cur, b))
    return [(round(x, 3), round(y, 3)) for x, y in parts if y - x > 0.001]


def saved_seconds(removed):
    return round(sum(b - a for a, b in removed or []), 2)
