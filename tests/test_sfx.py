import re
import shutil
import subprocess

import numpy as np
import pytest

from ai_director.common.io import read_json, write_json
from ai_director.common.paths import MOCK, ROOT
from ai_director.director.sfx import CFG, choose, clip_events, job_volume, plan_trailer, set_gains, visible_cuts

SFX = ROOT / "assets" / "sfx"
FILES = sorted(p.name for p in SFX.iterdir() if p.is_file() and p.name != "SOURCES.md")


def sound_length(name):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                 str(SFX / name)], capture_output=True, text=True).stdout.strip())


def loudest(x, sr=48000):
    """The loudest momentary loudness (EBU R128, 400 ms) of samples x (n, 2): how loud a short sound seems."""
    pad = np.vstack([np.zeros((sr // 2, 2)), x, np.zeros((sr, 2))]).astype(np.float32)
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-v", "verbose", "-f", "f32le", "-ar", str(sr), "-ac",
                          "2", "-i", "-", "-af", "ebur128=framelog=verbose", "-f", "null", "-"], input=pad.tobytes(),
                         capture_output=True).stderr.decode("utf-8", "replace")
    return max(float(m) for m in re.findall(r"M:\s*(-?[\d.]+)", err))


def source_rows():
    """The file rows of SOURCES.md's table: {file name: the whole row}."""
    rows = {}
    for line in (SFX / "SOURCES.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*`([^`]+)`\s*\|", line)
        if m:
            rows[m.group(1)] = line
    return rows


def test_every_sound_has_a_source_and_a_license():
    rows = source_rows()
    assert FILES, "assets/sfx has no sounds"
    assert set(FILES) == set(rows), f"not in SOURCES.md: {set(FILES) - set(rows)}; no file: {set(rows) - set(FILES)}"
    for name, row in rows.items():
        assert "CC0" in row and "https://" in row, f"{name}: its row needs the source page and the license"


def test_two_whooshes_two_pops_one_hit():                            # a trailer has one end card: one hit
    for kind, n in (("whoosh", 2), ("pop", 2), ("hit", 1)):
        assert [f for f in FILES if f.startswith(kind + "_")] == [f"{kind}_{k}.ogg" for k in range(1, n + 1)], kind


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not on PATH")
@pytest.mark.parametrize("name", FILES)
def test_one_format_and_one_loudness(name):
    info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,sample_rate,channels",
                           "-of", "csv=p=0", str(SFX / name)], capture_output=True, text=True).stdout.strip()
    assert info == "vorbis,48000,2", info
    x = samples(SFX / name)
    m, peak = loudest(x), 20 * np.log10(np.abs(x).max())
    assert abs(m - (-21.0)) < 0.5 and peak < -1.0, (round(m, 1), round(float(peak), 1))   # sfx.LIBRARY_LOUDNESS
    assert len(x) / 48000 < 1.0                                      # short effects only


# ---------------------------------------------------------------- where effects go (events) and how many (choose)
def shot(a, b, cam, **kw):
    return {"start": a, "end": b, "cam": cam, **kw}


def test_a_cut_is_where_the_picture_changes():
    shots = [shot(0, 4, 1), shot(4, 9, 2), shot(9, 12, 2, split=[2, 3]), shot(12, 20, 2)]
    assert visible_cuts(shots, "16:9") == [4, 9, 12]                 # a split starting and ending is a cut
    assert visible_cuts(shots, "9:16") == [4]                        # 9:16 never splits: camera 2 all along
    moving = [shot(0, 5, 2, crop_x=0.3), shot(5, 9, 2, crop_x=0.7), shot(9, 12, 2, crop_x=0.7)]
    assert visible_cuts(moving, "1:1") == [5]                        # the square moves to the other person


def test_clip_events_from_the_ai_edit_and_its_captions():
    events = clip_events(MOCK, 12.0, 27.0, fmt="16:9", source="program")
    assert [e["t"] for e in events if e["kind"] == "cut"] == [0.8]   # the mock edit changes camera at 12.8 s
    from ai_director.audio.subtitles import caption_items
    new_lines = [x for x in caption_items(MOCK, "ar+en") if 12.0 < x["start"] < 27.0]
    assert len([e for e in events if e["kind"] == "caption"]) == len(new_lines) > 0
    assert not [e for e in clip_events(MOCK, 12.0, 27.0, source=3) if e["kind"] == "cut"]     # one camera
    assert not [e for e in clip_events(MOCK, 12.0, 27.0, langs="none") if e["kind"] == "caption"]


