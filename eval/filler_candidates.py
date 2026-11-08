import collections
import csv
import sys
from pathlib import Path

from ai_director.audio.fillers import find_candidates, load_fillers, removed_in
from ai_director.common.io import read_json

COLUMNS = ["start", "end", "duration", "text", "entry", "group", "decision", "reason", "gap_before", "gap_after",
           "phrase_start", "phrase_end", "turn_start", "row", "context"]


def session_candidates(s):
    s = Path(s)
    return find_candidates(read_json(s / "transcript.json"), load_fillers(s))


def write_csv(cands, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:          # utf-8-sig: Excel shows Arabic correctly
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for c in cands:
            w.writerow({k: c[k] for k in COLUMNS})


def summary(s, cands):
    meta = read_json(Path(s) / "session.json")
    minutes = meta["duration"] / 60
    lines = [f"## {Path(s).name} ({meta['language']}, {minutes:.1f} min): {len(cands)} candidates"]
    for mode in ("conservative", "standard"):
        cut = removed_in(cands, mode)
        secs = sum(c["duration"] for c in cut)
        lines.append(f"- {mode}: removes {len(cut)} ({len(cut) / minutes:.1f} per minute), {secs:.1f} s of speech")
    lines.append("")
    lines.append("| Entry | Found | Conservative | Standard | Kept |")
    lines.append("|---|---|---|---|---|")
    by = collections.defaultdict(collections.Counter)
    for c in cands:
        by[c["entry"]][c["decision"]] += 1
    for entry, n in sorted(by.items(), key=lambda kv: -sum(kv[1].values())):
        lines.append(f"| {entry} | {sum(n.values())} | {n['conservative']} | {n['standard']} | {n['kept']} |")
    reasons = collections.Counter(c["reason"] for c in cands if c["decision"] == "kept")
    if reasons:
        lines.append("")
        lines.append("Kept because: " + "; ".join(f"{r} ({k})" for r, k in reasons.most_common()))
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python -m eval.filler_candidates <session folder> [...]")
    for arg in sys.argv[1:]:
        cands = session_candidates(arg)
        out = Path(arg) / "review" / "filler_candidates.csv"
        write_csv(cands, out)
        print(summary(arg, cands))
        print(f"\nfull list: {out}\n")
