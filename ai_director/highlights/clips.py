# ai_director/highlights/clips.py — every chosen moment as two clips: 16:9 (YouTube) and 9:16 (TikTok / Reels)
# Owner: Sara Walid (taken over by Ahmed Salama)
import numpy as np
import pandas as pd

from ..common.io import read_json
from ..director.render import render_clip                            # Ahmed Salama (Day 8)


def vertical_source(s, a, b, cuts, feats):
    """Where the 9:16 clip comes from and where to crop it (crop_x = face position 0..1).
    The guide crops the AI edit at ONE position, but the edit switches between cameras whose faces are in different
    places (Day 8: one face ends at the edge). So: the close-up camera of the person who talks most in the clip,
    cropped on that camera's face. If that person is not in a close-up -> the AI edit at the guide's position."""
    spk_map = read_json(s / "speaker_map.json") if (s / "speaker_map.json").exists() else {}
    talk = {}
    for d in read_json(s / "diarization.json"):
        o = min(b, d["end"]) - max(a, d["start"])
        if o > 0:
            talk[d["speaker"]] = talk.get(d["speaker"], 0) + o
    cam = spk_map.get(max(talk, key=talk.get)) if talk else None
    face = lambda c, x0, x1: feats[(feats.cam == c) & feats.t.between(x0, x1) & (feats.face_area > 0)].face_x
    if cam is not None and len(face(cam, a, b)):
        return cam, round(float(face(cam, a, b).median()), 3)
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
        print(f"  {hid}: {a:.1f}-{b:.1f} s  9:16 from {source} (crop_x {crop_x})  {titles['title_en'][:50]}",
              flush=True)
    return items
