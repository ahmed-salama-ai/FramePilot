"""Square 1:1 clips (Task 3): the crop window, the clip file, and captions that stay inside the square."""
import shutil
import subprocess

import numpy as np
import pandas as pd

from ai_director.audio.subtitles import RLM
from ai_director.common.io import run, write_json
from ai_director.common.paths import MOCK
from ai_director.director import render
from ai_director.director.brand import caption_fields, load_brand
from ai_director.director.render import crop_11, crop_916, render_clip, window_x
from ai_director.highlights.clips import strip_shots, vertical_source
from ai_director.ingest.probe import probe

# camera 2 = two people (A left, B right), camera 3 = C alone; A talks, then B (a 0.6 s "yes" from A makes no cut)
DIAR = [{"start": 0.0, "end": 6.0, "speaker": "A"}, {"start": 6.5, "end": 12.0, "speaker": "B"},
        {"start": 12.2, "end": 12.8, "speaker": "A"},
        {"start": 13.0, "end": 20.0, "speaker": "B"}, {"start": 20.5, "end": 30.0, "speaker": "C"}]


def two_people(tmp_path, a, b):
    """A tiny session: A sits at a, B at b on camera 2 (perception's face follows the talker), C at 0.5 on camera 3."""
    write_json(tmp_path / "diarization.json", DIAR)
    write_json(tmp_path / "speaker_map.json", {"A": 2, "B": 2, "C": 3})
    t = np.round(np.arange(0, 30, 0.1), 2)
    x2 = np.where([any(d["speaker"] == "B" and d["start"] <= v <= d["end"] for d in DIAR) for v in t], b, a)
    return pd.DataFrame({"t": np.concatenate([t, t]), "cam": [2] * len(t) + [3] * len(t),
                         "face_area": 0.027, "face_x": np.concatenate([x2, np.full(len(t), 0.5)])})


def test_square_follows_the_talker_when_two_people_are_far_apart(tmp_path):
    """s01 camera 2: the two people sit at 0.186 and 0.773, too far apart for one square -> it cuts to whoever
    talks, exactly like the 9:16 strip."""
    feats = two_people(tmp_path, 0.186, 0.773)
    one = [{"start": 0.0, "end": 20.0, "cam": 2}]
    square = strip_shots(tmp_path, one, feats, fmt="1:1")
    assert [(c["start"], c["end"], c["crop_x"]) for c in square] == [(0.0, 6.5, 0.186), (6.5, 20.0, 0.773)]
    assert square == strip_shots(tmp_path, one, feats)                             # = the 9:16 pieces
    for c in square:                                                              # the talker's face inside
        x0 = window_x(c["crop_x"], 1920, 1080) / 1920
        assert x0 + 0.06 <= c["crop_x"] <= x0 + 1080 / 1920 - 0.06


def test_square_keeps_both_people_when_they_fit(tmp_path):
    """0.32 apart: too far for a 9:16 strip (it follows the talker), but the square shows both, centred."""
    feats = two_people(tmp_path, 0.30, 0.62)
    one = [{"start": 0.0, "end": 20.0, "cam": 2}]
    assert len(strip_shots(tmp_path, one, feats)) == 2                             # 9:16: as before
    square = strip_shots(tmp_path, one, feats, fmt="1:1")
    assert [c["crop_x"] for c in square] == [0.46]                                 # one shot, between them
    x0 = window_x(0.46, 1920, 1080) / 1920
    assert x0 + 0.06 <= 0.30 and 0.62 <= x0 + 1080 / 1920 - 0.06                   # both faces well inside
    assert strip_shots(tmp_path, one, feats, keep={2: 0.30}, fmt="1:1")[0]["crop_x"] == 0.30   # "show A": A


def test_square_highlight_source(tmp_path):
    feats = two_people(tmp_path, 0.186, 0.773)
    source, crop = vertical_source(tmp_path, 0.0, 20.0, [], feats, fmt="1:1")      # B talks most -> camera 2
    assert crop is None and [(c["cam"], c["crop_x"]) for c in source] == [(2, 0.186), (2, 0.773)]
    assert vertical_source(tmp_path, 21.0, 29.0, [], feats, fmt="1:1") == (3, 0.5)   # a close-up: on the face


def clip_session(tmp_path):
    """A copy of the mock files render_clip needs (never write into samples/mock_s00)."""
    shutil.copytree(MOCK / "video", tmp_path / "video")
    for f in ("session.json", "upload.json", "transcript.json", "program_nocaps.mp4"):
        shutil.copy(MOCK / f, tmp_path)
    return tmp_path


def test_square_crop_window():
    assert crop_11(None, 1920, 1080) == "crop=1080:1080:420:0"                    # the middle
    assert crop_11(0.0, 1920, 1080) == "crop=1080:1080:0:0"                       # kept inside at the edges
    assert crop_11(1.0, 1920, 1080) == "crop=1080:1080:840:0"
    assert crop_11(0.5, 1920, 1080) == "crop=1080:1080:420:0"                     # face in the middle of the square
    assert crop_11(0.773, 1920, 1080) == "crop=1080:1080:840:0"                   # s01 cam 2, the right person
    assert crop_11(None) == "crop=720:720:280:0"                                  # 720p: 720x720, no upscaling
    assert crop_916(None, 1920, 1080) == "crop=608:1080:656:0,scale=1080:1920"    # 9:16 unchanged


