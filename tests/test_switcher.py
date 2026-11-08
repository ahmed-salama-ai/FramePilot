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


# ---------- reaction shots (switcher.reactions, Task 2): at the longest shot, while the same person keeps talking,
# the listener's close-up instead of the wide shot, then back to the speaker after the shortest shot ----------
REACT = {**CFG, "reactions": True}
TALK = {1: 0.5, 2: 5.0, 3: 0.5}                              # camera 2's person talks the whole time


def run_faces(sw, seconds, scores, speaker_cam=None, faces=None):
    """run() + which cameras show a face at every step."""
    return [sw.step(i / 10, scores, speaker_cam, faces) for i in range(int(seconds * 10))]


def test_reactions_off_still_go_wide():                      # rule 3 exactly as before (Balanced)
    cams = run(Switcher(CFG, start_cam=2), 16, TALK, speaker_cam=2)
    assert cams[151] == 1


def test_reaction_shot_shows_the_listener():
    cams = run_faces(Switcher(REACT, start_cam=2), 16, TALK, speaker_cam=2, faces={2, 3})
    assert cams[150] == 2 and cams[151] == 3 and 1 not in cams   # 15.1 s: the listener (camera 3), not the wide shot


def test_reaction_shot_returns_to_the_speaker():
    cams = run_faces(Switcher(REACT, start_cam=2), 18, TALK, speaker_cam=2, faces={2, 3})
    assert cams[170] == 3 and cams[171] == 2                     # back after the shortest shot (2 s)


def test_no_reaction_when_the_listener_shows_no_face():
    cams = run_faces(Switcher(REACT, start_cam=2), 16, TALK, speaker_cam=2, faces={2})
    assert cams[151] == 1                                        # nobody visible on camera 3: the wide shot


def test_no_reaction_when_nobody_talks():
    cams = run_faces(Switcher(REACT, start_cam=2), 16, TALK, speaker_cam=None, faces={2, 3})
    assert cams[151] == 1


def test_reaction_shot_in_a_short_breath():
    """The speaker pauses 0.1 s before the longest shot is reached: still the same person talking -> a reaction."""
    sw = Switcher({**REACT, "reaction_pause": 1.5}, start_cam=2)
    cams = [sw.step(i / 10, TALK, 2 if i < 150 else None, {2, 3}) for i in range(160)]
    assert cams[151] == 3


def test_no_reaction_after_a_long_pause():
    """The speaker stopped 2.1 s before the longest shot: nobody holds the floor -> the wide shot, as before."""
    sw = Switcher({**REACT, "reaction_pause": 1.5}, start_cam=2)
    cams = [sw.step(i / 10, TALK, 2 if i < 130 else None, {2, 3}) for i in range(160)]
    assert cams[151] == 1


def test_the_listener_who_starts_talking_keeps_the_shot():
    sw = Switcher(REACT, start_cam=2)
    three = {1: 0.5, 2: 0.5, 3: 5.0}                             # from 15.5 s camera 3's person talks
    cams = [sw.step(i / 10, TALK if i < 155 else three, 2 if i < 155 else 3, {2, 3}) for i in range(190)]
    assert cams[151] == 3 and set(cams[151:]) == {3}             # no jump back to camera 2: camera 3 now talks