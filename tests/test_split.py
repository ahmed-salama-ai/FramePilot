# tests/test_split.py — split screen (2026-10-09): when to split, how the cut list changes, how it is rendered
import shutil

import numpy as np
import pandas as pd

from ai_director.common.io import read_json, write_json
from ai_director.common.paths import MOCK
from ai_director.director import split as S
from ai_director.director.render import render_program
from ai_director.director.run import decide
from ai_director.highlights.clips import vertical_source
from ai_director.ingest.probe import probe
from eval.director_eval import edit_scores

MAP = {"A": 2, "B": 3, "C": 2, "W": 1}                      # A and C sit on camera 2, B on camera 3, W on the wide


def d(a, b, who):
    return {"start": a, "end": b, "speaker": who}


def test_fast_back_and_forth_is_found():
    """s01 7:53 "You are a failure" / "True, I am a failure": short turns switching camera = one moment. Two people on
    the same camera are one turn; a long turn or a pause ends the run; a person on no close-up breaks it."""
    diar = [d(10, 11, "A"), d(11.5, 13, "B"), d(13.2, 14, "C"), d(14.1, 15, "A"), d(15.5, 17, "B"),   # A+C = 1 turn
            d(17.5, 30, "A"),                                                                       # 12.5 s: too long
            d(31, 32, "B"), d(32.5, 33, "A"), d(36, 37, "B"), d(37.5, 38, "A")]                     # pause 3 s
    turns = S.cam_turns(diar, MAP, [3, 2])
    assert [(t["cam"], t["start"], t["end"]) for t in turns[:3]] == [(2, 10, 11), (3, 11.5, 13), (2, 13.2, 15)]
    runs = S.fast_talk(turns)
    assert [(r[0]["start"], r[-1]["end"], len(r)) for r in runs] == [(10, 17, 4)]
    assert S.fast_talk(S.cam_turns([d(10, 11, "A"), d(11.5, 13, "W"), d(13.5, 15, "B")], MAP, [3, 2])) == []


def test_mouth_check_drops_wrong_speaker_labels():
    """The audio says B talks, but camera 2's mouth moves more in most turns -> the labels are wrong here: no split."""
    t = np.round(np.arange(10, 17, 0.1), 2)
    feats = pd.DataFrame({"t": np.concatenate([t, t]), "cam": [2] * len(t) + [3] * len(t),
                          "mouth_motion": [0.8] * len(t) + [0.1] * len(t)})
    run = [{"cam": 2, "start": 10, "end": 12}, {"cam": 3, "start": 12, "end": 14}, {"cam": 2, "start": 14, "end": 16}]
    assert S.mouth_agrees(feats, run, [3, 2])                                         # 2 of 3 turns agree
    assert not S.mouth_agrees(feats, [{**r, "cam": 5 - r["cam"]} for r in run], [3, 2])   # 1 of 3


def test_reaction_while_someone_talks():
    """Rule B: laughter (audio or the AI Brain) while a close-up person talks; +-1 s, at least 4 s."""
    events = [{"t": t, "laugh": 0.9 if t in (20, 21) else 0.0} for t in range(60)]
    scene = [{"t": 45.0, "event": "talking", "raw_mode": "reaction"}]
    diar = [d(18, 25, "B"), d(46, 48, "A")]
    assert S.reactions(events, scene, diar, MAP, [3, 2]) == [(19.0, 23.0), (45.0, 49.0)]
    assert S.reactions(events, [], [d(30, 40, "B")], MAP, [3, 2]) == []                 # laughter in a pause: no split


def test_split_goes_into_the_cut_list():
    """The shots inside the moment become one split shot; a piece < 2 s next to it joins it; the rest is kept."""
    cuts = [{"start": 0.0, "end": 10.0, "cam": 1}, {"start": 10.0, "end": 21.0, "cam": 2},
            {"start": 21.0, "end": 30.0, "cam": 3}]
    m = {"start": 11.0, "end": 25.0, "cam": 3, "split": [3, 2], "split_x": [0.5, 0.8]}
    assert S.add_splits(cuts, [m], 2.0) == [
        {"start": 0.0, "end": 10.0, "cam": 1},
        {"start": 10.0, "end": 25.0, "cam": 3, "split": [3, 2], "split_x": [0.5, 0.8]},   # cam 2's 1 s piece joined
        {"start": 25.0, "end": 30.0, "cam": 3}]


