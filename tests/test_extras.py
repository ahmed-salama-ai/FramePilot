import json
import re
import shutil
import subprocess

import pytest

from ai_director.agent.search import find_words, normal
from ai_director.audio.subtitles import RLM, caption_items
from ai_director.common.io import read_json, write_json
from ai_director.common.paths import MOCK
from ai_director.director import pauses, render
from ai_director.director.coldopen import strongest_moment
from ai_director.director.podcast import make_podcast
from ai_director.director.stats import speaker_stats, turns
from ai_director.director.versions import V1, add_version, get_version, version_captions, video_time
from ai_director.director.why import TEXT, explain
from ai_director.director.zoom import zoom_filter, zoom_plan
from ai_director.ingest.probe import probe


@pytest.fixture
def s(tmp_path):
    shutil.copytree(MOCK, tmp_path / "s00")
    return tmp_path / "s00"


def with_pause(s):
    """The mock with a 3.2 s silence 11.8-15.0 s (SPEAKER_01 starts later); the director changes camera at 12.8 s."""
    for name in ("diarization.json", "speech.json"):
        items = read_json(s / name)
        for x in items:
            if abs(x["start"] - 12.5) < 0.3:
                x["start"] = 15.0
        write_json(s / name, items)


# ---------- word-by-word captions ----------

def test_caption_lines_keep_their_word_times(s):
    for x in caption_items(s):
        ar, en = x["lines"]
        assert x["text"] == ar["text"] + "\n" + en["text"]                    # the text is exactly as before
        assert ar["text"].startswith(RLM) and " ".join(w["w"] for w in ar["words"]) in ar["text"]
        assert en["words"] == []                                             # the translation has no word times
    assert all(x["lines"][0]["words"] == [] for x in caption_items(s, "en"))  # an Arabic video, English only


def test_word_by_word_ass(s):
    path = s / "tmp" / "w.ass"
    path.parent.mkdir(exist_ok=True)
    render.write_ass(s, path, words=False)
    plain = [l for l in path.read_text(encoding="utf-8-sig").splitlines() if l.startswith("Dialogue")]
    render.write_ass(s, path, words=True)
    lit = [l for l in path.read_text(encoding="utf-8-sig").splitlines() if l.startswith("Dialogue")]
    assert len(lit) > 2 * len(plain) and sum("\\1c&H3BD4FF&" in l for l in lit) > len(plain)   # the yellow word
    t = lambda x: int(x[0]) * 3600 + int(x[1]) * 60 + float(x[2])                               # noqa: E731
    times = [[t(m.split(":")) for m in l.split(",")[1:3]] for l in lit]
    assert all(b > a for a, b in times)                                      # never zero-long
    first = [l for l in lit if "\\1c" in l][0]
    assert first.count("{\\1c") == 1 and "{\\r}" in first                    # one word lit, then back to normal


def test_clip_captions_start_at_zero_and_language(s):
    path = s / "tmp" / "c.ass"
    path.parent.mkdir(exist_ok=True)
    render.write_ass(s, path, langs="en", vertical=True, window=(12.0, 27.0), words=False)
    text = path.read_text(encoding="utf-8-sig")
    assert "Style: Caption,Arial,9," in text or "Style: Caption,Noto Naskh Arabic,9," in text      # 9:16 size
    lines = [l for l in text.splitlines() if l.startswith("Dialogue")]
    assert lines and lines[0].split(",")[1] < "0:00:15.00" and not re.search("[؀-ۿ]", text)


def test_one_language_video(s):
    v = get_version(s, "v1")
    assert render.language_file(v, "ar+en") == "program.mp4" and render.language_file(v, "none") == "program_clean.mp4"
    assert render.language_file({**v, "program": "versions/v3/program.mp4"}, "en") == "versions/v3/program_en.mp4"
    render.finish(s, "program_nocaps.mp4", "program_en.mp4", read_json(s / "cuts.json"), langs="en")
    assert abs(probe(s / "program_en.mp4")["duration"] - 60.0) < 0.2


# ---------- pauses ----------

