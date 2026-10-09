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
    a = ClipArgs(start=10, end=40, format="vertical", focus_speaker="", seconds=0)
    assert (a.format, a.focus_speaker, a.captions, a.seconds) == ("9:16", None, None, None)   # None = not asked
    assert ClipArgs(start=10, end=40, captions="none", seconds="null").captions == "none"     # "none" = no captions
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
    assert [(x["id"], x["captions"]) for x in read_json(s / "clips.json")] == [("c1", "none"), ("c2", "ar")]
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
    """Eslam's version forced 9:16 for "short" and 60 s for any "دقيقة"; now "short" changes nothing and the code
    reads the length the user typed ("نصف دقيقة" = 30 s)."""
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
    assert listed[0]["title_en"] == "The salary question" and (listed[-1]["id"], listed[-1]["captions"]) == ("c1", "none")
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


def test_vague_restyle_asks_a_question(s):
    """"make the video better" became a restyle with a person nobody asked for (eval 2026-10-09): now the tool says
    nothing would change and the agent asks; a real style ("more reactions") still works."""
    nobody = lambda m: {"person": None, "level": None, "share": None}
    ask = scripted([("restyle_video", {"focus_speaker": "SPEAKER_01", "mode": "conversation"})],
                   "What would you like to change: show someone more, or more reactions?")
    out = chat(s, "make the video better", ask=ask, render=False, read=nobody)
    assert out["steps"][0]["summary"].startswith("error: the user named no person and no style")
    assert out["reply"].endswith("?") and not out["clips"]
    ask = scripted([("restyle_video", {"mode": "reaction"})], "Done")
    out = chat(s, "more reactions in the whole video", ask=ask, render=False, read=nobody)
    assert out["steps"][0]["summary"] == "rendered program_v2.mp4"


def test_what_the_user_asked():
    """asks.py: the language, the length and the caption languages are read by the code (not the LLM)."""
    from ai_director.agent.asks import asked_captions, asked_length, language, reply_language, title_problem
    lengths = {"Make a clip about salaries, it should be 1-2 minutes": (60, 120), "Cut a 30-second clip": (30, 30),
               "make a 1 minute clip": (60, 60), "a minute and a half": (90, 90), "clip between 60 and 90 seconds":
               (60, 90), "اعمل كليب دقيقة عن المرتبات": (60, 60), "اعمل كليب دقيقتين": (120, 120),
               "كليب دقيقة ونص": (90, 90), "نص دقيقة": (30, 30), "من دقيقة لدقيقتين": (60, 120), "٢ دقيقة": (120, 120),
               "اعمل ريل 30 ثانية": (30, 30), "e3mel clip de2i2a": (60, 60), "make a short clip": None,
               "it should be 1.20 minutes": (80, 80), "1:20 minutes": (80, 80), "1.5 minutes": (90, 90),
               "1 minute 20 seconds": (80, 80), "دقيقة و20 ثانية": (80, 80), "دقيقتين و 30 ثانية": (150, 150),
               "اعمل كليب من الدقيقة 5": None, "from 2:30 to 3:00": None, "two clips, 9:16": None}
    assert {m: asked_length(m) for m in lengths} == lengths
    assert typed_times("a 1:20 minutes clip") == [] and typed_times("from 1:20 to 2:00") == [(80, 120)]   # length, time
    captions = {"make a clip with english subtitles": "en", "English clip with Arabic captions": "ar",
                "arabic and english captions": "ar+en", "captions in both languages": "ar+en",
                "no captions please": "none", "اعمل كليب بدون ترجمة": "none", "مع ترجمة انجليزي": "en",
                "ترجمة عربي وانجليزي": "ar+en", "make a clip with subtitles": None, "a clip about salaries": None}
    assert {m: asked_captions(m) for m in captions} == captions
    assert [language(m) for m in ("make a clip about الذكاء الاصطناعي", "اعمل clip عن الـ AI", "e3mel clip 3an el mortabat",
                                  "the 2nd clip, 3 minutes", "كليب AI")] == ["en", "ar", "ar", "en", "ar"]
    assert reply_language("Clip c1 (16:9): clips/c1.mp4, SPEAKER_01 talks") == "en"
    assert title_problem("ال薪水 والخبرة", "ar", "") == "the title has Chinese letters"
    assert title_problem("المرتبات في سوق العمل", "en", "").startswith("the user wrote in English")
    assert title_problem("AI والوظائف", "ar", "") == "" and title_problem("Salaries in Cairo", "en", "") == ""
    assert title_problem("الشركات بتحب تشوف شغل", "ar", "طب الشركات بتحب تشوف شغل حقيقي").startswith("the title is copied")


