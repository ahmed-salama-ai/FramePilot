# tests/test_eval.py — the evaluation (stage 8) on made-up data and on copies of the mock session (no models needed)
import json
import shutil

import numpy as np
import pandas as pd
import pytest

from ai_director.common.check import check_session
from ai_director.common.io import read_json, write_json
from ai_director.common.paths import MOCK, ROOT
from ai_director.director.run import on_air_at as director_on_air
from eval import agent_eval, ab_test, table
from eval.director_eval import edit_scores, evaluate_director, on_air_at
from eval.wer import norm_ar, ready, wer_table


@pytest.fixture
def s(tmp_path):
    shutil.copytree(MOCK, tmp_path / "s00")               # never write into the mock
    return tmp_path / "s00"


def test_on_air_at_is_the_same_as_the_director(s):
    cuts, t = read_json(s / "cuts.json"), pd.read_csv(s / "labels.csv").t.values
    assert list(on_air_at(cuts, t)) == [director_on_air(cuts, x) for x in t]


def test_scores_by_hand():
    cuts = [{"start": 0.0, "end": 0.5, "cam": 1}, {"start": 0.5, "end": 1.0, "cam": 2}]
    times = np.round(np.arange(0, 1.0, 0.1), 2)                       # 10 moments
    speaking = np.array([-1, -1, 2, 2, 2, 2, 2, 3, 3, -1])            # nobody / camera 2's person / camera 3's
    human = np.array([1, 1, 1, 2, 2, 2, 2, 3, 3, 3])
    r = edit_scores(cuts, times, speaking, human)
    # on air: cam 1 at 0.0-0.4 s, cam 2 at 0.5-0.9 s
    assert r["agreement"] == 0.5                                      # same camera as the human at 0.0-0.2 and 0.5-0.6
    assert r["speaker_coverage"] == round(2 / 7, 3)                   # 7 speaking moments, the speaker's camera at 2
    assert (r["short_cuts"], r["avg_shot"], r["shots"]) == (1, 0.5, 2)   # the first shot is 0.5 s (the last one
    assert edit_scores(cuts, times, speaking)["agreement"] is None       # doesn't count); no labels -> no agreement


def test_the_ai_beats_the_baselines_on_the_mock(s):
    r = evaluate_director(s)
    assert r["ai"]["agreement"] > r["random"]["agreement"] > r["wide"]["agreement"]
    assert r["ai"]["speaker_coverage"] > 0.8 and r["wide"]["speaker_coverage"] == 0.0 and r["ai"]["short_cuts"] == 0
    assert r["human"]["agreement"] == 1.0 and r["wide"]["shots"] == 1
    (s / "labels.csv").unlink()                                       # no human labels yet
    r = evaluate_director(s)
    assert "human" not in r and r["ai"]["agreement"] is None and r["ai"]["speaker_coverage"] > 0.8


def test_wer(tmp_path):
    assert norm_ar("أَهلاً بالمرتبات!") == "اهلا بالمرتبات" and not ready({"reference": "PASTE HAND-CORRECTED TEXT HERE"})
    assert wer_table([{"session": "x", "lang": "ar", "start": 0, "end": 9, "reference": "PASTE HERE"}]) == {}
    pytest.importorskip("jiwer")
    (tmp_path / "x").mkdir()
    words = [{"w": w, "start": float(k), "end": k + 0.5} for k, w in enumerate("the salary is good".split())]
    write_json(tmp_path / "x" / "transcript.json", [{"words": words}])
    r = wer_table([{"session": "x", "lang": "en", "start": 0, "end": 3, "reference": "The salary was good."}], tmp_path)
    assert r == {"en": {"wer": 0.5, "cer": 0.368, "words": 4, "minutes": 0.1}}   # "is" for "was", "good" missing
                                                                      # (said after 3 s): 2/4 words, 7/19 letters


def test_the_agent_tests_file():
    tests = read_json(ROOT / "eval" / "agent_tests.json")
    assert len(tests) == 15 and sum(t["lang"] == "ar" for t in tests) == 8 and len({t["id"] for t in tests}) == 15
    assert [t["id"] for t in tests if t["expect"].get("asks_question")] == [6]
    for t in tests:
        e = t["expect"]
        assert t["session"] in ("s01", "s02", "s03")
        assert e.get("asks_question") or (0 <= e["start"] < e["end"] <= 603 and e["format"] in ("16:9", "9:16"))


def test_agent_eval_with_a_fake_agent(s):
    tests = [{"id": 1, "session": "s00", "lang": "ar", "request": "كليب المرتبات",
              "expect": {"start": 27, "end": 52, "format": "9:16", "focus_speaker": "SPEAKER_01"}},
             {"id": 2, "session": "s00", "lang": "en", "request": "make it better", "expect": {"asks_question": True}},
             {"id": 3, "session": "s00", "lang": "en", "request": "CV clip", "expect": {"start": 12, "end": 27,
                                                                                       "format": "16:9"}}]
    before = (s / "clips.json").read_text(encoding="utf-8")

    def fake_chat(session, message, render=True):                    # makes a clip file like the real agent
        if "better" in message:
            return {"reply": "What should I improve?", "steps": [], "clips": []}
        clip = {"id": "c9", "start": 38.0, "end": 52.0, "format": "9:16", "title": "", "file": "clips/c9.mp4",
                "focus_speaker": "SPEAKER_01"}
        (session / clip["file"]).write_bytes(b"video")
        write_json(session / "clips.json", read_json(session / "clips.json") + [clip])
        return {"reply": "Done", "steps": [{"tool": "make_clip", "summary": "rendered"}] * 2, "clips": [clip]}

    rows = agent_eval.run_tests(tests, root=s.parent, chat=fake_chat)
    assert [r["ok"] for r in rows] == [True, True, False]             # #3: the clip is in the wrong place and format
    assert not (s / "clips/c9.mp4").exists() and (s / "clips.json").read_text(encoding="utf-8") == before   # undone
    res = agent_eval.report(rows, "fake", True)
    assert res["summary"] == {"success_rate": 0.667, "avg_steps": 1.3, "avg_seconds": res["summary"]["avg_seconds"],
                              "tests": 3}
    assert res["by_language"]["ar"]["success_rate"] == 1.0 and res["by_session"]["s00"]["tests"] == 3


