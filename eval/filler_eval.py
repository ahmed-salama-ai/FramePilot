import collections
import itertools
import sys
from pathlib import Path

from ai_director.audio.fillers import find_candidates, load_fillers, removed_in
from ai_director.common.io import read_json


def load_labels(s, words):
    """The hand labels (filler_labels.json) as word positions: fillers, not fillers, and unwritten filler times."""
    saved = read_json(Path(s) / "filler_labels.json")
    by_time = {(round(w["start"], 2), w["w"]): k for k, w in enumerate(words)}
    pos = lambda items: {by_time[(round(x["start"], 2), x["w"])] for x in items or []    # noqa: E731
                         if (round(x["start"], 2), x["w"]) in by_time}
    return pos(saved.get("words")), pos(saved.get("not_fillers")), list(saved.get("missed") or []), saved


def flat_words(rows):
    return [w for r in rows for w in r.get("words") or [] if str(w.get("w", "")).strip()]


def truth(c, fillers, not_fillers):
    ks = range(c["i"], c["i"] + c["n"])
    if any(k in fillers for k in ks):
        return "filler"
    if any(k in not_fillers for k in ks):
        return "not"
    return None                                                     # never checked


def score(cands, fillers, not_fillers, missed, mode):
    """Precision of what `mode` removes (over checked candidates) and recall over every labelled filler."""
    cut = removed_in(cands, mode)
    judged = [(c, truth(c, fillers, not_fillers)) for c in cut]
    tp = sum(1 for _, t in judged if t == "filler")
    fp = sum(1 for _, t in judged if t == "not")
    in_cands = {k for c in cands for k in range(c["i"], c["i"] + c["n"])}
    filler_units = sum(1 for c in cands if truth(c, fillers, not_fillers) == "filler") + \
        len([k for k in fillers if k not in in_cands])
    written = filler_units
    total = written + len(missed)
    return {"mode": mode, "removed": len(cut), "tp": tp, "fp": fp, "unchecked": len(cut) - tp - fp,
            "precision": tp / (tp + fp) if tp + fp else None, "recall_written": tp / written if written else None,
            "recall_all": tp / total if total else None, "written": written, "unwritten": len(missed),
            "seconds": round(sum(c["duration"] for c in cut), 1)}


def pct(x):
    return "-" if x is None else f"{100 * x:.0f}%"


def tune(rows, cfg, fillers, not_fillers, missed):
    """Standard mode under other rule settings: the best recall that keeps precision at 85% or more."""
    out = []
    for pause, mx, start in itertools.product((0.1, 0.15, 0.2, 0.3, 0.5), (0.4, 0.5, 0.6, 0.8), (True, False)):
        c2 = {**cfg, "rule": {"pause": pause, "max_seconds": mx, "phrase_start": start}}
        r = score(find_candidates(rows, c2), fillers, not_fillers, missed, "standard")
        out.append(({"pause": pause, "max_seconds": mx, "phrase_start": start}, r))
    return out


def report(s):
    s = Path(s)
    rows = read_json(s / "transcript.json")
    cfg = load_fillers(s)
    words = flat_words(rows)
    fillers, not_fillers, missed, saved = load_labels(s, words)
    cands = find_candidates(rows, cfg)
    meta = read_json(s / "session.json")
    lines = [f"# Filler removal on {s.name}: measured against the hand labels", "",
             f"Labels: {len(fillers)} filler words, {len(not_fillers)} words judged not a filler, "
             f"{len(missed)} fillers heard but not written; listened through {saved.get('listened', 0):.0f} s of "
             f"{meta['duration']:.0f} s. {sum(1 for c in cands if truth(c, fillers, not_fillers))} of {len(cands)} "
             f"candidates checked.", "",
             "| Mode | Removed | Real fillers | Not fillers | Precision | Recall (written fillers) | Recall (all) | Speech cut |",
             "|---|---|---|---|---|---|---|---|"]
    for mode in ("conservative", "standard"):
        r = score(cands, fillers, not_fillers, missed, mode)
        lines.append(f"| {mode} | {r['removed']} | {r['tp']} | {r['fp']} | {pct(r['precision'])} | "
                     f"{pct(r['recall_written'])} of {r['written']} | {pct(r['recall_all'])} of "
                     f"{r['written'] + r['unwritten']} | {r['seconds']} s |")
    # per entry: where the wrong removals come from
    lines += ["", "## Per word (Standard)", "", "| Entry | Removed | Real fillers | Not fillers | Kept but a filler |",
              "|---|---|---|---|---|"]
    by = collections.defaultdict(collections.Counter)
    for c in cands:
        t = truth(c, fillers, not_fillers)
        cut = c["decision"] in ("conservative", "standard")
        by[c["entry"]]["removed"] += cut
        by[c["entry"]]["tp"] += cut and t == "filler"
        by[c["entry"]]["fp"] += cut and t == "not"
        by[c["entry"]]["fn"] += (not cut) and t == "filler"
    for entry, n in sorted(by.items(), key=lambda kv: -(kv[1]["removed"] + kv[1]["fn"])):
        lines.append(f"| {entry} | {n['removed']} | {n['tp']} | {n['fp']} | {n['fn']} |")
    # the mistakes
    wrong = [c for c in removed_in(cands, "standard") if truth(c, fillers, not_fillers) == "not"]
    lines += ["", f"## Removed but not a filler ({len(wrong)})", ""]
    lines += [f"- {c['start']:.1f} s `{c['entry']}` ({c['reason']}): {c['context']}" for c in wrong]
    kept = [c for c in cands if c["decision"] == "kept" and truth(c, fillers, not_fillers) == "filler"]
    lines += ["", f"## Fillers it keeps ({len(kept)})", ""]
    lines += [f"- {c['start']:.1f} s `{c['entry']}` (kept: {c['reason']}): {c['context']}" for c in kept]
    if missed:
        lines += ["", f"## Fillers heard but not written ({len(missed)}): no word timing, so they can't be cut", "",
                  "- at " + ", ".join(f"{t:.1f} s" for t in missed)]
    # other rule settings
    tuned = tune(rows, cfg, fillers, not_fillers, missed)
    ok = [x for x in tuned if x[1]["precision"] is not None and x[1]["precision"] >= 0.85]
    lines += ["", "## Standard under other rule settings", "",
              "| pause (s) | max per word (s) | phrase start counts | Removed | Precision | Recall (written) |",
              "|---|---|---|---|---|---|"]
    for rule, r in sorted(tuned, key=lambda x: (-(x[1]["precision"] or 0), -(x[1]["recall_written"] or 0)))[:12]:
        lines.append(f"| {rule['pause']} | {rule['max_seconds']} | {rule['phrase_start']} | {r['removed']} | "
                     f"{pct(r['precision'])} | {pct(r['recall_written'])} |")
    if ok:
        best = max(ok, key=lambda x: (x[1]["recall_written"] or 0, x[1]["precision"]))
        lines += ["", f"Best setting with precision of 85% or more: {best[0]} -> precision {pct(best[1]['precision'])},"
                      f" recall {pct(best[1]['recall_written'])} of written fillers."]
    else:
        lines += ["", "No rule setting alone reaches 85% precision: the word list itself needs changes."]
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python -m eval.filler_eval <session folder> [...]")
    for arg in sys.argv[1:]:
        text = report(arg)
        out = Path(arg) / "review" / "filler_results.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        print(text)
        print(f"\nsaved: {out}\n")
