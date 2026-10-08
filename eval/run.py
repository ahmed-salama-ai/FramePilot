# eval/run.py — stage 8 (Evaluation): every number we can measure for one session -> metrics.json
#   python -m eval.run data/sessions/s01
# The web app's metrics card reads metrics.json; eval/table.py joins all sessions into the results table.
# A number that can't be measured yet (no human labels, no hand-corrected text, no agent run, no viewer answers)
# is null with a printed reason, never a guess. Run it again after new labels arrive (delete metrics.json first if the
# pipeline should do it).
# Owner: Ahmed Salama
from pathlib import Path

import pandas as pd

from ai_director.common.io import read_json, session_from_argv, write_json
from ai_director.common.schemas import Metrics

from .agent_eval import RESULTS
from .director_eval import evaluate_director
from .highlight_eval import precision_at_3
from .wer import load_set, wer_table


def director(s):
    if not (s / "cuts.json").exists():
        return None, "no cuts.json (the Switching stage)"
    res = evaluate_director(s)
    return res, None if "human" in res else "agreement needs labels.csv (the labelling tool)"


def captions(s):
    items = [x for x in load_set() if x["session"] == s.name]
    table = wer_table(items, s.parent) if items else {}
    return (table or None), None if table else "no hand-corrected text for this session in eval/wer_set.json"


def highlights(s):
    if not (s / "highlights.json").exists():
        return None, "no highlights.json (the Highlights stage)"
    if not (s / "highlight_labels.csv").exists():
        return None, "needs highlight_labels.csv (the labelling tool)"
    p, _ = precision_at_3(s)
    return {"precision_at_3": round(p, 3), "labels": len(pd.read_csv(s / "highlight_labels.csv"))}, None


def agent(s):
    if not RESULTS.exists():
        return None, "no eval/agent_results.json yet (python -m eval.agent_eval, needs Ollama)"
    res = read_json(RESULTS)["by_session"].get(s.name)
    return res, None if res else "no agent tests for this session"


def viewer_test(s):
    if not (s / "ab_test" / "answers.csv").exists():
        return None, "no ab_test/answers.csv (the A/B viewer test)"
    from .ab_test import score
    return score(s), None


def processing(s):
    f = s / "logs" / "times.json"                                    # written by pipeline.py after every stage
    return (read_json(f), None) if f.exists() else ({}, "no logs/times.json (run the session with pipeline.py)")


def evaluate(s):
    """Every part on its own: a part that fails is reported and left null, the others are still measured."""
    m = {}
    for name, fn in (("director", director), ("captions", captions), ("highlights", highlights), ("agent", agent),
                     ("viewer_test", viewer_test), ("processing_seconds", processing)):
        try:
            m[name], why = fn(s)
        except Exception as e:                                       # e.g. a missing diarization.json
            m[name], why = ({} if name == "processing_seconds" else None), f"FAILED: {type(e).__name__}: {e}"
        print(f"  {name:18s} {'measured' if m[name] else 'not measured'}" + (f"  ({why})" if why else ""), flush=True)
    Metrics.model_validate(m)                                        # follows the contract
    return m


if __name__ == "__main__":
    s = session_from_argv()
    m = evaluate(s)
    write_json(s / "metrics.json", m)                                # LAST: the done file of this stage
    d = m["director"] or {}
    for name in ("ai", "random", "wide", "human"):
        if name in d:
            r = d[name]
            show = lambda v: "-" if v is None else f"{100 * v:.0f}%"
            print(f"  {name:7s} agreement {show(r['agreement']):>5s}  speaker coverage {show(r['speaker_coverage']):>5s}"
                  f"  cuts < 1 s {r['short_cuts']:3d}  average shot {r['avg_shot']:5.1f} s")
    print("done:", s / "metrics.json")