def test_the_code_makes_the_asked_length(s):
    """The LLM copies the moment's times (22.6-52.0, like qwen3:8b did): the code makes the clip as long as asked."""
    def clip(message, **args):
        ask = scripted([("search_transcript", {"query": "salary"})],
                       [("make_clip", {"start": 22.6, "end": 52.0, **args})], "ok")
        out = chat(s, message, ask=ask, render=False, embed=fake_embed)
        c, res = out["clips"][0], tool_results(ask)[1]
        return c["start"], c["end"], res["notes"]
    assert clip("Make a 20-second clip about salaries") == (22.6, 43.5, ["20 s long, as the user asked"])
    assert clip("a 20-30 seconds clip about salaries", seconds=25)[:2] == (22.6, 48.0)     # the LLM's pick, inside
    assert clip("a 20-30 seconds clip about salaries", seconds=90)[:2] == (22.6, 48.0)     # outside -> the middle
    assert clip("Make a clip about salaries", seconds=60)[:2] == (22.6, 52.0)       # no length asked: seconds ignored
    assert clip("salary clip, a few seconds long", seconds=25)[:2] == (22.6, 48.0)  # a length the code can't read
    assert clip("اعمل كليب دقيقة عن المرتبات") == (0.0, 60.0, ["60 s long, as the user asked"])   # 60 s video
    assert clip("a 2 second clip about salaries") == (22.6, 33.0, ["a clip can be 5-180 s long, so it is 5 s"])


def test_captions_from_the_request(s):
    def captions(message, **args):
        ask = scripted([("search_transcript", {"query": "salary"})],
                       [("make_clip", {"start": 22.6, "end": 52.0, **args})], "ok")
        chat(s, message, ask=ask, render=False, embed=fake_embed)
        return tool_results(ask)[1]["captions"]
    assert captions("Make a clip about salaries", captions="ar") == "ar+en"          # English: Arabic + English
    assert captions("اعمل كليب عن المرتبات", captions="ar+en") == "ar"              # Arabic: Arabic only
    assert captions("salary clip with english subtitles", captions="ar+en") == "en"  # what the user typed wins
    assert captions("اعمل كليب عن المرتبات بدون ترجمة") == "none"
    assert captions("salary clip, subtitles EN only", captions="en") == "en"         # words the code can't read: LLM


def test_bad_titles_are_written_again(s):
    ask = scripted([("search_transcript", {"query": "salary"})],
                   [("make_clip", {"start": 22.6, "end": 52.0, "title": "المرتبات"})],      # Arabic for an English user
                   [("make_clip", {"start": 22.6, "end": 52.0, "title": "First-year salary advice"})], "Done")
    out = chat(s, "Make a clip about salaries", ask=ask, render=False, embed=fake_embed)
    assert out["steps"][1]["summary"].startswith("error: the user wrote in English: write the title in English")
    assert out["clips"][0]["title"] == "First-year salary advice"
    bad = [("make_clip", {"start": 22.6, "end": 52.0, "title": "ال薪水"})]
    ask = scripted([("search_transcript", {"query": "salary"})], bad, bad, bad, "تمام")
    out = chat(s, "اعمل كليب عن المرتبات", ask=ask, render=False, embed=fake_embed)
    assert [x["summary"][:35] for x in out["steps"][1:]] == ["error: the title has Chinese letter"] * 2 + ["rendered clips/c2.mp4"]
    assert out["clips"][0]["title"] == "الشركات بتحب تشوف شغل حقيقي طب"         # 3rd time: the first words said


