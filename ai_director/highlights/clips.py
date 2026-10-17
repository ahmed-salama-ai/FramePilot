import numpy as np
import pandas as pd

from ..common.io import read_json
from ..director.render import render_clip
from ..director.run import RULES

FIT = 0.25


def people_x(s, feats):
    """Where each person sits on their close-up camera (0..1)"""
    spk_map = read_json(s / "speaker_map.json") if (s / "speaker_map.json").exists() else {}
    if not spk_map or not (s / "diarization.json").exists():
        return {}
    f = feats[feats.face_area > 0]
    out = {}
    for spk, cam in spk_map.items():
        rows = f[f.cam == cam]
        own = np.zeros(len(rows), bool)
        for d in read_json(s / "diarization.json"):
            if d["speaker"] == spk:
                own |= rows.t.between(d["start"], d["end"]).to_numpy()
        if own.sum() >= 20:
            out.setdefault(cam, {})[spk] = round(float(rows.face_x[own].median()), 3)
    return out


def strip_shots(s, shots, feats, keep=None):
    pos, diar = people_x(s, feats), read_json(s / "diarization.json") if (s / "diarization.json").exists() else []
    out = []
    for sh in shots:
        cam, a, b = sh["cam"], sh["start"], sh["end"]
        who = pos.get(cam, {})
        if keep and cam in keep:
            out.append({**sh, "crop_x": keep[cam]})
            continue
        if len(who) < 2 or max(who.values()) - min(who.values()) < FIT:     # one person, or both fit in the strip
            x = feats[(feats.cam == cam) & feats.t.between(a, b) & (feats.face_area > 0)].face_x
            out.append({**sh, "crop_x": round(float(x.median()), 3) if len(x) else None})
            continue
        talks = sorted((max(d["start"], a), d["speaker"]) for d in diar
                       if d["speaker"] in who and d["end"] > a and d["start"] < b)
        if talks:
            first = talks[0][1]
        else:                                                                # nobody there talks: whoever is seen
            x = feats[(feats.cam == cam) & feats.t.between(a, b) & (feats.face_area > 0)].face_x
            first = min(who, key=lambda p: abs(who[p] - (x.median() if len(x) else 0.5)))
        pieces = [[a, first]]                                                # [start, person]
        for t, spk in talks:
            if spk != pieces[-1][1]:
                pieces.append([t, spk])
        changed = True
        while changed and len(pieces) > 1:                                   # a piece < min_shot joins the one before
            changed = False
            ends = [p[0] for p in pieces[1:]] + [b]
            for i, (p, e) in enumerate(zip(pieces, ends)):
                if e - p[0] < RULES["min_shot"]:
                    if i == 0:
                        pieces[1][0] = a                                     # the first one: the next starts at a
                    pieces.pop(i)
                    changed = True
                    break
            pieces = [p for k, p in enumerate(pieces) if k == 0 or p[1] != pieces[k - 1][1]]   # same person twice
        ends = [p[0] for p in pieces[1:]] + [b]
        out += [{**sh, "start": round(p[0], 3), "end": round(e, 3), "crop_x": who[p[1]]} for p, e in zip(pieces, ends)]
    return out


def vertical_source(s, a, b, cuts, feats):
    """Where the 9:16 clip comes from and where to crop it (crop_x = face position 0..1).
    The guide crops the AI edit at ONE position, but the edit switches between cameras whose faces are in different
    places (Day 8: one face ends at the edge). So: the close-up camera of the person who talks most in the clip,
    cropped on that camera's face; on a camera with two people the strip moves to the one who talks (strip_shots)
    -> source = a shot list (each shot has its own crop_x), crop_x = None. If that person is not in a close-up ->
    the AI edit at the guide's position (with a split screen in it: the AI edit's shots, each from its main camera)."""
    spk_map = read_json(s / "speaker_map.json") if (s / "speaker_map.json").exists() else {}
    talk = {}
    for d in read_json(s / "diarization.json"):
        o = min(b, d["end"]) - max(a, d["start"])
        if o > 0:
            talk[d["speaker"]] = talk.get(d["speaker"], 0) + o
    cam = spk_map.get(max(talk, key=talk.get)) if talk else None
    face = lambda c, x0, x1: feats[(feats.cam == c) & feats.t.between(x0, x1) & (feats.face_area > 0)].face_x
    if cam is not None and len(face(cam, a, b)):
        shots = strip_shots(s, [{"start": a, "end": b, "cam": cam}], feats)
        return (cam, shots[0]["crop_x"]) if len(shots) == 1 else (shots, None)
    inside = [c for c in cuts if c["end"] > a and c["start"] < b]
    if any(c.get("split") for c in inside):
        shots = [{"start": round(max(c["start"], a), 3), "end": round(min(c["end"], b), 3), "cam": c["cam"]}
                 for c in inside]                  # every shot from its own (main) camera, cropped on its face
        return strip_shots(s, shots, feats), None
    xs = [face(c["cam"], max(c["start"], a), min(c["end"], b)).median() for c in cuts
          if c["end"] > a and c["start"] < b]                         # the guide's way: on-air cameras, median
    x = float(np.nanmedian(xs)) if xs and not np.all(np.isnan(xs)) else 0.5
    return "program", round(x, 3)


def make_clips(s, chosen):
    """[(candidate, titles), ...] -> highlights.json items, with the two clip files rendered."""
    cuts = read_json(s / "cuts.json")
    feats = pd.read_parquet(s / "features.parquet") if (s / "features.parquet").exists() else pd.DataFrame(
        columns=["t", "cam", "face_area", "face_x"])
    items = []
    for n, (c, titles) in enumerate(chosen, 1):
        hid, a, b = f"h{n}", c["start"], c["end"]
        source, crop_x = vertical_source(s, a, b, cuts, feats)
        render_clip(s, a, b, f"highlights/{hid}_169.mp4", fmt="16:9")
        render_clip(s, a, b, f"highlights/{hid}_916.mp4", fmt="9:16", source=source, crop_x=crop_x)
        items.append({"id": hid, "start": a, "end": b, **titles,
                      "files": {"16:9": f"highlights/{hid}_169.mp4", "9:16": f"highlights/{hid}_916.mp4"}})
        src = f"{len(source)} shots" if isinstance(source, list) else source
        print(f"  {hid}: {a:.1f}-{b:.1f} s  9:16 from {src} (crop_x {crop_x})  {titles['title_en'][:50]}",
              flush=True)
    return items


def remake_clips(s):
    if not (s / "highlights.json").exists():
        return []
    items = read_json(s / "highlights.json")
    return make_clips(s, [({"start": h["start"], "end": h["end"]},
                           {"title_ar": h["title_ar"], "title_en": h["title_en"], "hook": h["hook"]}) for h in items])
