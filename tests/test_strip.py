# tests/test_strip.py — 9:16 clips on a camera with two people: the strip moves to the one who talks (2026-10-09)
import shutil

import numpy as np
import pandas as pd

from ai_director.common.io import write_json
from ai_director.common.paths import MOCK
from ai_director.director.render import render_clip
from ai_director.highlights.clips import people_x, strip_shots, vertical_source
from ai_director.ingest.probe import probe

# camera 2 = two people far apart (A on the left at 0.2, B on the right at 0.8), camera 3 = C alone
DIAR = [{"start": 0.0, "end": 6.0, "speaker": "A"}, {"start": 6.5, "end": 12.0, "speaker": "B"},
        {"start": 12.2, "end": 12.8, "speaker": "A"},                                  # a quick "yes": no flash
        {"start": 13.0, "end": 20.0, "speaker": "B"}, {"start": 20.5, "end": 30.0, "speaker": "C"}]


def session(tmp_path, near=False):
    """A tiny session: who talks when, who sits where; perception's face follows the talker on camera 2."""
    write_json(tmp_path / "diarization.json", DIAR)
    write_json(tmp_path / "speaker_map.json", {"A": 2, "B": 2, "C": 3})
    t = np.round(np.arange(0, 30, 0.1), 2)
    b = 0.35 if near else 0.8
    x2 = np.where([any(d["speaker"] == "B" and d["start"] <= v <= d["end"] for d in DIAR) for v in t], b, 0.2)
    feats = pd.DataFrame({"t": np.concatenate([t, t]), "cam": [2] * len(t) + [3] * len(t),
                          "face_area": 0.02, "face_x": np.concatenate([x2, np.full(len(t), 0.5)])})
    return feats


def test_where_each_person_sits(tmp_path):
    feats = session(tmp_path)
    assert people_x(tmp_path, feats) == {2: {"A": 0.2, "B": 0.8}, 3: {"C": 0.5}}


def test_strip_moves_to_whoever_talks(tmp_path):
    """s01 h3: the host and the man in grey both talk, but the strip stayed on the host. Now it cuts to the talker;
    the 0.6 s "yes" (< 2 s) makes no cut."""
    feats = session(tmp_path)
    shots = strip_shots(tmp_path, [{"start": 0.0, "end": 20.0, "cam": 2}], feats)
    assert [(c["start"], c["end"], c["crop_x"]) for c in shots] == [(0.0, 6.5, 0.2), (6.5, 20.0, 0.8)]


def test_strip_stays_when_asked_or_when_both_fit(tmp_path):
    feats = session(tmp_path)
    one = [{"start": 0.0, "end": 20.0, "cam": 2}]
    assert strip_shots(tmp_path, one, feats, keep={2: 0.2}) == [{**one[0], "crop_x": 0.2}]   # "show A": A only
    assert strip_shots(tmp_path, [{"start": 21.0, "end": 29.0, "cam": 2}], feats)[0]["crop_x"] == 0.2  # nobody on cam
    assert len(strip_shots(tmp_path, [{"start": 0.0, "end": 9.0, "cam": 3}], feats)) == 1             # one person
    near = session(tmp_path, near=True)                                    # 0.2 and 0.35: both fit in one strip
    assert len(strip_shots(tmp_path, one, near)) == 1


def test_vertical_highlight_follows_the_talker(tmp_path):
    feats = session(tmp_path)
    source, crop = vertical_source(tmp_path, 0.0, 20.0, [], feats)          # B talks most -> camera 2, 2 shots
    assert crop is None and [(c["cam"], c["crop_x"]) for c in source] == [(2, 0.2), (2, 0.8)]
    assert vertical_source(tmp_path, 21.0, 29.0, [], feats) == (3, 0.5)     # one person: as before


def test_render_two_strips_from_one_camera(tmp_path):
    """One camera, two crops in one clip: 9:16, the right length."""
    shutil.copytree(MOCK / "video", tmp_path / "video")
    for f in ("session.json", "transcript.json"):
        shutil.copy(MOCK / f, tmp_path)
    shots = [{"start": 10.0, "end": 13.0, "cam": 2, "crop_x": 0.1}, {"start": 13.0, "end": 16.0, "cam": 2, "crop_x": 0.9}]
    info = probe(render_clip(tmp_path, 10.0, 16.0, "clips/t.mp4", fmt="9:16", source=shots, langs="none"))
    assert (info["width"], info["height"]) == (720, 1280) and abs(info["duration"] - 6.0) < 0.15
