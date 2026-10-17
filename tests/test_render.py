import json
import shutil

import pandas as pd

from ai_director.common.io import read_json
from ai_director.common.paths import MOCK
from ai_director.director.baselines import random_cuts, wide_cuts
from ai_director.director.render import render_program
from ai_director.director.run import make_timeline
from ai_director.ingest.probe import probe


def test_timeline_matches_mock():
    sc = pd.read_parquet(MOCK / "scores.parquet")
    ours = make_timeline(sc, read_json(MOCK / "cuts.json"))
    assert json.loads(json.dumps(ours)) == read_json(MOCK / "timeline.json")


def test_random_baseline():
    cuts = random_cuts(60.0, [1, 2, 3], seed=0)
    assert cuts == random_cuts(60.0, [1, 2, 3], seed=0)                 # same seed -> same edit
    assert cuts[0]["start"] == 0.0 and cuts[-1]["end"] == 60.0
    assert all(a["end"] == b["start"] and a["cam"] != b["cam"] for a, b in zip(cuts, cuts[1:]))
    assert all(2.0 <= c["end"] - c["start"] <= 8.0 for c in cuts[:-1])


def test_wide_baseline():
    assert wide_cuts(60.0, 1) == [{"start": 0.0, "end": 60.0, "cam": 1}]


def test_render_program(tmp_path):
    shutil.copytree(MOCK / "video", tmp_path / "video")                 # a small copy of the mock session
    shutil.copy(MOCK / "session.json", tmp_path)
    cuts = [{"start": 0.0, "end": 2.0, "cam": 1}, {"start": 2.0, "end": 4.0, "cam": 2},
            {"start": 4.0, "end": 6.0, "cam": 3}]
    out = render_program(tmp_path, cuts)
    info = probe(out)
    assert (info["width"], info["height"]) == (1280, 720)
    assert abs(info["duration"] - 6.0) < 0.1                             # 3 shots x 2 s
    assert not list((tmp_path / "tmp").glob("seg*.mp4"))                 # shot files cleaned up

def clip_session(tmp_path):
    """A copy of the mock files render_clip needs (never write into samples/mock_s00)."""
    shutil.copytree(MOCK / "video", tmp_path / "video")
    for f in ("session.json", "upload.json", "transcript.json", "program_nocaps.mp4"):
        shutil.copy(MOCK / f, tmp_path)
    return tmp_path


def test_render_clip_both_formats(tmp_path):
    from ai_director.director.render import render_clip
    s = clip_session(tmp_path)
    wide = probe(render_clip(s, 12.0, 27.0, "clips/a_169.mp4"))                       # 16:9, the AI edit, captions
    assert (wide["width"], wide["height"]) == (1280, 720) and abs(wide["duration"] - 15.0) < 0.1
    tall = probe(render_clip(s, 12.0, 27.0, "clips/b_916.mp4", fmt="9:16", source=3, crop_x=0.62))
    assert (tall["width"], tall["height"]) == (720, 1280) and abs(tall["duration"] - 15.0) < 0.1
    assert probe(render_clip(s, 38.0, 52.0, "clips/c.mp4", langs="none"))["duration"] > 13.9   # no captions
    assert not list((s / "tmp").glob("*.srt"))                                          # caption files cleaned up


def test_render_clip_refuses_bad_times(tmp_path):
    import pytest
    from ai_director.director.render import render_clip
    s = clip_session(tmp_path)
    for a, b in ((50.0, 70.0), (20.0, 10.0), (-1.0, 5.0)):
        with pytest.raises(ValueError):
            render_clip(s, a, b, "clips/x.mp4")
    with pytest.raises(ValueError):
        render_clip(s, 1.0, 5.0, "clips/x.mp4", fmt="1:1")


def test_make_cuts_boost_and_mode(tmp_path):
    from ai_director.director.run import make_cuts
    s = tmp_path / "s00"
    shutil.copytree(MOCK, s)
    share = lambda cuts, cam: sum(c["end"] - c["start"] for c in cuts if c["cam"] == cam)
    normal = make_cuts(s, out="cuts_normal.json")
    boosted = make_cuts(s, boost={"cam": 3, "factor": 1.5}, out="cuts_v2.json")     # what the agent's restyle does
    wide = make_cuts(s, force_mode="wide_energy", out="cuts_wide_energy.json")
    assert share(boosted, 3) > share(normal, 3)                                      # more camera 3
    assert share(wide, 1) > share(normal, 1)                                         # more wide shot
    assert (s / "cuts_v2.json").exists() and read_json(s / "cuts.json") == read_json(MOCK / "cuts.json")  # done file untouched


