# tests/test_agent.py — the Editor Agent without Ollama: a fake LLM answers turn by turn, a fake model makes the
# search vectors. Runs on copies of the mock session (never writes into the mock).
import json
import shutil
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import TypeAdapter, ValidationError

from ai_director.agent import search as S
from ai_director.agent.agent import chat
from ai_director.agent.prompts import speaker_lines
from ai_director.agent.tools import TOOLS, ClipArgs, Job, get_scenes, ScenesArgs, to_sentences, typed_times
from ai_director.common import schemas
from ai_director.common.io import read_json, write_json, write_jsonl
from ai_director.common.paths import MOCK

TOPICS = [("salar", "مرتب"), ("cv", "السي في"), ("welcome", "أهلا"), ("thank", "شكرا")]


def fake_embed(texts, calls=None):
    """A tiny stand-in for bge-m3: one number per topic (how often its words appear)."""
    if calls is not None:
        calls.append(len(texts))
    v = np.array([[sum(t.lower().count(w) for w in topic) + 0.01 for topic in TOPICS] for t in texts], "float32")
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def scripted(*turns):
    """A fake LLM: answers turn by turn. A turn is a text (final answer) or [(tool name, arguments), ...]."""
    sent = []

    def ask(messages, tools):
        sent.append({"messages": list(messages), "tools": tools})
        t = turns[min(len(sent), len(turns)) - 1]
        if isinstance(t, str):
            return SimpleNamespace(role="assistant", content=t, tool_calls=None)
        return SimpleNamespace(role="assistant", content="", tool_calls=[
            SimpleNamespace(function=SimpleNamespace(name=n, arguments=a)) for n, a in t])
    ask.sent = sent
    return ask


@pytest.fixture
def s(tmp_path):
    shutil.copytree(MOCK, tmp_path / "s00")               # never write into the mock
    return tmp_path / "s00"


def tool_results(ask):
    """What the tools answered (the "tool" messages the LLM read), in order."""
    return [json.loads(m["content"]) for m in ask.sent[-1]["messages"] if isinstance(m, dict) and m["role"] == "tool"]


def test_windows_are_whole_sentences(s):
    segs = read_json(s / "transcript.json")
    w = S.windows(segs)
    assert [(x["start"], x["end"]) for x in w] == [(1.0, 27.0), (12.5, 33.0), (22.6, 52.0), (38.0, 59.5)]
    starts, ends = {r["start"] for r in segs}, {r["end"] for r in segs}
    assert all(x["start"] in starts and x["end"] in ends and x["end"] - x["start"] <= 30 for x in w)


def test_search_finds_the_topic_and_caches_the_index(s):
    calls = []
    emb = lambda texts: fake_embed(texts, calls)
    m = S.search(s, "المرتبات", embed=emb)
    assert (m[0]["start"], m[0]["end"], m[0]["speaker"]) == (22.6, 52.0, "SPEAKER_01")
    assert "salary" in m[0]["translation"].lower()
    assert all(a["end"] <= b["start"] or b["end"] <= a["start"] for a in m for b in m if a is not b)  # no overlaps
    assert calls == [4, 1]                                    # 4 pieces + the question
    S.search(s, "CV", embed=emb)
    assert calls == [4, 1, 1]                                 # the index is reused: only the question
    rows = read_json(s / "transcript.json")
    write_json(s / "transcript.json", rows[:6])               # the transcript changed -> a new index
    S.search(s, "CV", embed=emb)
    assert calls[-2:] == [2, 1]                                # 2 pieces (rows 1-33 s) + the question


def test_clip_arguments():
    a = ClipArgs(start=10, end=40, format="vertical", focus_speaker="")
    assert (a.format, a.focus_speaker, a.captions) == ("9:16", None, "ar+en")
    with pytest.raises(ValidationError, match="5-180 s"):
        ClipArgs(start=10, end=12)
    with pytest.raises(ValidationError):
        ClipArgs(start=10, end=400)
    assert typed_times("اعمل كليب من 0:40 لـ 0:55") == [(40, 55)]
    assert typed_times("from 1:02:00") == [(3720, 3900)] and typed_times("make a 1-minute clip") == []


def test_to_sentences():
    segs = [{"start": 10.0, "end": 14.0}, {"start": 15.0, "end": 20.0}]
    assert to_sentences(segs, 12.0, 17.5) == (10.0, 20.0)    # both edges inside a sentence -> whole sentences
    assert to_sentences(segs, 14.5, 21.0) == (14.5, 21.0)    # in pauses -> unchanged


