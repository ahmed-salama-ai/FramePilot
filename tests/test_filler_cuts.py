import json
import subprocess

import numpy as np
import pytest
import soundfile as sf

from ai_director.director.filler_cuts import FPS, drop_cut_words, filler_mode, plan_fillers, plan_removed
from ai_director.director.render import audio_graph

SR = 16000
WORDS = [("انا", 0.5, 0.9), ("قلت", 1.0, 1.4), ("اه", 1.6, 1.9), ("الموضوع", 2.1, 2.8), ("صعب", 2.9, 3.3)]


def session(tmp_path, words=WORDS, mode="conservative"):
    """A small session: one speaker, a tone while each word is said, near silence between words."""
    rows = [{"id": 0, "speaker": "A", "words": [{"w": w, "start": a, "end": b} for w, a, b in words]}]
    (tmp_path / "transcript.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "upload.json").write_text(json.dumps({"filler_mode": mode}), encoding="utf-8")
    t = np.arange(int(10 * SR)) / SR
    audio = np.random.default_rng(0).normal(0, 0.001, len(t))
    for _, a, b in words:
        on = (t >= a) & (t < b)
        audio[on] += 0.3 * np.sin(2 * np.pi * 220 * t[on])
    sf.write(tmp_path / "audio.wav", audio.astype("float32"), SR)
    return tmp_path


def still(session_dir, cam, t):
    return np.zeros(64 * 36)


def moving(session_dir, cam, t):
    return np.full(64 * 36, 0.0 if t < 1.75 else 120.0)


def never(session_dir, cam, t):
    raise AssertionError("a cut hidden at a camera change needs no picture check")


ONE_SHOT = [{"start": 0.0, "end": 10.0, "cam": 1}]


def test_the_mode_comes_from_the_upload(tmp_path):
    assert filler_mode(tmp_path) == "off"
    (tmp_path / "upload.json").write_text(json.dumps({"filler_mode": "standard"}), encoding="utf-8")
    assert filler_mode(tmp_path) == "standard"
    (tmp_path / "upload.json").write_text(json.dumps({"filler_mode": "everything"}), encoding="utf-8")
    assert filler_mode(tmp_path) == "off"


def test_off_cuts_nothing(tmp_path):
    s = session(tmp_path, mode="off")
    assert plan_fillers(s, ONE_SHOT, frame=never) == ([], [])


def test_a_still_picture_on_the_same_camera_is_cut_on_frames_between_words(tmp_path):
    removed, report = plan_fillers(session(tmp_path), ONE_SHOT, frame=still)
    assert len(removed) == 1 and report[0]["result"].startswith("cut: same camera")
    r0, r1 = removed[0]
    assert 1.4 <= r0 <= 1.62 and 1.88 <= r1 <= 2.1                       # in the quiet around the word
    assert abs(r0 * FPS - round(r0 * FPS)) < 0.01 and abs(r1 * FPS - round(r1 * FPS)) < 0.01


def test_a_jump_that_would_show_keeps_the_filler(tmp_path):
    removed, report = plan_fillers(session(tmp_path), ONE_SHOT, frame=moving)
    assert removed == [] and report[0]["result"] == "kept: the jump on the same camera would show"
    assert report[0]["jump"] > 0.06


def test_a_camera_change_nearby_moves_into_the_cut(tmp_path):
    cuts = [{"start": 0.0, "end": 2.2, "cam": 1}, {"start": 2.2, "end": 10.0, "cam": 2}]       # 0.4 s away
    removed, report = plan_fillers(session(tmp_path), cuts, frame=never)
    assert len(removed) == 1 and report[0]["result"] == "cut: hidden at a camera change"


def test_a_camera_change_already_hiding_a_pause_stays_there(tmp_path):
    cuts = [{"start": 0.0, "end": 2.2, "cam": 1}, {"start": 2.2, "end": 10.0, "cam": 2}]
    s = session(tmp_path)
    assert plan_fillers(s, cuts, frame=never)[1][0]["result"] == "cut: hidden at a camera change"
    removed, report = plan_fillers(s, cuts, frame=still, done=[[2.1, 2.3]])
    assert report[0]["result"].startswith("cut: same camera")


def test_a_camera_change_too_far_away_stays_and_the_shot_after_it_takes_the_cut(tmp_path):
    cuts = [{"start": 0.0, "end": 1.2, "cam": 1}, {"start": 1.2, "end": 10.0, "cam": 2}]       # 0.55 s away
    removed, report = plan_fillers(session(tmp_path), cuts, frame=still)
    assert len(removed) == 1 and report[0]["result"].startswith("cut: same camera")   # not "a flash of a shot"


def test_fillers_said_together_are_one_cut(tmp_path):
    words = WORDS[:3] + [("امم", 1.95, 2.25), ("الموضوع", 2.5, 3.0)]
    removed, report = plan_fillers(session(tmp_path, words), ONE_SHOT, frame=still)
    assert len(removed) == 1 and len(report) == 1 and report[0]["text"] == "اه امم"


def test_plan_removed_saves_the_report(tmp_path):
    s = session(tmp_path)
    removed, shots = plan_removed(s, ONE_SHOT, frame=still)
    rep = json.loads((s / "filler_cuts.json").read_text(encoding="utf-8"))
    assert rep["mode"] == "conservative" and rep["cut"] == 1 and len(removed) == 1 and shots == ONE_SHOT
    (s / "upload.json").write_text(json.dumps({"filler_mode": "off"}), encoding="utf-8")
    assert plan_removed(s, ONE_SHOT, frame=never) == ([], ONE_SHOT) and not (s / "filler_cuts.json").exists()


def test_the_render_gets_the_shots_with_the_camera_change_moved(tmp_path):
    cuts = [{"start": 0.0, "end": 2.2, "cam": 1}, {"start": 2.2, "end": 10.0, "cam": 2}]
    removed, shots = plan_removed(session(tmp_path), cuts, frame=never)
    (r0, r1), = removed
    assert r0 < shots[0]["end"] == shots[1]["start"] < r1                  # the change is inside the cut piece


def test_a_camera_change_never_moves_across_another_cut(tmp_path):
    from ai_director.director.filler_cuts import fit_free
    cuts = [{"start": 0.0, "end": 9.95, "cam": 1}, {"start": 9.95, "end": 20.0, "cam": 2}]
    assert fit_free(cuts, 10.25, 10.4, done=[])[1]["start"] == 10.3
    assert fit_free(cuts, 10.25, 10.4, done=[[10.0, 10.1]]) is cuts
    assert fit_free(cuts, 10.25, 10.4, done=[], move_max=0.2) is cuts


def test_cut_words_leave_the_captions():
    words = [{"w": "انا", "start": 0.5, "end": 0.9}, {"w": "اه", "start": 1.6, "end": 1.9},
             {"w": "قلت", "start": 2.0, "end": 2.4}]
    item = {"start": 0.5, "end": 2.4, "text": "P: انا اه قلت\nI uh said",
            "lines": [{"text": "P: انا اه قلت", "prefix": "P: ", "words": words},
                      {"text": "I uh said", "prefix": "", "words": []}]}
    out = drop_cut_words([item], [[1.55, 1.95]])
    assert out[0]["lines"][0]["text"] == "P: انا قلت" and [w["w"] for w in out[0]["lines"][0]["words"]] == ["انا", "قلت"]
    assert out[0]["lines"][1]["text"] == "I uh said"                     # no word times: the translation stays
    assert out[0]["text"] == "P: انا قلت\nI uh said"
    assert drop_cut_words([item], None) == [item] and drop_cut_words([item], [[5.0, 6.0]]) == [item]
    only_filler = {**item, "lines": [{"text": "اه", "prefix": "", "words": [words[1]]}]}
    assert drop_cut_words([only_filler], [[1.55, 1.95]]) == []


@pytest.mark.parametrize("fade", [0.025, 0.01])
def test_the_crossfaded_sound_is_as_long_as_the_kept_parts(tmp_path, fade):
    parts = [(0.0, 1.0), (1.3, 2.0333), (2.5, 4.0)]
    (tmp_path / "graph.txt").write_text(";\n".join(audio_graph(parts, fade)), encoding="utf-8")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-f", "lavfi",
                    "-i", "sine=frequency=300:sample_rate=48000:duration=5", "-/filter_complex", "graph.txt",
                    "-map", "[aout]", "out.wav"], cwd=tmp_path, check=True)
    got = sf.info(tmp_path / "out.wav").duration
    assert abs(got - sum(b - a for a, b in parts)) < 0.002