def test_an_answer_in_the_wrong_language_is_asked_again(s):
    ask = scripted([("search_transcript", {"query": "salary"})],
                   [("make_clip", {"start": 22.6, "end": 52.0, "title": "Salary advice"})],
                   "عملت لك الكليب اللي طلبته: Salary advice", "Here is your clip: Salary advice (29 s)")
    out = chat(s, "Make a clip about salaries", ask=ask, render=False, embed=fake_embed)
    assert out["reply"] == ("Here is your clip: Salary advice (29 s)\n"
                            "- Salary advice (c2): 29 s, horizontal 16:9, captions: Arabic + English")
    assert ask.sent[-1]["tools"] == [] and "again in English" in ask.sent[-1]["messages"][-1]["content"]
    ask = scripted("أكيد! 你好 تحب أركز على مين؟")                                  # Chinese letters, asked again ...
    assert chat(s, "اعمل كليب أحسن لحظة", ask=ask)["reply"] == "أكيد!  تحب أركز على مين؟"   # ... still there: removed


def test_who_to_show_reader():
    """read_focus(): the LLM's answer is checked: "not_asked" = nobody, a share only if the user typed that number."""
    from ai_director.agent.asks import FocusWish, focus_wish
    assert focus_wish(FocusWish(person="guest", level="mostly", share=70), "the guest 70% of the time") == \
        {"person": "guest", "level": "mostly", "share": 70}
    assert focus_wish(FocusWish(person="guest", level="mostly", share=70), "mostly the guest")["share"] is None
    assert focus_wish(FocusWish(person="not_asked", level="only", share=None), "a clip about salaries") == \
        {"person": "", "level": None, "share": None}


def focus_clip(s, wish, message="a clip about salaries", fmt="16:9", render=False, **args):
    """One clip of the salary moment (22.6-52.0 s), the reader's answer = wish. Returns (clip, tool result)."""
    ask = scripted([("search_transcript", {"query": "salary"})],
                   [("make_clip", {"start": 22.6, "end": 52.0, "format": fmt, **args})], "ok")
    if fmt == "9:16":
        message = "a vertical " + message.removeprefix("a ")             # the code reads the format from the message
    out = chat(s, message, ask=ask, render=render, embed=fake_embed, read=lambda m: wish)
    return out["clips"][0], tool_results(ask)[1]


def test_mostly_the_guest_is_the_ai_edit_with_a_boost(s):
    from ai_director.ingest.probe import probe
    guest = {"person": "guest", "level": "mostly", "share": None}            # 75 % (configs agent.focus_share)
    c, res = focus_clip(s, guest, focus_speaker="SPEAKER_01", render=True)
    on = int(res["shows"].split("on screen ")[1].split("%")[0])
    assert res["shows"].startswith("the AI edit with SPEAKER_01 (camera 3)") and on >= 75 and res["notes"] == []
    assert c["focus_speaker"] == "SPEAKER_01" and abs(probe(s / c["file"])["duration"] - 29.4) < 0.2
    c, res = focus_clip(s, {**guest, "level": "more"}, focus_speaker="SPEAKER_01")   # 60 %: the edit already has 64 %
    assert "on screen 68%" in res["shows"]                       # 64 % before the split screen at 37-41 s (2026-10-09)
    c, res = focus_clip(s, {**guest, "share": 95}, focus_speaker="SPEAKER_01")       # more than the rules allow
    assert res["notes"][-1].endswith("the most the editing rules give here (asked 95%)")
    c, res = focus_clip(s, guest, fmt="9:16", focus_speaker="SPEAKER_01", render=True)
    assert (probe(s / c["file"])["width"], probe(s / c["file"])["height"]) == (720, 1280)