def test_prompt_has_the_real_people(s):
    lines = speaker_lines(Job(s).speakers)
    assert "SPEAKER_00: host, Host, close-up camera 2" in lines and "SPEAKER_01: guest, Guest, close-up camera 3" in lines
    assert speaker_lines([{"id": "SPEAKER_03", "role": "other", "name": "", "camera": None, "talk_seconds": 4,
                           "description": ""}]) == "- SPEAKER_03: other, no close-up camera, talks 4 s"
    assert [t["function"]["name"] for t in TOOLS] == ["search_transcript", "get_scenes", "get_speakers",
                                                      "make_clip", "restyle_video", "list_clips"]


def test_the_demo_request_renders_a_vertical_clip_of_the_guest(s):
    from ai_director.ingest.probe import probe
    ask = scripted([("search_transcript", {"query": "المرتبات"})],
                   [("make_clip", {"start": 22.6, "end": 52.0, "format": "9:16", "focus_speaker": "SPEAKER_01",
                                   "title": "نصيحة المرتبات"})],
                   "عملت لك كليب عمودي 29 ثانية: نصيحة المرتبات")
    out = chat(s, "اعمل ريل عن المرتبات وركز على الضيف", ask=ask, embed=fake_embed)
    assert out["reply"].startswith("عملت") and [x["summary"] for x in out["steps"]] == ["found 1 moments",
                                                                                        "rendered clips/c2.mp4"]
    c = out["clips"][0]
    assert (c["id"], c["start"], c["end"], c["format"], c["focus_speaker"]) == ("c2", 22.6, 52.0, "9:16", "SPEAKER_01")
    v = probe(s / c["file"])
    assert (v["width"], v["height"]) == (720, 1280) and abs(v["duration"] - 29.4) < 0.2
    TypeAdapter(list[schemas.Clip]).validate_python(read_json(s / "clips.json"))   # follows the contract
    assert [x["id"] for x in read_json(s / "clips.json")] == ["c1", "c2"]
    assert tool_results(ask)[1]["shows"] == "camera 3 (SPEAKER_01)"
    assert "SPEAKER_01: guest" in ask.sent[0]["messages"][0]["content"]                   # the rules know the people


def test_invented_times_are_refused_then_fixed(s):
    ask = scripted([("make_clip", {"start": 0, "end": 30})],                 # no search yet: invented times
                   [("search_transcript", {"query": "CV"})],
                   [("make_clip", {"start": 12.5, "end": 33.0})], "Done")
    out = chat(s, "Make a clip about the CV", ask=ask, render=False, embed=fake_embed)
    assert out["steps"][0]["summary"].startswith("error: these times did not come from a tool")
    assert [(c["start"], c["end"], c["format"]) for c in out["clips"]] == [(12.5, 33.0, "16:9")]
    assert not (s / "clips/c2.mp4").exists()                                  # render=False: nothing made


def test_no_keyword_overrides(s):
    """Eslam's version forced 9:16 for "short" and 60 s for any "دقيقة"; now the LLM's arguments are used."""
    ask = scripted([("search_transcript", {"query": "salaries"})],
                   [("make_clip", {"start": 22.6, "end": 52.0, "format": "16:9"})], "Here it is")
    out = chat(s, "Make a short clip about salaries", ask=ask, render=False, embed=fake_embed)
    assert out["clips"][0]["format"] == "16:9"
    ask = scripted([("search_transcript", {"query": "المرتبات"})],
                   [("make_clip", {"start": 22.6, "end": 52.6})], "تمام")
    out = chat(s, "اعمل كليب نصف دقيقة عن المرتبات", ask=ask, render=False, embed=fake_embed)
    c = out["clips"][0]
    assert (c["start"], c["end"]) == (22.6, 56.0)                 # ~30 s (the end moved to the end of its sentence)


def test_typed_times_end_of_video_and_unknown_people(s):
    ask = scripted([("make_clip", {"start": 40, "end": 55})], "ok")
    out = chat(s, "اعمل كليب من 0:40 لـ 0:55", ask=ask, render=False)
    assert (out["clips"][0]["start"], out["clips"][0]["end"]) == (38.0, 56.0)     # moved to whole sentences
    ask = scripted([("search_transcript", {"query": "salary"})],
                   [("make_clip", {"start": 38.0, "end": 100.0}),                 # after the end of the video
                    ("make_clip", {"start": 38.0, "end": 52.0, "focus_speaker": "SPEAKER_07"})], "ok")
    out = chat(s, "two clips about salaries", ask=ask, render=False, embed=fake_embed)
    first, second = tool_results(ask)[1:]
    assert (first["end"], first["notes"]) == (60.0, ["end moved to the end of the video (60.0 s)"])
    assert "unknown speaker 'SPEAKER_07'. Use one of: SPEAKER_01 (guest Guest), SPEAKER_00 (host Host)" in second["error"]


