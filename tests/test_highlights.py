# tests/test_highlights.py — highlights without an LLM (a fake one answers) on made-up data and a copy of the mock
import shutil

import numpy as np
import pandas as pd
from pydantic import TypeAdapter

from ai_director.common import schemas as S
from ai_director.common.io import read_json, write_json
from ai_director.common.paths import MOCK
from ai_director.highlights.clips import vertical_source
from ai_director.highlights.interest import interest_curve
from ai_director.highlights.select import Pick, Picks, candidates, pick, snap


def rows(duration, every=5.0, text="كلام"):
    """Made-up transcript rows: one every 5 s."""
    return [{"start": t, "end": t + every - 0.5, "speaker": "SPEAKER_00", "text": f"{text} {k}", "translation": f"talk {k}"}
            for k, t in enumerate(np.arange(0, duration, every))]


def test_interest_curve_on_the_mock(tmp_path):
    ev = interest_curve(MOCK)
    assert len(ev) == 60 and {"loud_z", "laugh", "energy", "changes", "interest"} <= set(ev.columns)
    laugh = ev[ev.t.between(33, 38)].interest.mean()                  # the mock's laughter (33-38 s)
    assert laugh > ev.interest.mean()
    for f in ("audio_events.json", "diarization.json"):                # without the AI Brain (no scene.jsonl)
        shutil.copy(MOCK / f, tmp_path)
    ev2 = interest_curve(tmp_path)
    assert (ev2.energy == 0).all() and len(ev2) == 60


def test_snap_to_sentences():
    segs = rows(200)
    a, b = snap(segs, 47.0, 82.0, 200)
    assert a == 45.0                                                  # the start of the row that contains 47 s
    assert b in [r["end"] for r in segs] and 20 <= b - a <= 45        # a row end, 20-45 s long
    assert snap(segs, 185.0, 220.0, 200)[1] <= 200                    # never after the end of the video


def test_candidates_are_the_peaks_without_overlap():
    t = np.arange(0, 200.0)
    interest = np.exp(-((t - 40) ** 2) / 20) * 3 + np.exp(-((t - 100) ** 2) / 20) * 2 + np.exp(-((t - 160) ** 2) / 20)
    ev = pd.DataFrame({"t": t, "interest": interest})
    c = candidates(ev, rows(200), 200)
    assert [x["peak"] for x in c][:2] == [40.0, 100.0]                # most interesting first
    assert all(20 <= x["end"] - x["start"] <= 45 for x in c)
    assert all(a["end"] <= b["start"] or b["end"] <= a["start"] for a in c for b in c if a is not b)


def cands(n):
    return [{"id": k, "start": 50.0 * k, "end": 50.0 * k + 30, "peak": 50.0 * k + 15, "interest": 1.0 - k / 10,
             "text": f"أول جملة في المقطع رقم {k} وبعدين كلام تاني", "translation": f"the first sentence of clip {k}"}
            for k in range(n)]


def test_the_llm_picks_with_checks():
    answer = Picks(picks=[Pick(id=9, title_ar="x", title_en="wrong id", hook=""),            # not a candidate
                          Pick(id=2, title_ar="المرتبات", title_en="Salaries", hook="Why?"),
                          Pick(id=2, title_ar="تاني", title_en="double", hook="")])          # already chosen
    chosen = pick(cands(5), "ar", ask=lambda prompt: answer)
    assert [c["id"] for c, _ in chosen] == [2, 0, 1]                  # 1 good pick + the best remaining (min 3)
    assert chosen[0][1] == {"title_ar": "المرتبات", "title_en": "Salaries", "hook": "Why?"}
    assert chosen[1][1]["title_ar"] == "أول جملة في المقطع رقم 0"     # fallback title: the first words


def test_titles_from_gemini_then_the_local_model(monkeypatch):
    """By default Gemini (highlights.title_model) picks and writes the titles; without quota the local model does."""
    import ai_director.audio.gemini as gemini
    import ai_director.brain.llm_client as llm
    asked = []
    monkeypatch.setattr(gemini, "ask_json", lambda model, prompt, schema: asked.append(model) or Picks(
        picks=[Pick(id=1, title_ar="عنوان", title_en="Title", hook="Hook")]))
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("local model used")))
    assert pick(cands(4), "ar")[0][1]["title_en"] == "Title" and asked == ["gemini-3.1-flash-lite"]

    def no_quota(*a, **k):
        raise RuntimeError("Gemini: no key can be used right now (rate or daily limits).")
    monkeypatch.setattr(gemini, "ask_json", no_quota)
    monkeypatch.setattr(llm, "chat_json", lambda model, prompt, schema, think=None: Picks(
        picks=[Pick(id=2, title_ar="محلي", title_en="Local", hook="")]))
    assert pick(cands(4), "ar")[0][1]["title_en"] == "Local"


def test_no_llm_still_gives_highlights():
    def broken(prompt):
        raise ConnectionError("Ollama is not running")
    chosen = pick(cands(4), "ar", ask=broken)
    assert len(chosen) == 3 and chosen[0][1]["title_en"].startswith("the first sentence")
    assert len(pick(cands(1), "ar", ask=broken)) == 1                 # fewer candidates -> fewer highlights


def test_vertical_clip_follows_the_main_speaker(tmp_path):
    write_json(tmp_path / "speaker_map.json", {"SPEAKER_00": 2})
    write_json(tmp_path / "diarization.json", [{"start": 0, "end": 25, "speaker": "SPEAKER_00"},
                                               {"start": 25, "end": 30, "speaker": "SPEAKER_01"}])
    feats = pd.DataFrame({"t": [5.0, 10, 15, 5, 10], "cam": [2, 2, 2, 3, 3], "face_area": [0.03] * 5,
                          "face_x": [0.70, 0.72, 0.74, 0.40, 0.42]})
    cuts = [{"start": 0, "end": 30, "cam": 3}]
    assert vertical_source(tmp_path, 0, 30, cuts, feats) == (2, 0.72)        # SPEAKER_00 talks most -> cam 2
    write_json(tmp_path / "speaker_map.json", {})                             # not in a close-up -> the AI edit
    assert vertical_source(tmp_path, 0, 30, cuts, feats) == ("program", 0.41)


def test_the_stage_on_a_copy_of_the_mock(tmp_path):
    from ai_director.highlights.run import main
    from ai_director.ingest.probe import probe
    s = tmp_path / "s00"
    shutil.copytree(MOCK, s)                                          # never write into the mock
    shutil.rmtree(s / "highlights"); (s / "highlights.json").unlink()
    items = main(s, ask=lambda prompt: Picks(picks=[Pick(id=0, title_ar="نصايح السي في", title_en="CV tips",
                                                         hook="One page only")]))
    TypeAdapter(list[S.Highlight]).validate_python(read_json(s / "highlights.json"))
    assert items[0]["title_en"] == "CV tips" and (s / "highlights" / "interest.csv").exists()
    tall = probe(s / items[0]["files"]["9:16"])
    assert (tall["width"], tall["height"]) == (720, 1280)
    assert abs(tall["duration"] - (items[0]["end"] - items[0]["start"])) < 0.2


def test_highlight_eval_on_the_mock():
    from eval.highlight_eval import iou, precision_at_3
    assert iou((0, 10), (5, 15)) == 5 / 15 and iou((0, 10), (20, 30)) == 0
    p, hits = precision_at_3(MOCK)                    # mock: h1 27.5-48 overlaps the laugh 30-40; h2 12.5-27 doesn't
    assert hits == [True, False] and p == 0.5