def test_ab_test(s):
    from ai_director.ingest.probe import probe
    cuts = read_json(s / "cuts.json")
    w = ab_test.pick_windows(cuts, 60.0, 3, 15)
    assert len(w) == 3 and all(abs(a - b) >= 15 for a in w for b in w if a != b)
    key = ab_test.make(s, n=2, length=10)
    assert len(key) == 2 and all(abs(probe(s / f"ab_test/pair{x['pair']}_{side}.mp4")["duration"] - 10) < 0.2
                                 for x in key for side in "AB")
    ai = {x["pair"]: x["ai"] for x in key}
    other = {"A": "B", "B": "A"}
    pd.DataFrame({"pair1": [ai[1], ai[1], other[ai[1]], ai[1]], "pair2": [ai[2], other[ai[2]], other[ai[2]], None]}
                 ).to_csv(s / "ab_test" / "answers.csv", index=False)
    r = ab_test.score(s)
    assert r == {"prefer_ai": round(4 / 7, 3), "answers": 7, "people": 4, "pair1": 0.75, "pair2": round(1 / 3, 3)}


def test_eval_run_writes_metrics(s, tmp_path, monkeypatch):
    import eval.run as er
    (s / "metrics.json").unlink()
    (s / "logs").mkdir(exist_ok=True)
    write_json(s / "logs" / "times.json", {"Ingest + Sync": 41.2, "Render": 63.0})
    results = tmp_path / "agent_results.json"
    write_json(results, {"by_session": {"s00": {"success_rate": 0.8, "avg_steps": 2.5, "avg_seconds": 20.1,
                                                "tests": 5}}})
    monkeypatch.setattr(er, "RESULTS", results)
    m = er.evaluate(s)
    assert m["director"]["ai"]["agreement"] > 0.8 and m["highlights"] == {"precision_at_3": 0.5, "labels": 2}
    assert m["agent"]["success_rate"] == 0.8 and m["processing_seconds"]["Render"] == 63.0
    assert m["captions"] is None and m["viewer_test"] is None          # not measured: no reference text, no answers
    write_json(s / "metrics.json", m)
    assert check_session(s) == []                                     # metrics.json follows the contract
    (s / "diarization.json").unlink()                                 # one part breaks -> the others still work
    m = er.evaluate(s)
    assert m["director"] is None and m["highlights"]["precision_at_3"] == 0.5


def test_results_table():
    d = {"ai": {"agreement": 0.71, "speaker_coverage": 0.85, "short_cuts": 0, "avg_shot": 5.2, "shots": 90},
         "random": {"agreement": 0.33, "speaker_coverage": 0.3, "short_cuts": 0, "avg_shot": 5.0, "shots": 120},
         "wide": {"agreement": None, "speaker_coverage": 0.0, "short_cuts": 0, "avg_shot": 600.0, "shots": 1}}
    text = table.results({"s01": {"director": d, "captions": {"ar": {"wer": 0.31, "cer": 0.14, "words": 900}}},
                          "s03": {"director": d, "agent": {"success_rate": 0.8, "avg_steps": 2.5, "avg_seconds": 20.0,
                                                           "tests": 5}}})
    assert "## s01 (tuning session)" in text and "## s03 (test session (never tuned on))" in text
    assert "| Agreement with the human | 33% | – | 71% | > 60% |" in text
    assert "| Caption WER / CER (AR) | 0.310 / 0.140 (900 words) | lower is better |" in text
    assert "| Agent success rate | 80% of 5 requests, 2.5 steps, 20.0 s each | > 70% |" in text
    assert "## All sessions (average of the AI edit)" in text


def test_tuning_tries_settings_and_puts_the_old_ones_back(s):
    import ai_director.director.run as director
    import ai_director.director.scorer as scorer
    from eval.tune import try_setting, tune
    before = (dict(scorer.W), dict(director.RULES))
    ranked = tune([s], {"min_shot": [12.0, 2.0], "margin": [0.2]})   # a 12 s minimum shot misses the changes
    assert [v for v, _ in ranked] == [{"min_shot": 2.0, "margin": 0.2}, {"min_shot": 12.0, "margin": 0.2}]
    assert ranked[0][1]["agreement"] == 0.867 and ranked[1][1]["agreement"] == 0.425     # best first (0.85 / 0.258 before the split at 37-41 s)
    assert ranked[0][1] == try_setting([s], {"min_shot": 2.0, "margin": 0.2})
    assert (dict(scorer.W), dict(director.RULES)) == before            # configs unchanged