def test_unclear_request_gets_a_question(s):
    ask = scripted("تحب أركز على مين، ولا أعمل كليب عن موضوع معين؟")
    out = chat(s, "اعمل كليب أحسن لحظة", ask=ask)
    assert out == {"reply": "تحب أركز على مين، ولا أعمل كليب عن موضوع معين؟", "steps": [], "clips": []}
    assert ask.sent[0]["tools"]                                                 # the LLM decided, with the tools


def test_errors_never_crash(s, tmp_path):
    def off(messages, tools):
        raise ConnectionError("Ollama is not running")
    out = chat(s, "Make a clip about salaries", ask=off)
    assert out["reply"].startswith("Sorry, I can't reach the AI model") and out["clips"] == []
    assert chat(tmp_path / "nothing", "اعمل كليب", ask=off)["reply"].startswith("عذراً، الجلسة دي مش جاهزة")
    ask = scripted([("cut_video", {}), ("search_transcript", '{"query": "salary"}'),   # unknown tool, JSON text
                    ("get_scenes", {"start": 30, "end": 10})], "ok")                 # bad arguments
    out = chat(s, "salary", ask=ask, embed=fake_embed)
    assert [x["summary"][:20] for x in out["steps"]] == ["error: there is no t", "found 1 moments",
                                                         "error: wrong argumen"]
    (s / "program_nocaps.mp4").unlink()                                       # FFmpeg will fail
    ask = scripted([("search_transcript", {"query": "salary"})], [("make_clip", {"start": 22.6, "end": 52.0})], "ok")
    out = chat(s, "salary clip", ask=ask, embed=fake_embed)
    assert out["steps"][1]["summary"].startswith("error: RuntimeError") and out["clips"] == []


def test_at_most_6_tool_calls_then_it_must_answer(s):
    ask = scripted([("get_speakers", {})])                                    # a model that never stops
    out = chat(s, "who talks?", ask=ask)
    assert len(out["steps"]) == 6 and ask.sent[-1]["tools"] == []             # the last turn has no tools
    assert out["reply"] == "Sorry, I couldn't finish that. Please ask in a simpler way."
    ask = scripted([("search_transcript", {"query": "salary"})], [("make_clip", {"start": 22.6, "end": 52.0})] * 4,
                   "ok")
    out = chat(s, "4 clips", ask=ask, render=False, embed=fake_embed)
    assert len(out["clips"]) == 3 and out["steps"][-1]["summary"] == "error: at most 3 clips per request"
    assert [c["id"] for c in out["clips"]] == ["c2", "c3", "c4"]


def test_list_clips_and_scenes(s, tmp_path):
    ask = scripted([("list_clips", {})], [("make_clip", {"start": 27.5, "end": 48.0, "format": "9:16"})], "ok")
    out = chat(s, "make highlight h1 vertical", ask=ask, render=False)          # times from list_clips are allowed
    listed = tool_results(ask)[0]["clips"]
    assert listed[0]["title_en"] == "The salary question" and listed[-1]["id"] == "c1"
    assert out["clips"][0]["start"] == 27.5
    t = tmp_path / "t"
    t.mkdir()
    shutil.copy(MOCK / "session.json", t)
    rows = [{"t": 5.0 * k, "scene": "talk", "event": "talking", "energy": 0.2, "mode": "conversation",
             "raw_mode": "conversation", "highlight": False} for k in range(30)]
    rows[25].update(event="laughter", energy=0.9, highlight=True)
    write_jsonl(t / "scene.jsonl", rows)
    got = get_scenes(Job(t), ScenesArgs(start=0, end=200))["scenes"]
    assert len(got) == 20 and 125.0 in [r["t"] for r in got] and got == sorted(got, key=lambda r: r["t"])


def test_restyle_makes_a_new_full_video(s):
    from ai_director.ingest.probe import probe
    ask = scripted([("restyle_video", {})], [("restyle_video", {"focus_speaker": "SPEAKER_01"})], "Done")
    out = chat(s, "show the guest more in the whole video", ask=ask)
    assert out["steps"][0]["summary"] == "error: give focus_speaker or mode (or both)"
    assert out["steps"][1]["summary"] == "rendered program_v2.mp4"
    assert abs(probe(s / "program_v2.mp4")["duration"] - 60.0) < 0.2 and (s / "program.mp4").exists()
    v2, v1 = read_json(s / "cuts_v2.json"), read_json(s / "cuts.json")
    on = lambda cuts: sum(c["end"] - c["start"] for c in cuts if c["cam"] == 3)  # the guest's camera
    assert on(v2) >= on(v1)