def test_only_and_nobody(s):
    c, res = focus_clip(s, {"person": "guest", "level": "only", "share": None})       # the agent forgot the id
    assert (c["focus_speaker"], res["shows"]) == ("SPEAKER_01", "camera 3 (SPEAKER_01)")
    c, res = focus_clip(s, {"person": "", "level": None, "share": None}, focus_speaker="SPEAKER_01")
    assert c["focus_speaker"] is None and "did not ask to show a particular person" in res["notes"][-1]
    def broken(message):
        raise ConnectionError("Ollama is not running")
    ask = scripted([("search_transcript", {"query": "salary"})],
                   [("make_clip", {"start": 22.6, "end": 52.0, "focus_speaker": "SPEAKER_01"})], "ok")
    out = chat(s, "a clip about salaries", ask=ask, render=False, embed=fake_embed, read=broken)
    assert out["clips"][0]["focus_speaker"] == "SPEAKER_01"                  # no reader: the agent's choice, as before
    assert "did NOT ask to show" not in ask.sent[0]["messages"][0]["content"]
    ask = scripted("ok")
    chat(s, "a clip about salaries", ask=ask, read=lambda m: {"person": "", "level": None, "share": None})
    assert "The user did NOT ask to show a particular person" in ask.sent[0]["messages"][0]["content"]


# ---------- 2026-10-09: the clip list, names, follow-ups, the time limit ----------

def test_the_code_writes_the_clip_list(s):
    """The LLM listed clips that were never made, wrong captions and SPEAKER ids: now only its first friendly words
    are kept and the CODE writes the clips really made (title, length, format, captions, who is shown)."""
    ask = scripted([("search_transcript", {"query": "salary"})],
                   [("make_clip", {"start": 22.6, "end": 52.0, "focus_speaker": "SPEAKER_01", "title": "Salary advice"})],
                   "Here it is, showing SPEAKER_01!\n- **Clip 1**: Salary advice (30 s, no captions)\n"
                   "- **Clip 2**: CV tips (40 s)\nFile: [clips/c2.mp4](clips/c2.mp4)")
    out = chat(s, "Make a clip about salaries and focus on the guest", ask=ask, render=False, embed=fake_embed)
    assert out["reply"] == ("Here it is, showing Guest!\n"
                            "- Salary advice (c2): 29 s, horizontal 16:9, captions: Arabic + English, showing Guest")
    ask = scripted([("search_transcript", {"query": "المرتبات"})],
                   [("make_clip", {"start": 22.6, "end": 52.0, "format": "9:16", "title": "نصيحة المرتبات"})],
                   "هذا الريل جاهز: [المرتبات](clips/c2.mp4)")              # only a file link: the code's words
    out = chat(s, "اعمل ريل عن المرتبات", ask=ask, render=False, embed=fake_embed)
    assert out["reply"] == "خلصت!\n- نصيحة المرتبات (c2): 29 ثانية، عمودي 9:16، الترجمة: عربي"


def test_one_clip_unless_more_are_asked(s):
    """"Make a reel about ..." made 3 clips: now exactly the number asked (1 if none)."""
    from ai_director.agent.asks import asked_count
    counts = {"make a reel about salaries": 1, "3 clips about salaries": 3, "two reels please": 2, "اعمل كليبين": 2,
              "اعمل 3 كليبات عن الشغل": 3, "تلات ريلز عن المرتبات": 3, "some clips about salaries": None,
              "اعمل كليبات عن الجامعة": None, "a 2 minute clip": 1, "the 2nd clip, 30 seconds": 1,
              "two clips, 9:16": 2, "عايز ريل دقيقتين": 1}
    assert {m: asked_count(m) for m in counts} == counts
    ask = scripted([("search_transcript", {"query": "المرتبات"})], [("make_clip", {"start": 22.6, "end": 52.0})] * 3,
                   "تمام")
    out = chat(s, "اعمل ريل عن المرتبات", ask=ask, render=False, embed=fake_embed)
    assert len(out["clips"]) == 1
    assert out["steps"][2]["summary"].startswith("error: the user asked for 1 clip and it is made")
    assert "Clips to make for this request: at most 1 clip" in ask.sent[0]["messages"][0]["content"]


