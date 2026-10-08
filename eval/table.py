# eval/table.py — Day 12: the final results table of all sessions -> eval/results.md (slides, README)
#   python -m eval.table
# Reads data/sessions/*/metrics.json (made by eval.run). The test session (configs eval.test_session) is the honest
# number: the weights were tuned on the other sessions only.
# Owner: Ahmed Salama
import sys

import numpy as np
import yaml

from ai_director.common.io import read_json
from ai_director.common.paths import CONFIGS, ROOT, SESSIONS

CFG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["eval"]
EDITS = [("random", "Random"), ("wide", "Always wide"), ("ai", "AI Director"), ("human", "Human")]
ROWS = [("agreement", "Agreement with the human", "pct", "> 60%"),
        ("speaker_coverage", "Speaker coverage", "pct", "> 80%"),
        ("short_cuts", "Cuts shorter than 1 s", "int", "0"),
        ("avg_shot", "Average shot length", "sec", "4-8 s")]


def show(v, kind):
    if v is None:
        return "–"
    return {"pct": f"{100 * v:.0f}%", "int": f"{v:.0f}", "sec": f"{v:.1f} s", "num": f"{v:.3f}"}[kind]


def director_table(d):
    lines = ["| Metric | " + " | ".join(n for k, n in EDITS if k in d) + " | Target |",
             "|---|" + "---|" * (sum(k in d for k, _ in EDITS) + 1)]
    for key, name, kind, target in ROWS:
        lines.append(f"| {name} | " + " | ".join(show(d[k][key], kind) for k, _ in EDITS if k in d) + f" | {target} |")
    return lines


def other_rows(m):
    rows = []
    for lang, r in (m.get("captions") or {}).items():
        rows.append((f"Caption WER / CER ({lang.upper()})", f"{r['wer']:.3f} / {r['cer']:.3f} ({r['words']:.0f} words)",
                     "lower is better"))
    if m.get("highlights"):
        rows.append(("Highlight precision@3", show(m["highlights"]["precision_at_3"], "num"), "> 0.6"))
    if m.get("agent"):
        a = m["agent"]
        rows.append(("Agent success rate", f"{show(a['success_rate'], 'pct')} of {a['tests']:.0f} requests, "
                     f"{a['avg_steps']} steps, {a['avg_seconds']} s each", "> 70%"))
    if m.get("processing_seconds"):
        rows.append(("Processing time", f"{sum(m['processing_seconds'].values()) / 60:.1f} min", "< 10 min"))
    if m.get("viewer_test") and m["viewer_test"].get("prefer_ai") is not None:
        v = m["viewer_test"]
        rows.append(("Viewer test (chose the AI edit)", f"{show(v['prefer_ai'], 'pct')} of {v['answers']:.0f} answers",
                     "majority"))
    return rows


def results(sessions):
    """{session name: metrics} -> the markdown text of the results table."""
    out = ["# AI Director: results", ""]
    for name, m in sessions.items():
        role = ("test session (never tuned on)" if name == CFG["test_session"] else
                "tuning session" if name in CFG["tuning_sessions"] else "session")
        out += [f"## {name} ({role})", ""]
        if m.get("director"):
            out += director_table(m["director"]) + [""]
        rows = other_rows(m)
        if rows:
            out += ["| Metric | Value | Target |", "|---|---|---|"] + [f"| {a} | {b} | {c} |" for a, b, c in rows] + [""]
    ai = [m["director"]["ai"] for m in sessions.values() if m.get("director")]
    if len(ai) > 1:                                                  # the average over the sessions
        out += ["## All sessions (average of the AI edit)", "", "| Metric | AI Director | Target |", "|---|---|---|"]
        for key, name, kind, target in ROWS:
            vals = [x[key] for x in ai if x[key] is not None]
            out.append(f"| {name} | {show(float(np.mean(vals)), kind) if vals else '–'} | {target} |")
        out.append("")
    out.append("– = not measured yet (needs human labels, hand-corrected text, an agent run or viewer answers).")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    found = {p.parent.name: read_json(p) for p in sorted(SESSIONS.glob("*/metrics.json"))}
    found = {k: v for k, v in found.items() if not v.get("mock")}             # not the copies of the mock session
    if not found:
        sys.exit("No metrics.json yet: run  python -m eval.run data/sessions/s01  first")
    text = results(found)
    (ROOT / "eval" / "results.md").write_text(text, encoding="utf-8")
    print(text)
    print("saved:", ROOT / "eval" / "results.md")