def test_the_trailer_gets_every_join_and_the_end_card():
    effects = plan_trailer("unused", [3.9, 2.7, 9.5, 9.3, 8.4], "medium")      # joins 2.7 s apart, 5 effects in 37 s
    assert [(e["t"], e["kind"], e["sound"]) for e in effects] == [
        (3.9, "cut", "whoosh_1.ogg"), (6.6, "cut", "whoosh_2.ogg"), (16.1, "cut", "whoosh_1.ogg"),
        (25.4, "cut", "whoosh_2.ogg"), (33.8, "title", "hit_1.ogg")]            # no count limit, no gap: all of them
    assert effects[0]["at"] == 3.85 and effects[-1]["at"] == 33.8               # the whoosh peaks on the join


MANY = {"per_minute": 60}                                            # tests of the other rules: no rate limit


def test_choose_keeps_away_from_the_edges_and_keeps_a_gap():
    events = [{"t": t, "kind": "cut"} for t in (0.2, 2.0, 3.0, 6.5, 9.8)]
    assert [e["t"] for e in choose(events, length=10.0, cfg=MANY)] == [3.0, 6.5]   # 0.2, 9.8: edges; 2.0: too close


def test_choose_spreads_the_effects_over_the_clip():
    events = [{"t": 2.0 + k, "kind": "caption"} for k in range(30)]   # a new caption line every second
    assert [e["t"] for e in choose(events, length=34.0)] == [8.0, 17.0, 25.0]   # not bunched at the start


def test_choose_prefers_the_cut():
    events = [{"t": 5.0, "kind": "caption"}, {"t": 5.5, "kind": "cut"}]
    assert [e["kind"] for e in choose(events, length=20.0)] == ["cut"]


def test_choose_caps_effects_per_minute():
    events = [{"t": 1.0 + 3.0 * k, "kind": "cut"} for k in range(40)]   # one every 3 s for 2 minutes
    chosen = choose(events, length=125.0)
    times = [e["t"] for e in chosen]
    assert max(sum(a <= b < a + 60 for b in times) for a in times) <= 6
    assert len(chosen) >= 10                                          # still spread over both minutes
    short = choose([{"t": 1.0 + 3.0 * k, "kind": "cut"} for k in range(10)], length=31.0)
    assert len(short) == 3                                            # a rate: 6 a minute = 3 in a 30 s clip


def test_the_two_sounds_take_turns_and_start_early():
    chosen = choose([{"t": t, "kind": "cut"} for t in (2.0, 6.0, 10.0)] + [{"t": 14.0, "kind": "caption"}], 20.0,
                    cfg=MANY)
    assert [e["sound"] for e in chosen] == ["whoosh_1.ogg", "whoosh_2.ogg", "whoosh_1.ogg", "pop_1.ogg"]
    assert chosen[0]["at"] == 1.95 and chosen[-1]["at"] == 14.0       # a whoosh peaks on the cut
    assert all((SFX / e["sound"]).exists() for e in chosen)


# ---------------------------------------------------------------- the mix: the upload's choice, levels, clips, trailer
def test_the_upload_turns_effects_on(tmp_path):
    assert job_volume(tmp_path) is None                                         # no upload.json
    for choice, volume in (({"on": True, "volume": "high"}, "high"), ({"on": True}, "medium"),
                           ({"on": False, "volume": "high"}, None), ({"on": True, "volume": "loud"}, None)):
        write_json(tmp_path / "upload.json", {"sound_effects": choice})
        assert job_volume(tmp_path) == volume, choice


def test_the_volume_sets_how_far_under_the_speech():
    effects = [{"at": 2.0, "sound": "pop_1.ogg"}, {"at": 9.9, "sound": "whoosh_1.ogg"}]
    assert [e["gain_db"] for e in set_gains(effects, "unused", "medium")] == [1.0, 1.0]   # -14 LUFS - 6 dB + 21
    assert [e["gain_db"] for e in set_gains(effects, "unused", "low")] == [-3.0, -3.0]    # the same while people talk


needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not on PATH")


@pytest.fixture
def session(tmp_path):
    shutil.copytree(MOCK, tmp_path / "s00")                                     # never write into the mock
    return tmp_path / "s00"


def choose_at_upload(s, **choice):
    write_json(s / "upload.json", {**read_json(s / "upload.json"), "sound_effects": choice})


def samples(path):
    """A file's sound: float samples, (n, 2), 48 kHz."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "2", "-ar", "48000", "-f", "f32le",
                          "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2)


def level(x):
    return float(20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-12))


def heard(sound, e):
    """How loud effect e is in `sound` (where nothing else plays: the file with the effect minus the same file without
    it, or a silent stretch), and how loud it should be: the effect file's level + its gain."""
    a = int(round(e["at"] * 48000))
    return level(sound[a:a + int(sound_length(e["sound"]) * 48000)]), level(samples(SFX / e["sound"])) + e["gain_db"]