def stream_seconds(path, kind):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", kind, "-show_entries", "stream=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout
    return float(out.split()[0])


def test_cuts_on_frames_keep_picture_and_sound_the_same_length(tmp_path, monkeypatch):
    import shutil
    from ai_director.common.paths import MOCK
    from ai_director.director import render
    from ai_director.director.render import render_program
    shutil.copytree(MOCK / "video", tmp_path / "video")
    shutil.copy(MOCK / "session.json", tmp_path)
    cuts = [{"start": 0.0, "end": 2.0, "cam": 1}, {"start": 2.0, "end": 4.0, "cam": 2},
            {"start": 4.0, "end": 6.0, "cam": 3}]
    removed = [[0.6333, 0.9], [1.4667, 1.7333], [2.9, 3.1667], [4.2333, 4.5]]          # fillers: on frames, not on 0.1 s
    monkeypatch.setattr(render, "fit_cuts", lambda *a: pytest.fail("the planned shots were moved again"))
    out = render_program(tmp_path, cuts, removed=removed, fitted=True)
    want = 6.0 - sum(b - a for a, b in removed)
    assert abs(stream_seconds(out, "v") - want) < 0.5 / FPS
    assert abs(stream_seconds(out, "a") - want) < 0.03                    # AAC adds a few ms of padding