def test_mock_gets_one_split_at_the_laugh():
    """The mock: everyone laughs at 35-40 s and the guest starts talking at 38 s -> a split 37-41 s (cam 3 | cam 2)."""
    m = S.split_moments(MOCK)
    assert [(x["start"], x["end"], x["split"], x["why"]) for x in m] == [(37.0, 41.0, [3, 2], "reaction")]
    cuts, _ = decide(MOCK)
    assert [c for c in cuts if c.get("split")][0]["start"] == 37.0
    assert all(a["end"] == b["start"] for a, b in zip(cuts, cuts[1:])) and cuts[-1]["end"] == 60.0


def test_split_is_rendered_side_by_side(tmp_path):
    """A split shot = two half-width strips joined, the same size as a camera, a dark line in the middle."""
    shutil.copytree(MOCK / "video", tmp_path / "video")
    shutil.copy(MOCK / "session.json", tmp_path)
    cuts = [{"start": 0.0, "end": 2.0, "cam": 1},
            {"start": 2.0, "end": 5.0, "cam": 3, "split": [3, 2], "split_x": [0.5, 0.9]}]
    info = probe(render_program(tmp_path, cuts))
    assert (info["width"], info["height"]) == (1280, 720) and abs(info["duration"] - 5.0) < 0.1
    import cv2
    cap = cv2.VideoCapture(str(tmp_path / "program_nocaps.mp4"))
    cap.set(cv2.CAP_PROP_POS_MSEC, 3500)
    ok, frame = cap.read()
    assert ok and frame[:, 639:641].mean() < 20                                         # the dark line


def test_vertical_clip_never_cuts_a_split_in_half(tmp_path):
    """9:16 from the AI edit (the talker has no close-up) over a split: every shot from its own camera instead."""
    for f in ("session.json", "diarization.json", "features.parquet"):
        shutil.copy(MOCK / f, tmp_path)
    write_json(tmp_path / "speaker_map.json", {})                                       # nobody has a close-up
    cuts = [{"start": 30.0, "end": 37.0, "cam": 2}, {"start": 37.0, "end": 41.0, "cam": 3, "split": [3, 2],
                                                      "split_x": [0.5, 0.5]}]
    feats = pd.read_parquet(MOCK / "features.parquet")
    source, crop = vertical_source(tmp_path, 30.0, 41.0, cuts, feats)
    assert [(c["start"], c["end"], c["cam"]) for c in source] == [(30.0, 37.0, 2), (37.0, 41.0, 3)]
    assert crop is None and all(c["crop_x"] is not None for c in source)               # each shot on its own face


def test_speaker_coverage_counts_both_halves():
    """In a split both close-ups are on screen: the speaker on the second camera is seen too."""
    times = np.round(np.arange(0, 10, 0.1), 2)
    speaking = np.where(times < 5, 2, 3)
    plain = [{"start": 0.0, "end": 10.0, "cam": 3}]
    both = [{"start": 0.0, "end": 10.0, "cam": 3, "split": [3, 2], "split_x": [0.5, 0.5]}]
    assert edit_scores(plain, times, speaking)["speaker_coverage"] == 0.5
    assert edit_scores(both, times, speaking)["speaker_coverage"] == 1.0


def test_contract_allows_split_shots():
    from ai_director.common.schemas import Cut
    c = Cut(**{"start": 1.0, "end": 5.0, "cam": 3, "split": [3, 2], "split_x": [0.5, 0.8]})
    assert c.split == [3, 2] and Cut(**{"start": 0, "end": 1, "cam": 1}).split is None
    assert read_json(MOCK / "cuts.json")                                                # the mock's file still loads
