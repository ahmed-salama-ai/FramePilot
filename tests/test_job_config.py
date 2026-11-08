# tests/test_job_config.py — Task 2: every job reads its own editing settings (configs/default.yaml + the editing
# style saved with the job in upload.json -> style -> config). A job without a style must behave exactly as before.
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml

from ai_director.common.config import job_config
from ai_director.common.io import read_json, write_json
from ai_director.common.paths import CONFIGS, MOCK
from ai_director.director.run import decide
from ai_director.director.scorer import score
from ai_director.director.why import explain
from ai_director.director.zoom import zoom_plan
from ai_director.highlights.clips import strip_shots

GOLDEN = Path(__file__).parent / "golden" / "balanced_cuts_mock.json"      # decide(MOCK) before Task 2
DEFAULTS = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def s(tmp_path):
    """The mock session's data files (no videos) in a temporary folder."""
    out = tmp_path / "s00"
    out.mkdir()
    for f in MOCK.iterdir():
        if f.is_file() and f.suffix in (".json", ".jsonl", ".parquet"):
            shutil.copy2(f, out / f.name)
    return out


def with_style(s, config):
    """Save an editing style with this job, the way the upload page will."""
    up = read_json(s / "upload.json") if (s / "upload.json").exists() else {}
    write_json(s / "upload.json", {**up, "style": {"preset": "custom", "config": config}})


# ---------- job_config ----------

def test_job_config_without_style_is_default_yaml(s):
    assert job_config(s) == DEFAULTS


def test_job_config_puts_the_saved_style_over_the_defaults(s):
    with_style(s, {"switcher": {"min_shot": 4.0}, "scorer": {"weights": {"speaker": 2.0}}})
    cfg = job_config(s)
    assert cfg["switcher"] == {**DEFAULTS["switcher"], "min_shot": 4.0}                # the other rules stay
    assert cfg["scorer"]["weights"] == {**DEFAULTS["scorer"]["weights"], "speaker": 2.0}
    assert cfg["split"] == DEFAULTS["split"]


def test_one_jobs_style_does_not_leak_into_another_job(s):
    with_style(s, {"switcher": {"min_shot": 4.0}})
    job_config(s)
    assert job_config(MOCK) == DEFAULTS


# ---------- the Balanced guarantee ----------

def test_a_job_without_style_gets_the_same_edit_as_before():
    cuts, _ = decide(MOCK)
    assert cuts == json.loads(GOLDEN.read_text(encoding="utf-8"))


# ---------- every part of the edit follows the job's settings ----------

def test_switcher_follows_the_jobs_shortest_shot(s):
    assert min(c["end"] - c["start"] for c in decide(s)[0][:-1]) < 5.0                 # today: 2 s shots
    with_style(s, {"switcher": {"min_shot": 5.0}})
    cuts, _ = decide(s)
    assert all(c["end"] - c["start"] >= 5.0 - 1e-9 for c in cuts[:-1] if not c.get("split"))


def test_split_screen_follows_the_jobs_setting(s):
    assert any(c.get("split") for c in decide(s)[0])                                  # today: one split screen
    with_style(s, {"split": {"enabled": False}})
    assert not any(c.get("split") for c in decide(s)[0])


def test_camera_scores_follow_the_jobs_weights(s):
    plain = score(s).score.to_numpy()
    with_style(s, {"scorer": {"weights": {"speaker": 0.0}}})                          # ignore who is talking
    muted = score(s).score.to_numpy()
    assert (muted <= plain + 1e-9).all() and (muted < plain - 1e-6).any()


def test_punch_in_zoom_follows_the_jobs_setting(s):
    ev = read_json(s / "audio_events.json")
    for e in ev:
        e["laugh"] = 0.6 if e["t"] in (20, 21) else 0.0                               # laughter in the cam 3 shot
    write_json(s / "audio_events.json", ev)
    cuts = read_json(s / "cuts.json")
    assert zoom_plan(s, cuts)
    with_style(s, {"zoom": {"enabled": False}})
    assert zoom_plan(s, cuts) == {}


def test_why_this_shot_uses_the_jobs_longest_shot(s):
    cuts = [{"start": 0.0, "end": 3.0, "cam": 1}, {"start": 3.0, "end": 12.8, "cam": 2},
            {"start": 12.8, "end": 27.6, "cam": 3}, {"start": 27.6, "end": 32.0, "cam": 1},
            {"start": 32.0, "end": 60.0, "cam": 2}]
    assert explain(s, cuts)[3]["code"] == "wide_variety"          # after a 14.8 s close-up (longest shot 15 s)
    with_style(s, {"switcher": {"max_shot": 30.0}})
    assert explain(s, cuts)[3]["code"] == "wide_safe"             # 14.8 s is no longer "too long"


def test_vertical_clip_strip_uses_the_jobs_shortest_shot(tmp_path):
    """Two people on camera 2: A talks 0-10 s and 13-20 s, B talks 10-13 s (a 3 s turn)."""
    s = tmp_path / "s"
    s.mkdir()
    write_json(s / "speaker_map.json", {"A": 2, "B": 2})
    write_json(s / "diarization.json", [{"start": 0.0, "end": 10.0, "speaker": "A"},
                                        {"start": 10.0, "end": 13.0, "speaker": "B"},
                                        {"start": 13.0, "end": 20.0, "speaker": "A"}])
    t = [round(i * 0.1, 1) for i in range(200)]
    feats = pd.DataFrame({"t": t, "cam": 2, "face_area": 0.1, "face_x": [0.8 if 10 <= x < 13 else 0.2 for x in t]})
    shot = [{"start": 0.0, "end": 20.0, "cam": 2}]
    assert [p["crop_x"] for p in strip_shots(s, shot, feats)] == [0.2, 0.8, 0.2]   # 3 s turn >= 2 s: B is shown
    with_style(s, {"switcher": {"min_shot": 4.0}})
    assert [p["crop_x"] for p in strip_shots(s, shot, feats)] == [0.2]             # 3 s turn < 4 s: stays on A
