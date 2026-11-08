# tests/test_style_report.py — Task 2: the calibration report (the same recording edited with every style, measured).
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ai_director.common.config import job_config, merged
from ai_director.common.io import read_json, write_json
from ai_director.common.paths import MOCK
from ai_director.director import render
from ai_director.director.styles import load_styles
from eval.style_report import markdown, rhythm, style_rows

GOLDEN = Path(__file__).parent / "golden" / "balanced_cuts_mock.json"


def test_rhythm_numbers_of_one_edit():
    cuts = [{"start": 0.0, "end": 8.0, "cam": 1}, {"start": 8.0, "end": 12.0, "cam": 2},
            {"start": 12.0, "end": 24.0, "cam": 3, "split": [3, 2]}, {"start": 24.0, "end": 25.0, "cam": 3}]
    assert rhythm(cuts, wide=1) == {
        "shots": 4, "cuts_per_min": 7.2,        # 3 changes in 25 s
        "avg_shot": 6.25,
        "shortest": 4.0,                        # the last shot (1 s) ends with the video: not counted
        "longest_single": 8.0, "longest": 12.0,  # a split screen may be longer than the longest shot
        "splits": 1, "split_share": 48.0, "wide_share": 32.0}


def test_one_row_per_style_and_balanced_is_todays_edit():
    rows = style_rows(MOCK)
    named = [pid for pid, p in load_styles()["presets"].items() if not p.get("custom")]
    assert [r["style"] for r in rows] == named
    balanced = next(r for r in rows if r["style"] == "balanced")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert {k: balanced[k] for k in rhythm(golden, wide=1)} == rhythm(golden, wide=1)
    assert 0 <= balanced["speaker_coverage"] <= 100


def test_markdown_table_for_the_pull_request():
    text = markdown(style_rows(MOCK))
    assert "| Session | Style | Cuts / min |" in text
    assert "Calm interview" in text and "Lively debate" in text
    assert "Lively debate vs Calm interview" in text and "cuts per minute" in text


@pytest.fixture
def laughing(tmp_path):
    """The mock (with videos) with laughter at 20-21 s inside the camera 3 shot 12.5-27.5 s: a punch-in there."""
    s = tmp_path / "s00"
    shutil.copytree(MOCK, s)
    ev = read_json(s / "audio_events.json")
    for e in ev:
        e["laugh"] = 0.6 if e["t"] in (20, 21) else 0.0
    write_json(s / "audio_events.json", ev)
    return s


def frame(path, t):
    return subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1", "-f", "rawvideo",
                           "-pix_fmt", "gray", "-s", "64x36", "-"], capture_output=True).stdout


def test_render_program_can_use_another_styles_zoom(laughing):
    """A preview of a style must use THAT style's punch-ins, not the ones of the job's own style."""
    cuts = json.loads(GOLDEN.read_text(encoding="utf-8"))
    no_zoom = merged(job_config(laughing), {"zoom": {"enabled": False}})
    render.render_program(laughing, cuts, out="nozoom.mp4", cfg=no_zoom)
    plain, made = frame(laughing / "video/cam3.mp4", 26), frame(laughing / "nozoom.mp4", 26)
    assert sum(abs(x - y) for x, y in zip(made, plain)) / len(plain) < 2     # no push-in: the plain camera picture