def test_pause_found_and_hidden_by_a_camera_change(s):
    with_pause(s)
    cuts = read_json(s / "cuts.json")
    assert pauses.silences(s) and pauses.plan_pauses(s, cuts) == []          # off by default (configs pauses.cut)
    removed = pauses.plan_pauses(s, cuts, on=True)
    assert len(removed) == 1
    r0, r1 = removed[0]
    assert 11.8 < r0 < 12.8 < r1 < 15.0 and r1 - r0 > 2                       # the camera change is inside it
    assert pauses.out_time(20.0, removed) == pytest.approx(20.0 - (r1 - r0))
    assert pauses.keep_parts(10.0, 16.0, removed) == [(10.0, r0), (r1, 16.0)]


def test_pause_on_one_camera_is_a_jump_cut(s):
    with_pause(s)
    cuts = [c for c in read_json(s / "cuts.json")]
    cuts[1]["end"] = cuts[2]["end"] = 27.6                                   # one long camera 2 shot over the pause
    cuts = [cuts[0], {**cuts[1], "end": 27.6}] + cuts[3:]
    assert pauses.plan_pauses(s, cuts, on=True) == []                        # the same camera on both sides
    assert len(pauses.plan_pauses(s, cuts, on=True, jump_cuts=True)) == 1


def test_a_change_next_to_the_pause_moves_into_it(s):
    with_pause(s)
    cuts = read_json(s / "cuts.json")
    cuts[1]["end"] = cuts[2]["start"] = 15.8                                 # the director cut 0.8 s after the pause
    removed = pauses.plan_pauses(s, cuts, on=True)
    assert len(removed) == 1
    fitted = pauses.fit_cuts(cuts, removed)
    assert removed[0][0] <= fitted[2]["start"] <= removed[0][1]


def test_program_with_a_cut_pause_stays_in_sync(s):
    with_pause(s)
    cuts = read_json(s / "cuts.json")
    removed = pauses.plan_pauses(s, cuts, on=True)
    render.render_program(s, cuts, removed=removed)
    info = probe(s / "program_nocaps.mp4")
    assert abs(info["duration"] - (60.0 - pauses.saved_seconds(removed))) < 0.1
    v = {**V1, "removed": removed, "intro": 0.0}
    add_version(s, v)
    srt = version_captions(s, get_version(s, "v1"), "ar")
    first_after = next(x for x in caption_items(s, "ar") if x["start"] > 15)
    assert re.search(re.escape(f"{int(video_time(v, first_after['start']) // 60):02d}:"), srt)
    assert video_time({**v, "intro": 4.0}, 20.0) == pytest.approx(24.0 - pauses.saved_seconds(removed))


def test_export_with_cut_pauses(s):
    from ai_director.director.export import edl, fcp_xml
    with_pause(s)
    cuts = read_json(s / "cuts.json")
    removed = pauses.plan_pauses(s, cuts, on=True)
    xml = fcp_xml(s, cuts, "t", removed)
    total = int(re.search(r"<sequence id=\"sequence-1\"><name>t</name><duration>(\d+)", xml).group(1))
    assert total == round((60.0 - pauses.saved_seconds(removed)) * 30)
    ins = [int(x) for x in re.findall(r"<in>(\d+)</in>", xml)]
    starts = [int(x) for x in re.findall(r"<start>(\d+)</start>", xml)]
    assert any(i != a for i, a in zip(ins, starts))                          # source time != timeline time
    assert edl(s, cuts, "t", removed).count("AA ") == 2                      # the sound in 2 parts


# ---------- punch-in zoom, cold open ----------

