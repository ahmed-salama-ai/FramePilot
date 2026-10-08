# eval/agent_eval.py — Days 10-11: the Editor Agent on the 15 test requests (agent_tests.json) -> success rate,
# average steps and seconds. Needs Ollama (the real LLM) and the sessions.
#   python -m eval.agent_eval                    every test; the clips are rendered, then removed again
#   python -m eval.agent_eval --no-render        decisions only (fast, no FFmpeg): good while improving the prompt
#   python -m eval.agent_eval --session s02      only one session (the other sessions' results are kept)
#   python -m eval.agent_eval --out eval/agent_results_qwen3-4b.json     keep a run under another name (compare models)
# Writes eval/agent_results.json; eval.run copies each session's numbers into its metrics.json.
# Owner: Eslam ElKharbotly (written by Ahmed Salama from Eslam's guide)
import argparse
import sys
import time
from pathlib import Path

from ai_director.common.io import read_json, write_json
from ai_director.common.paths import ROOT, SESSIONS

TESTS = ROOT / "eval" / "agent_tests.json"
RESULTS = ROOT / "eval" / "agent_results.json"


def passed(test, out):
    """Success (Architecture §6): a clip overlaps the right moment and has the right format (and shows the right
    person, if the test names one). An unclear request: no clip and a question."""
    exp = test["expect"]
    if exp.get("asks_question"):
        return not out["clips"] and ("?" in out["reply"] or "؟" in out["reply"])
    return any(min(c["end"], exp["end"]) - max(c["start"], exp["start"]) > 0
               and c["format"] == exp.get("format", c["format"])
               and ("focus_speaker" not in exp or c.get("focus_speaker") == exp["focus_speaker"])
               for c in out["clips"])


def undo(s, before, clips):
    """Remove what one test made: its clip files, and clips.json as it was before."""
    for c in clips:
        (s / c["file"]).unlink(missing_ok=True)
    if before is None:
        (s / "clips.json").unlink(missing_ok=True)
    else:
        (s / "clips.json").write_text(before, encoding="utf-8")


def run_tests(tests, root=SESSIONS, render=True, keep=False, chat=None):
    """Every test once, in a NEW chat (no history). Returns one row per test."""
    if chat is None:
        from ai_director.agent.agent import chat                    # needs Ollama only when it really runs
    rows = []
    for t in tests:
        s = Path(root) / t["session"]
        before = (s / "clips.json").read_text(encoding="utf-8") if (s / "clips.json").exists() else None
        t0 = time.time()
        out = chat(s, t["request"], render=render)
        row = {"id": t["id"], "session": t["session"], "lang": t["lang"], "request": t["request"],
               "ok": passed(t, out), "steps": len(out["steps"]), "seconds": round(time.time() - t0, 1),
               "expect": t["expect"], "reply": out["reply"][:300],
               "clips": [{k: c.get(k) for k in ("start", "end", "format", "focus_speaker", "file")} for c in out["clips"]],
               "tools": [f"{st['tool']}: {st['summary']}" for st in out["steps"]]}
        rows.append(row)
        print(f"  {'OK  ' if row['ok'] else 'FAIL'} #{t['id']:2d} {t['session']} {row['steps']} steps {row['seconds']:5.1f} s"
              f"  {t['request'][:60]}", flush=True)
        if render and not keep:
            undo(s, before, out["clips"])
    return rows


def summary(rows):
    n = len(rows)
    return {"success_rate": round(sum(r["ok"] for r in rows) / n, 3), "avg_steps": round(sum(r["steps"] for r in rows) / n, 1),
            "avg_seconds": round(sum(r["seconds"] for r in rows) / n, 1), "tests": n} if n else None


def report(rows, model, render):
    """The results file: every test + the numbers for all tests, per session and per language."""
    return {"made": time.strftime("%Y-%m-%d %H:%M"), "model": model, "render": render, "summary": summary(rows),
            "by_session": {s: summary([r for r in rows if r["session"] == s]) for s in sorted({r["session"] for r in rows})},
            "by_language": {g: summary([r for r in rows if r["lang"] == g]) for g in sorted({r["lang"] for r in rows})},
            "tests": sorted(rows, key=lambda r: r["id"])}


def main(argv=None):
    p = argparse.ArgumentParser(description="Run the Editor Agent's test requests.")
    p.add_argument("--session", help="only the tests of this session, e.g. s02")
    p.add_argument("--no-render", action="store_true", help="decide only, render no clips (fast)")
    p.add_argument("--keep", action="store_true", help="keep the clips the tests made")
    p.add_argument("--out", default=str(RESULTS), help="results file")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    tests = [t for t in read_json(TESTS) if not args.session or t["session"] == args.session]
    rows = run_tests(tests, render=not args.no_render, keep=args.keep)
    out = Path(args.out)
    if args.session and out.exists():                           # keep the other sessions' results
        rows = [r for r in read_json(out)["tests"] if r["session"] != args.session] + rows
    from ai_director.agent.search import OLLAMA
    res = report(rows, OLLAMA["text_model"], not args.no_render)
    write_json(out, res)
    s = res["summary"]
    print(f"success rate {100 * s['success_rate']:.0f}% ({sum(r['ok'] for r in rows)}/{s['tests']}), "
          f"{s['avg_steps']} steps and {s['avg_seconds']} s per request -> {out}")
    for r in res["tests"]:
        if not r["ok"]:                                          # what to look at: wrong tool? times? format?
            print(f"\n  FAILED #{r['id']}: {r['request']}\n    expected {r['expect']}\n    got {r['clips']}"
                  f"\n    steps {r['tools']}\n    reply {r['reply'][:150]}")


if __name__ == "__main__":
    main()