@needs_ffmpeg
def test_off_renders_the_clip_as_before(session, monkeypatch):
    from ai_director.director import render
    cmds = []
    monkeypatch.setattr(render, "run", lambda cmd, **kw: cmds.append(cmd))
    render.render_clip(session, 12.0, 27.0, "clips/a.mp4")                      # nothing chosen at upload
    choose_at_upload(session, on=False, volume="high")
    render.render_clip(session, 12.0, 27.0, "clips/a.mp4")                      # chosen off
    choose_at_upload(session, on=True, volume="high")
    render.render_clip(session, 12.0, 27.0, "clips/a.mp4", sfx=False)           # on, but not here (a trailer part)
    render.render_clip(session, 12.0, 27.0, "clips/a.mp4")                      # on
    assert cmds[0] == cmds[1] == cmds[2] and "-af" in cmds[0]                   # one FFmpeg run, the loudness as -af
    uses = lambda cmd: any(str(SFX) in str(x) for x in cmd)                      # noqa: E731
    assert not uses(cmds[0]) and uses(cmds[3])


@needs_ffmpeg
def test_effects_play_on_time_at_their_level(session):
    from ai_director.director.render import render_clip
    from ai_director.director.sfx import plan_clip
    off = samples(render_clip(session, 5.0, 45.0, "clips/off.mp4", sfx=False))
    on = samples(render_clip(session, 5.0, 45.0, "clips/on.mp4", sfx="low"))   # low: under the limiter
    loud = samples(render_clip(session, 5.0, 45.0, "clips/loud.mp4", sfx="high"))
    assert 20 * np.log10(np.abs(loud).max()) < -0.5                             # high: the limiter, no clipping
    effects = plan_clip(session, 5.0, 45.0, "16:9", "program", "ar+en", "low")
    assert len(effects) == 4                                                    # whooshes, while somebody talks
    n = min(len(on), len(off))
    added = on[:n] - off[:n]                                                    # the effects alone: same speech
    wants, spans = [], []
    for e in effects:
        got, want = heard(added, e)
        assert abs(got - want) < 1.5, (e, round(got, 1), round(want, 1))         # at its time, at its level
        a = int(round(e["at"] * 48000))
        m = loudest(added[a:a + int(sound_length(e["sound"]) * 48000)])
        assert abs(m - (-14 + CFG["levels"]["low"])) < 1.5, (e, m)              # 10 dB under the speech (-14 LUFS)
        a = int(round(e["at"] * 48000))
        wants.append(want)
        spans.append((a, a + int(sound_length(e["sound"]) * 48000) + 2400))     # + 50 ms of the encoder's smear
    step = 4800                                                                 # 0.1 s; from 0.1 s on: the first
    others = [level(added[k:k + step]) for k in range(step, n - step, step)    # frames of a mono (off) and a stereo
              if not any(k < b and a < k + step for a, b in spans)]             # (on) file are encoded differently
    assert max(others) < min(wants) - 10, max(others)                          # no other effect anywhere


@needs_ffmpeg
def test_the_trailer_gets_its_effects_after_the_parts_are_joined(session, monkeypatch):
    from ai_director.highlights import trailer
    seen, join = {}, trailer.join

    def spy(s, parts, out, *args, effects=None):
        seen[out] = effects
        return join(s, parts, out, *args, effects=effects)
    monkeypatch.setattr(trailer, "join", spy)
    choose_at_upload(session, on=True, volume="medium")
    ask = lambda p: trailer.Answer(moments=[trailer._Moment(first=k, last=k) for k in (1, 6, 9)],  # noqa: E731
                                   title_ar="عنوان", title_en="Name")
    out = trailer.make_trailer(session, ask=ask)
    lengths = [m["end"] - m["start"] for m in out["moments"]]
    for fmt, tag in (("16:9", "169"), ("9:16", "916")):
        effects = seen[f"trailer/trailer_{tag}.mp4"]
        joins, titles = [e for e in effects if e["kind"] == "cut"], [e for e in effects if e["kind"] == "title"]
        bounds = [sum(lengths[:k]) for k in range(1, len(lengths))]            # where one part ends, the next begins
        assert len(joins) == len(bounds) and len(titles) == 1 and len(effects) == len(bounds) + 1   # nothing else
        assert all(abs(e["t"] - b) < 0.1 for e, b in zip(joins, bounds)), (fmt, joins, bounds)
        card_at = titles[0]["t"]
        sound = samples(session / out["files"][fmt])
        assert abs(card_at - (len(sound) / 48000 - trailer.CFG["end_card"])) < 0.05     # the end card's first frame
        got, want = heard(sound, titles[0])                                     # the end card is silent: the hit alone
        assert abs(got - want) < 1.5, (round(got, 1), round(want, 1))
