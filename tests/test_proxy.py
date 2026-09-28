# tests/test_proxy.py — start times and common length from the offsets
from pytest import approx

from ai_director.ingest.proxy import plan


def test_plan_starts_and_length():
    offsets = {1: 0.0, 2: 1.84, 3: -0.52}
    durations = {1: 60.82, 2: 62.36, 3: 60.6}
    starts, length = plan(offsets, durations)
    assert starts == approx({1: 0.52, 2: 2.36, 3: 0.0})
    assert length == approx(60.0)