def test_render_square_clip(tmp_path):
    s = clip_session(tmp_path)
    one = probe(render_clip(s, 12.0, 27.0, "clips/a_11.mp4", fmt="1:1", source=3, crop_x=0.62))
    assert (one["width"], one["height"]) == (720, 720) and abs(one["duration"] - 15.0) < 0.1
    shots = [{"start": 12.0, "end": 16.5, "cam": 3}, {"start": 16.5, "end": 21.0, "cam": 2, "split": [2, 3],
                                                       "split_x": [0.5, 0.5]},
             {"start": 21.0, "end": 27.0, "cam": 2, "crop_x": 0.1}]              # a split: its main camera only
    two = probe(render_clip(s, 12.0, 27.0, "clips/b_11.mp4", fmt="1:1", source=shots, crop_x={3: 0.62}, langs="ar"))
    assert (two["width"], two["height"]) == (720, 720) and abs(two["duration"] - 15.0) < 0.1
    assert not list((s / "tmp").glob("*.ass"))                                    # caption file cleaned up


def test_square_clip_from_a_1080p_camera(tmp_path):
    (tmp_path / "video").mkdir()
    run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=3", "-f", "lavfi",
         "-i", "sine=duration=3", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", "video/cam1.mp4"], cwd=tmp_path)
    write_json(tmp_path / "session.json", {"duration": 3.0, "reference_cam": 1, "language": "ar"})
    info = probe(render_clip(tmp_path, 0.5, 2.5, "clips/sq.mp4", fmt="1:1", source=1, crop_x=0.3, langs="none"))
    assert (info["width"], info["height"]) == (1080, 1080)                        # the brief's 1080 x 1080


def test_caption_style_per_format(tmp_path):
    s = clip_session(tmp_path)
    style = {}
    for name, kw in (("169", {}), ("916", {"vertical": True}), ("11", {"square": True})):
        render.write_ass(s, tmp_path / f"{name}.ass", langs="ar+en", window=(12.0, 27.0), words=False, **kw)
        style[name] = next(l for l in (tmp_path / f"{name}.ass").read_text(encoding="utf-8-sig").splitlines()
                           if l.startswith("Style: Caption,"))
    assert style["169"].split(",")[2] == "15" and style["169"].endswith(",2,10,10,30,-1")   # 16:9: as before
    assert style["916"].split(",")[2] == "9" and style["916"].endswith(",2,10,10,30,-1")    # 9:16: as before
    assert style["11"].split(",")[2] == "15" and style["11"].endswith(",2,24,24,30,-1")     # 1:1: wider margins
    b = load_brand(s)
    for size, px in (("small", 13), ("medium", 15), ("large", 18)):
        assert caption_fields({**b, "captions": {**b["captions"], "size": size}}, square=True)["FontSize"] == px


def drawn_box(ass, t, side=1080):
    """Burn the .ass on a plain grey side x side picture at t seconds -> (left, top, right, bottom) of every pixel
    the captions changed (text, box and outline)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c=gray:s={side}x{side}:r=30:d=8",
                          "-vf", f"subtitles={ass.name}", "-ss", f"{t}", "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], cwd=ass.parent, capture_output=True, check=True).stdout
    frame = np.frombuffer(raw, np.uint8).reshape(side, side).astype(int)
    ys, xs = np.nonzero(np.abs(frame - np.median(frame)) > 8)
    assert len(xs), "no caption was drawn"
    return xs.min(), ys.min(), xs.max(), ys.max()


LONG_CAPTION = "\\N".join([                    # two people, Arabic + English, every line far too long for one row
    f"{RLM}- المذيع: الموضوع ده مهم جداً لكل الناس اللي بتشتغل في المجال ده من زمان",
    f"{RLM}- الضيف: أكيد طبعاً وده اللي إحنا بنحاول نوصله للجمهور في كل حلقة",
    "- Host: this topic matters a lot to everyone who has worked in this field for years",
    "- Guest: of course, and that is what we try to get across to the audience every episode"])


def long_caption_ass(s, ass):
    """The square caption style with ONE caption: LONG_CAPTION from 0 to 5 s."""
    render.write_ass(s, ass, langs="ar+en", window=(0.0, 1.0), words=False, square=True)
    head = [l for l in ass.read_text(encoding="utf-8-sig").splitlines() if not l.startswith("Dialogue")]
    ass.write_text("\n".join(head + [f"Dialogue: 0,0:00:00.00,0:00:05.00,Caption,,0,0,0,,{LONG_CAPTION}", ""]),
                   encoding="utf-8-sig")
    return ass


def test_longest_caption_stays_inside_the_square(tmp_path):
    """A worst case longer than any real caption (lines are cut at 42 letters). It wraps and stays at least 5 %
    inside every edge of a 1080 x 1080 clip."""
    s = clip_session(tmp_path)
    left, top, right, bottom = drawn_box(long_caption_ass(s, tmp_path / "long.ass"), 2.0)
    margin = 0.05 * 1080
    assert left >= margin and right <= 1080 - margin, (left, right)                # wrapped inside the side margins
    assert top >= margin and bottom <= 1080 - margin, (top, bottom)                # and inside top and bottom
