import json

import numpy as np
import pandas as pd
import yaml

from ai_director.common.io import read_json
from ai_director.common.paths import CONFIGS

CFG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["split"]
FACES = 0.5                     #both close-ups must show a face in at least half of the moment (nobody there: no split)


def cam_turns(diar, spk_map, pair):
    """The talk as camera turns"""
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
    times = {e["t"] for e in events if e["laugh"] >= CFG["laugh"]}
    times |= {int(r["t"]) + k for r in scene if r.get("event") == "laughter" or r.get("raw_mode") == "reaction"
              for k in range(5)}
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
        if b - a < least:
            a, b = (a + b - least) / 2, (a + b + least) / 2
        res.append((a, b))
    return res


def face_at(feats, diar, spk_map, cam, a, b):
    rows = feats[(feats.cam == cam) & feats.t.between(a, b) & (feats.face_area > 0)]
    own = np.zeros(len(rows), bool)
    for d in diar:
        if spk_map.get(d["speaker"]) == cam and d["end"] > a and d["start"] < b:
            own |= rows.t.between(d["start"], d["end"]).to_numpy()
    x = rows.face_x[own] if own.any() else rows.face_x
    return round(float(x.median()), 3) if len(x) else 0.5


def split_moments(s):
    if not CFG["enabled"]:
        return []
    meta = read_json(s / "session.json")
    close = sorted(c["id"] for c in meta["cameras"] if c["role"] == "closeup")
    need = [s / "diarization.json", s / "speaker_map.json", s / "features.parquet"]
    if len(close) != 2 or not all(f.exists() for f in need):
        return []
    pair = CFG["order"] if sorted(CFG["order"] or []) == close else close
    diar, spk_map = read_json(s / "diarization.json"), read_json(s / "speaker_map.json")
    feats = pd.read_parquet(s / "features.parquet", columns=["t", "cam", "face_area", "face_x", "mouth_motion"])
    found = [(r[0]["start"], r[-1]["end"], "fast talk") for r in fast_talk(cam_turns(diar, spk_map, pair))
             if not CFG["mouth_check"] or mouth_agrees(feats, r, pair)]
    events = read_json(s / "audio_events.json") if (s / "audio_events.json").exists() else []
    scene = ([json.loads(x) for x in (s / "scene.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
             if (s / "scene.jsonl").exists() else [])
    found += [(a, b, "reaction") for a, b in reactions(events, scene, diar, spk_map, pair)]
    joined = []
    for a, b, why in sorted(found):
        if joined and a - joined[-1][1] < CFG["join_gap"]:
            joined[-1] = (joined[-1][0], max(joined[-1][1], b), joined[-1][2] if joined[-1][2] == why else "both")
        else:
            joined.append((a, b, why))
    out = []
    for a, b, why in joined:
        a, b = max(0.0, a), min(meta["duration"], b)
        seen = {c: (feats[(feats.cam == c) & feats.t.between(a, b)].face_area > 0).mean() for c in pair}
        if min(np.nan_to_num(list(seen.values()))) < FACES:
            continue
        talk = {c: sum(max(0, min(b, d["end"]) - max(a, d["start"])) for d in diar if spk_map.get(d["speaker"]) == c)
                for c in pair}
        out.append({"start": round(a, 2), "end": round(b, 2), "cam": max(talk, key=talk.get), "split": list(pair),
                    "split_x": [face_at(feats, diar, spk_map, c, a, b) for c in pair], "why": why})
    return out


def add_splits(cuts, moments, min_shot):
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
    for i, c in enumerate(out):
        if c.get("split"):
            continue
        near = [j for j in (i - 1, i + 1) if 0 <= j < len(out) and out[j].get("split")]
        if near and c["end"] - c["start"] < min_shot:
            j = near[0]
            out[j]["start"], out[j]["end"] = min(out[j]["start"], c["start"]), max(out[j]["end"], c["end"])
            c["gone"] = True
    out = [c for c in out if not c.get("gone")]
    merged = []
    for c in out:
        if merged and not c.get("split") and not merged[-1].get("split") and merged[-1]["cam"] == c["cam"]:
            merged[-1]["end"] = c["end"]
        else:
            merged.append(c)
    return [{**c, "start": round(c["start"], 2), "end": round(c["end"], 2)} for c in merged]
