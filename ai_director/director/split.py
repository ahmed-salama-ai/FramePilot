# ai_director/director/split.py — split screen: the two close-ups side by side (16:9 only), SOMETIMES (2026-10-09)
# Rule A, fast back-and-forth: the person on one close-up and the person on the other take turns quickly.
# Rule B, the listener reacts: someone on a close-up talks while there is laughter / the AI Brain sees a reaction.
# A split shot is a normal cuts.json shot with 2 extra fields: {"start", "end", "cam": the main camera,
# "split": [left cam, right cam], "split_x": [face position of each, 0..1]} -> older readers just see "cam".
# Owner: Ahmed Salama. Tested 2026-10-09 on s01-s03 against hand labels (transcript lines + frames): turns <= 5 s +
# the mouth check = 12/16 moments right, 13/13 real fast exchanges found; Rule B 4/4 right (s01 only).
import json

import numpy as np
import pandas as pd
import yaml

from ai_director.common.io import read_json
from ai_director.common.paths import CONFIGS

CFG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["split"]
FACES = 0.5                     # both close-ups must show a face in at least half of the moment (nobody there: no split)


def cam_turns(diar, spk_map, pair):
    """The talk as camera turns: speech on the SAME close-up camera in a row is one turn (two people on one camera are
    one shot). A speaker on no close-up (or the wide camera) is a turn with cam None (it breaks a back-and-forth)."""
    out = []
    for d in sorted(diar, key=lambda d: d["start"]):
        cam = spk_map.get(d["speaker"])
        cam = cam if cam in pair else None
        if out and cam is not None and out[-1]["cam"] == cam and d["start"] - out[-1]["end"] <= CFG["max_gap"]:
            out[-1]["end"] = max(out[-1]["end"], d["end"])
        else:
            out.append({"cam": cam, "start": d["start"], "end": d["end"]})
    return out


def fast_talk(turns):
    """Rule A: runs of at least min_turns turns that switch camera every time, each turn <= turn_max s, pauses
    <= max_gap s, the run >= min_seconds long. -> [[turn, ...], ...]"""
    runs, cur = [], []

    def close():
        if len(cur) >= CFG["min_turns"] and cur[-1]["end"] - cur[0]["start"] >= CFG["min_seconds"]:
            runs.append(list(cur))
    for t in turns:
        ok = t["cam"] is not None and t["end"] - t["start"] <= CFG["turn_max"]
        if ok and cur and t["cam"] != cur[-1]["cam"] and t["start"] - cur[-1]["end"] <= CFG["max_gap"]:
            cur.append(t)
        else:
            close()
            cur = [t] if ok else []
    close()
    return runs


def mouth_agrees(feats, run, pair):
    """The mouth check (vision, independent of who the audio says talks): in most turns of >= 0.6 s the talker's
    camera shows more mouth movement than the other close-up. Catches wrong speaker labels (s01 405 s: 1 of 3)."""
    votes = []
    for t in run:
        if t["end"] - t["start"] < 0.6:
            continue
        m = {c: feats[(feats.cam == c) & feats.t.between(t["start"], t["end"])].mouth_motion.dropna() for c in pair}
        if all(len(x) for x in m.values()):
            other = pair[1] if t["cam"] == pair[0] else pair[0]
            votes.append(m[t["cam"]].mean() > m[other].mean())
    return not votes or sum(votes) > len(votes) / 2


def reactions(events, scene, diar, spk_map, pair):
    """Rule B: the seconds with laughter (audio >= split.laugh) or a scene line that says laughter / reaction, while a
    person on one of the close-ups talks -> [(start, end)], +-react_pad s, at least min_seconds long."""
    times = {e["t"] for e in events if e["laugh"] >= CFG["laugh"]}
    times |= {int(r["t"]) + k for r in scene if r.get("event") == "laughter" or r.get("raw_mode") == "reaction"
              for k in range(5)}                                             # a scene line = 5 s
    talk = [d for d in diar if spk_map.get(d["speaker"]) in pair]
    out = []
    for t in sorted(times):
        if not any(d["start"] <= t + 0.5 <= d["end"] for d in talk):
            continue
        if out and t - out[-1][1] <= 2:
            out[-1][1] = t + 1
        else:
            out.append([t, t + 1])
    pad, least = CFG["react_pad"], CFG["min_seconds"]
    res = []
    for a, b in out:
        a, b = a - pad, b + pad
        if b - a < least:                                                    # too short: grow around the middle
            a, b = (a + b - least) / 2, (a + b + least) / 2
        res.append((a, b))
    return res