def test_a_found_piece_grows_over_the_same_topic():
    """s03 "subscription and profit": the best 30 s piece was only the end of the talk. Neighbours that match almost
    as well (<= 0.05 lower) join, the better one first, up to 90 s, never into a moment already found."""
    pieces = [{"start": 10.0 * k, "end": 10.0 * k + 30} for k in range(10)]           # 0-30, 10-40, ... 90-120
    scores = [0.30, 0.50, 0.52, 0.55, 0.40, 0.54, 0.53, 0.52, 0.51, 0.50]
    assert S.topic(pieces, scores, 3, drop=0.05, longest=90) == (1, 3)               # 4: 0.40 = another topic
    assert S.topic(pieces, scores, 5, drop=0.05, longest=90) == (5, 9)               # 50-120 s
    assert S.topic(pieces, scores, 5, drop=0.05, longest=50) == (5, 7)               # at most 50 s: 50-100 s
    assert S.topic(pieces, scores, 5, taken=[{"start": 75, "end": 120}], drop=0.05, longest=90) == (5, 5)


def test_one_clip_still_searches_several_moments(s, monkeypatch):
    """Told "1 clip", qwen searched with top_k=1 and took the first hit (eval 2026-10-09: 3 wrong moments); and
    "the user asked for 1 clip" made it render a video for "make the video better" (no number = only a limit)."""
    from ai_director.agent import tools
    from ai_director.agent.prompts import count_text
    asked = []
    monkeypatch.setattr(tools, "search", lambda s, q, k, embed: asked.append(k) or [])
    tools.search_transcript(tools.Job(s, "اعمل ريل", render=False), tools.SearchArgs(query="المرتبات", top_k=1))
    assert asked == [5]
    assert [count_text(c, 3) for c in (1, 2, None)] == ["at most 1 clip (none if the request is unclear)",
                                                       "exactly 2 clips", "up to 3 clips"]


def test_people_are_called_by_name_or_role():
    """Names are often blank (s01: the host and the co-host): the role, numbered when two unnamed share it."""
    from ai_director.agent.asks import name_people, people_labels
    p = lambda i, role, name="": {"id": f"SPEAKER_0{i}", "role": role, "name": name}          # noqa: E731
    s03 = [p(0, "panelist"), p(1, "host"), p(2, "panelist", "Ahmed"), p(3, "panelist"), p(4, "")]
    assert people_labels(s03, "en") == {"SPEAKER_00": "panelist 1", "SPEAKER_01": "the host", "SPEAKER_02": "Ahmed",
                                        "SPEAKER_03": "panelist 2", "SPEAKER_04": "speaker 5"}
    assert people_labels(s03, "ar") == {"SPEAKER_00": "المشارك 1", "SPEAKER_01": "المقدم", "SPEAKER_02": "المشارك 2",
                                        "SPEAKER_03": "المشارك 3", "SPEAKER_04": "المتحدث 5"}   # "Ahmed": English letters
    named = [p(1, "guest", "إسلام"), p(2, "host", "Salma")]                 # each language keeps its own letters
    assert people_labels(named, "ar") == {"SPEAKER_01": "إسلام", "SPEAKER_02": "المقدم"}
    assert people_labels(named, "en") == {"SPEAKER_01": "the guest", "SPEAKER_02": "Salma"}
    s01 = [p(0, "host"), p(1, "guest", "Islam"), p(2, "co-host")]
    labels = people_labels(s01, "en")
    assert name_people("A clip of SPEAKER_01 asked by the host (SPEAKER_00), SPEAKER_02 laughs", labels) == \
        "A clip of Islam asked by the host, the co-host laughs"
    assert "SPEAKER_00: host, close-up camera" in speaker_lines(
        [{**p(0, "host"), "camera": 2, "talk_seconds": 9, "description": ""}], {"SPEAKER_00": "the host"})