def test_video_quality_comes_from_the_config():
    import yaml
    from ai_director.common import io
    from ai_director.common.paths import CONFIGS
    cfg = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["video"]["quality"]
    assert {k: io.quality(k) for k in io.QUALITY} == cfg and set(cfg) == set(io.QUALITY)


def test_h264_settings(monkeypatch):
    import ai_director.common.io as io
    monkeypatch.setattr(io, "video_encoder", lambda: "h264_nvenc")                    # an NVIDIA GPU
    gpu = io.h264(20)
    assert gpu[:2] == ["-c:v", "h264_nvenc"] and "-cq" in gpu and gpu[-2:] == ["-pix_fmt", "yuv420p"]
    assert io.decode_on_gpu() == ["-hwaccel", "cuda"]
    monkeypatch.setattr(io, "video_encoder", lambda: "libx264")                       # no NVIDIA GPU
    assert io.h264(21) == ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p"]
    assert io.decode_on_gpu() == []


def test_render_writes_8_bit_video(tmp_path):
    import subprocess
    shutil.copytree(MOCK / "video", tmp_path / "video")
    shutil.copy(MOCK / "session.json", tmp_path)
    out = render_program(tmp_path, [{"start": 0.0, "end": 2.0, "cam": 1}])
    pix = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=pix_fmt",
                          "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    assert pix == "yuv420p"                                                           # 8-bit: plays in browsers


def test_render_clip_from_shots(tmp_path):
    """The agent's "mostly one person" edit: every shot from its own camera, joined in one run, captions on top."""
    import pytest
    from ai_director.director.render import render_clip
    s = clip_session(tmp_path)
    shots = [{"start": 12.0, "end": 16.5, "cam": 3}, {"start": 16.5, "end": 21.0, "cam": 2},
             {"start": 21.0, "end": 27.0, "cam": 1}]
    wide = probe(render_clip(s, 12.0, 27.0, "clips/m_169.mp4", source=shots))
    assert (wide["width"], wide["height"]) == (1280, 720) and abs(wide["duration"] - 15.0) < 0.1
    tall = probe(render_clip(s, 12.0, 27.0, "clips/m_916.mp4", fmt="9:16", source=shots, crop_x={3: 0.62, 2: 0.4},
                             langs="ar"))                                   # each camera cropped on its own face
    assert (tall["width"], tall["height"]) == (720, 1280) and abs(tall["duration"] - 15.0) < 0.1
    with pytest.raises(ValueError, match="must cover"):
        render_clip(s, 10.0, 27.0, "clips/x.mp4", source=shots)


def test_1080p_clips(tmp_path):
    from ai_director.common.io import run, write_json
    from ai_director.director.render import crop_916, render_clip
    assert crop_916(None) == "crop=404:720:438:0,scale=720:1280"                       # the old 720p numbers
    assert crop_916(None, 1920, 1080) == "crop=608:1080:656:0,scale=1080:1920"
    assert crop_916(0.0, 1920, 1080).startswith("crop=608:1080:0:0") and ":1312:" in crop_916(1.0, 1920, 1080)
    (tmp_path / "video").mkdir()
    for c in (1, 2):
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=3", "-f", "lavfi",
             "-i", "sine=duration=3", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-shortest", f"video/cam{c}.mp4"], cwd=tmp_path)
    write_json(tmp_path / "session.json", {"duration": 3.0, "reference_cam": 1, "language": "ar"})
    tall = probe(render_clip(tmp_path, 0.5, 2.5, "clips/t.mp4", fmt="9:16", source=2, crop_x=0.7, langs="none"))
    wide = probe(render_clip(tmp_path, 0.5, 2.5, "clips/w.mp4", source=[{"start": 0.5, "end": 1.5, "cam": 1},
                                                                      {"start": 1.5, "end": 2.5, "cam": 2}], langs="none"))
    assert (tall["width"], tall["height"]) == (1080, 1920) and (wide["width"], wide["height"]) == (1920, 1080)