def face_at(feats, diar, spk_map, cam, a, b):
    """Where to crop camera `cam` in a..b (0..1): its face while ITS person talks (perception follows the talker on a
    camera with two people: s01 cam2 = host at 0.80 or the man in grey at 0.18), else its face over a..b, else 0.5."""
    rows = feats[(feats.cam == cam) & feats.t.between(a, b) & (feats.face_area > 0)]
    own = np.zeros(len(rows), bool)
    for d in diar:
        if spk_map.get(d["speaker"]) == cam and d["end"] > a and d["start"] < b:
            own |= rows.t.between(d["start"], d["end"]).to_numpy()
    x = rows.face_x[own] if own.any() else rows.face_x
    return round(float(x.median()), 3) if len(x) else 0.5


def split_moments(s):
    """Every split moment of a session: [{"start", "end", "cam", "split", "split_x", "why"}]. [] when splits are off,
    the session has no 2 close-up cameras or a file is missing (diarization, speaker_map, features)."""
    if not CFG["enabled"]:
        return []
    meta = read_json(s / "session.json")
    close = sorted(c["id"] for c in meta["cameras"] if c["role"] == "closeup")
    need = [s / "diarization.json", s / "speaker_map.json", s / "features.parquet"]
    if len(close) != 2 or not all(f.exists() for f in need):
        return []
    pair = CFG["order"] if sorted(CFG["order"] or []) == close else close   # left, right
    diar, spk_map = read_json(s / "diarization.json"), read_json(s / "speaker_map.json")
    feats = pd.read_parquet(s / "features.parquet", columns=["t", "cam", "face_area", "face_x", "mouth_motion"])
    found = [(r[0]["start"], r[-1]["end"], "fast talk") for r in fast_talk(cam_turns(diar, spk_map, pair))
             if not CFG["mouth_check"] or mouth_agrees(feats, r, pair)]
    events = read_json(s / "audio_events.json") if (s / "audio_events.json").exists() else []
    scene = ([json.loads(x) for x in (s / "scene.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
             if (s / "scene.jsonl").exists() else [])
    found += [(a, b, "reaction") for a, b in reactions(events, scene, diar, spk_map, pair)]
    joined = []
    for a, b, why in sorted(found):                                        # close moments become one (no flicker)
        if joined and a - joined[-1][1] < CFG["join_gap"]:
            joined[-1] = (joined[-1][0], max(joined[-1][1], b), joined[-1][2] if joined[-1][2] == why else "both")
        else:
            joined.append((a, b, why))
    out = []
    for a, b, why in joined:
        a, b = max(0.0, a), min(meta["duration"], b)
        seen = {c: (feats[(feats.cam == c) & feats.t.between(a, b)].face_area > 0).mean() for c in pair}
        if min(np.nan_to_num(list(seen.values()))) < FACES:
            continue                                                         # someone left the frame
        talk = {c: sum(max(0, min(b, d["end"]) - max(a, d["start"])) for d in diar if spk_map.get(d["speaker"]) == c)
                for c in pair}
        out.append({"start": round(a, 2), "end": round(b, 2), "cam": max(talk, key=talk.get), "split": list(pair),
                    "split_x": [face_at(feats, diar, spk_map, c, a, b) for c in pair], "why": why})
    return out


def add_splits(cuts, moments, min_shot):
    """The switcher's cut list with every split moment put in: the shots inside become one split shot; a piece of a
    shot shorter than min_shot left next to a split joins the split (no flash)."""
    out = [dict(c) for c in cuts]
    for m in moments:
        keep = []
        for c in out:
            if c["end"] <= m["start"] or c["start"] >= m["end"]:
                keep.append(c)
                continue
            if c["start"] < m["start"]:
                keep.append({**c, "end": m["start"]})
            if c["end"] > m["end"]:
                keep.append({**c, "start": m["end"]})
        shot = {k: m[k] for k in ("start", "end", "cam", "split", "split_x")}
        out = sorted(keep + [shot], key=lambda c: c["start"])
    for i, c in enumerate(out):                                              # short leftovers join the split
        if c.get("split"):
            continue
        near = [j for j in (i - 1, i + 1) if 0 <= j < len(out) and out[j].get("split")]
        if near and c["end"] - c["start"] < min_shot:
            j = near[0]
            out[j]["start"], out[j]["end"] = min(out[j]["start"], c["start"]), max(out[j]["end"], c["end"])
            c["gone"] = True
    out = [c for c in out if not c.get("gone")]
    merged = []
    for c in out:                                                            # the same camera twice in a row = 1 shot
        if merged and not c.get("split") and not merged[-1].get("split") and merged[-1]["cam"] == c["cam"]:
            merged[-1]["end"] = c["end"]
        else:
            merged.append(c)
    return [{**c, "start": round(c["start"], 2), "end": round(c["end"], 2)} for c in merged]
