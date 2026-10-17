# tests/test_switcher.py — the editing rules, one test per rule   (run: pytest -q)
from ai_director.director.switcher import Switcher

CFG = dict(min_shot=2.0, margin=0.2, hold=0.4, max_shot=15.0, low_score=0.3, wide_cam=1)


def run(sw, seconds, scores, speaker_cam=None):
    """Call step() every 0.1 s with the same scores; return the camera on air at every step."""
    return [sw.step(i / 10, scores, speaker_cam) for i in range(int(seconds * 10))]


def test_no_cut_before_2_seconds():                          # rule 1
    cams = run(Switcher(CFG, start_cam=1), 1.9, {1: 0.5, 2: 5.0, 3: 0.5})
    assert set(cams) == {1}


def test_follows_new_speaker():                              # rule 2
    cams = run(Switcher(CFG, start_cam=1), 2.5, {1: 1, 2: 1, 3: 1}, speaker_cam=3)
    assert cams[-1] == 3


def test_max_shot_goes_wide():                               # rule 3
    cams = run(Switcher(CFG, start_cam=2), 16, {1: 0.5, 2: 5.0, 3: 0.5})
    assert cams[-1] == 1


def test_all_low_goes_wide():                                # rule 4
    cams = run(Switcher(CFG, start_cam=2), 3, {1: 0.1, 2: 0.2, 3: 0.1})
    assert cams[-1] == 1


def test_small_lead_is_ignored():                            # margin: 10% better is not enough
    cams = run(Switcher(CFG, start_cam=2), 14, {1: 0.5, 2: 2.0, 3: 2.2})
    assert set(cams) == {2}


def test_clear_winner_after_hold():                          # rule 5: 20% better AND for 0.4 s
    cams = run(Switcher(CFG, start_cam=2), 3, {1: 0.5, 2: 1.0, 3: 2.0})
    assert cams[20] == 2 and cams[23] == 2                   # 2.0 s: becomes candidate; 2.3 s: still waiting
    assert cams[24] == 3                                     # 2.4 s: held for 0.4 s -> cut


def test_blink_does_not_cut():                               # a lead of only 0.3 s never becomes a cut
    sw = Switcher(CFG, start_cam=2)
    good, blink = {1: 0.5, 2: 2.0, 3: 1.0}, {1: 0.5, 2: 1.0, 3: 3.0}
    cams = [sw.step(i / 10, blink if (i // 3) % 2 else good) for i in range(60)]
    assert set(cams) == {2}