def test_follow_ups_use_the_earlier_clip(s):
    """The mock has c1 = 38.0-52.0 s (14 s, 9:16). "make it vertical / longer / 5 s shorter / أقصر" reuse its times
    (no search needed) and the code works out the new length."""
    from ai_director.agent.asks import length_change
    changes = {"make it longer": ("longer", None), "make it 30 seconds longer": ("longer", 30),
               "longer by half a minute": ("longer", 30), "زود 20 ثانية": ("longer", 20),
               "خليه أطول بنص دقيقة": ("longer", 30), "قصره شوية": ("shorter", None),
               "make it shorter, 1 minute": ("shorter", None), "make a clip about salaries": None,
               "اعمل كليب دقيقتين": None}
    assert {m: length_change(m) for m in changes} == changes

    def follow(message, **args):
        ask = scripted([("make_clip", {"start": 38.0, "end": 52.0, **args})], "ok")
        out = chat(s, message, ask=ask, render=False, embed=fake_embed)
        return out, tool_results(ask)[0], ask
    out, res, ask = follow("make it horizontal", format="16:9")
    assert (out["clips"][0]["start"], out["clips"][0]["end"], out["clips"][0]["format"]) == (38.0, 52.0, "16:9")
    assert "- c1: 38.0-52.0 s (14 s), 9:16" in ask.sent[0]["messages"][0]["content"]       # the agent knows c1
    out, res, _ = follow("make it 5 seconds shorter")
    assert res["notes"][0] == "9 s long (shorter than the 14 s before, as the user asked)" and res["seconds"] == 10.0
    out, res, _ = follow("خليه أقصر")
    assert res["notes"][0].startswith("5 s long (shorter than the 14 s before") and res["seconds"] <= 6
    out, res, _ = follow("make it longer")
    assert res["notes"][0].startswith("24 s long (longer than the 14 s before") and res["seconds"] >= 23
    out, res, _ = follow("make it shorter, 1 minute")                         # a new length, not "1 minute less"
    assert res["notes"][0].startswith("60 s long, as the user asked")
    ask = scripted([("make_clip", {"start": 0.0, "end": 39.0})], "ok")        # only touches c1: still invented
    out = chat(s, "make a clip", ask=ask, render=False, embed=fake_embed)
    assert out["steps"][0]["summary"].startswith("error: these times did not come from a tool")


def test_a_stuck_model_gets_a_clear_answer():
    """Ollama has a time limit now (agent.timeout); a timeout becomes "it took too long" (never a hang)."""
    ollama = pytest.importorskip("ollama")
    from ai_director.agent.search import CFG, ollama_client
    assert isinstance(ollama_client(), ollama.Client) and ollama_client()._client.timeout.read == CFG["timeout"]


def test_the_code_reads_the_format():
    """"Make a short clip" became 9:16 (the LLM's choice): the format is read from the message like the length."""
    from ai_director.agent.asks import asked_format
    formats = {"Make a short clip about the app": None, "TikTok clip about the model": "9:16", "عايز ريل عن": "9:16",
               "اعمل تيك توك": "9:16", "a vertical clip": "9:16", "for YouTube please": "16:9", "خليه أفقي": "16:9",
               "YouTube Shorts": "9:16", "make it 9:16": "9:16", "an Instagram story": "9:16", "e3mel reel": "9:16"}
    assert {m: asked_format(m) for m in formats} == formats


def test_a_timeout_reply(s):
    class ReadTimeout(Exception):
        pass

    def stuck(messages, tools):
        raise ReadTimeout("timed out")
    out = chat(s, "Make a clip about salaries", ask=stuck)
    assert out["reply"] == "Sorry, the AI model took longer than 120 seconds. Please try again in a minute."