def test_zoom_on_a_laughing_close_up(s):
    ev = read_json(s / "audio_events.json")
    for e in ev:
        e["laugh"] = 0.6 if e["t"] in (20, 21) else 0.0                       # laughter inside the cam 3 shot 12.8-27.6
    write_json(s / "audio_events.json", ev)
    cuts = read_json(s / "cuts.json")
    plan = zoom_plan(s, cuts)
    assert list(plan) == [2] and plan[2]["why"] == "laughter" and plan[2]["t0"] == pytest.approx(19.0)
    assert zoom_plan(s, cuts, {**zoom_plan.__globals__["CFG"], "enabled": False}) == {}
    f = zoom_filter(plan[2], 12.8, 1280, 720)
    assert f.startswith("perspective=") and "eval=frame" in f
    render.render_program(s, cuts)
    a = subprocess.run(["ffmpeg", "-v", "error", "-ss", "26", "-i", s / "program_nocaps.mp4", "-frames:v", "1", "-f",
                        "rawvideo", "-pix_fmt", "gray", "-s", "64x36", "-"], capture_output=True).stdout
    b = subprocess.run(["ffmpeg", "-v", "error", "-ss", "26", "-i", s / "video/cam3.mp4", "-frames:v", "1", "-f",
                        "rawvideo", "-pix_fmt", "gray", "-s", "64x36", "-"], capture_output=True).stdout
    assert sum(abs(x - y) for x, y in zip(a, b)) / len(a) > 2                # pushed in: not the plain camera picture


def test_cold_open(s, monkeypatch):
    m = strongest_moment(s, 6, 12)
    rows = read_json(s / "transcript.json")
    assert m and 6 <= m[1] - m[0] <= 12
    assert any(abs(r["start"] - m[0]) < 0.01 for r in rows) and any(abs(r["end"] - m[1]) < 0.01 for r in rows)
    monkeypatch.setattr(render, "COLD", {"enabled": True, "seconds": [6, 12]})
    cold, lead = render.lead_in(s)
    assert cold == m and lead == pytest.approx(m[1] - m[0])
    render.finish(s, "program_nocaps.mp4", "out.mp4", read_json(s / "cuts.json"))
    assert abs(probe(s / "out.mp4")["duration"] - (60.0 + lead)) < 0.3


# ---------- why this shot, stats, search, podcast ----------

def test_why_this_shot(s):
    cuts = read_json(s / "cuts.json")
    why = explain(s, cuts)
    assert len(why) == len(cuts) and all(w["code"] in TEXT and w["en"] and w["ar"] for w in why)
    assert why[0]["code"] == "wide_open"
    assert why[1]["code"] == "speaker" and "Host" in why[1]["en"]             # cam 2 = SPEAKER_00 talking
    assert why[4]["code"] == "wide_laugh"                                     # the laughter at 33-37 s


def test_speaker_stats(s):
    st = speaker_stats(s)
    people = {p["speaker"]: p for p in st["people"]}
    assert set(people) == {"SPEAKER_00", "SPEAKER_01"} and abs(sum(p["share"] for p in st["people"]) - 100) < 0.2
    assert people["SPEAKER_01"]["longest"] == {"seconds": 14.5, "start": 12.5}
    assert st["laughs"] == [{"start": 33, "end": 38, "peak": 0.91}]
    tt = turns([{"speaker": "A", "start": 0, "end": 2}, {"speaker": "A", "start": 2.5, "end": 4},
                {"speaker": "B", "start": 4.1, "end": 6}])
    assert [(t["speaker"], t["start"], t["end"]) for t in tt] == [("A", 0, 4), ("B", 4.1, 6)]


def test_search_by_words(s):
    assert normal("أَهْلاً بالضيوفِ") == "اهلا بالضيوف"
    rows = read_json(s / "transcript.json")
    word = rows[1]["text"].split()[1]
    found = find_words(s, word)
    assert found and found[0]["start"] == rows[1]["start"]
    assert find_words(s, "CV") and not find_words(s, "V on")                  # Latin: from the start of a word
    assert find_words(s, "   ") == []


def test_podcast_mp3_with_chapters(s):
    write_json(s / "publish.json", {"chapters": [{"start": 0, "title_ar": "البداية", "title_en": "Start"},
                                                 {"start": 30.0, "title_ar": "الضحك", "title_en": "Laughs"}]})
    out = make_podcast(s, "v1")
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-show_format", "-of", "json", out],
                                     capture_output=True, text=True, encoding="utf-8").stdout)
    assert [c["tags"]["title"] for c in info["chapters"]] == ["البداية", "الضحك"]
    assert abs(float(info["chapters"][1]["start_time"]) - 30.0) < 0.01 and abs(float(info["format"]["duration"]) - 60) < 0.5
    assert make_podcast(s, "v1") == out                                       # made once, then reused
