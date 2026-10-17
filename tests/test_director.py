# tests/test_director.py — the whole director (scorer + switcher) on the mock session
from ai_director.common.paths import MOCK
from ai_director.director.run import decide, to_segments


def test_to_segments():
    on_air = [(0.0, 1), (0.1, 1), (0.2, 2), (0.3, 2), (0.4, 2)]
    assert to_segments(on_air) == [{"start": 0.0, "end": 0.2, "cam": 1}, {"start": 0.2, "end": 0.5, "cam": 2}]


def test_mock_cut_list_is_valid():
    cuts, _ = decide(MOCK)
    assert cuts[0]["start"] == 0.0 and cuts[-1]["end"] == 60.0           # covers the whole video
    assert all(a["end"] == b["start"] for a, b in zip(cuts, cuts[1:]))   # no gaps, no overlaps
    assert all(c["end"] - c["start"] >= 2.0 for c in cuts[:-1])          # no shot shorter than 2 s


def test_mock_follows_the_speakers():
    cuts, _ = decide(MOCK)
    on_air = lambda t: next(c["cam"] for c in cuts if c["start"] <= t < c["end"])
    assert on_air(8.0) == 2        # host talking
    assert on_air(20.0) == 3       # guest talking
    assert on_air(45.0) == 3       # guest talking