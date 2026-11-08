# eval/style_report.py — Task 2: the same recording edited with every editing style (configs/styles.yaml), measured.
# The table goes in the pull request. Reads only: nothing is written into the sessions (unless --render).
#   python -m eval.style_report data/sessions/s01 [data/sessions/s02 ...] [--render]
# --render: the plain edit (no captions) of every style -> <session>/styles/<style>_nocaps.mp4, to watch them.
import sys
from pathlib import Path

import numpy as np

from ai_director.common.config import job_config, merged
from ai_director.common.io import read_json
from ai_director.director.run import decide
from ai_director.director.styles import load_styles, resolve
from eval.director_eval import edit_scores, speaking_cams

COLUMNS = [("Cuts / min", "cuts_per_min"), ("Avg shot (s)", "avg_shot"), ("Shots", "shots"),
           ("Shortest (s)", "shortest"), ("Longest, 1 camera (s)", "longest_single"),
           ("Longest incl. split (s)", "longest"), ("Splits", "splits"), ("Split time %", "split_share"),
           ("Wide shot %", "wide_share"), ("Speaker on screen %", "speaker_coverage")]


def rhythm(cuts, wide=None):
    """The rhythm numbers of one edit. Cuts / min = camera changes per minute; the last shot ends with the video,
    so it is not counted as the shortest; a split screen may be longer than the longest shot (configs/styles.yaml)."""
    dur = cuts[-1]["end"] - cuts[0]["start"]
    shots = [c["end"] - c["start"] for c in cuts]
    single = [c["end"] - c["start"] for c in cuts if not c.get("split")]
    split_time = sum(c["end"] - c["start"] for c in cuts if c.get("split"))
    wide_time = sum(c["end"] - c["start"] for c in cuts if c["cam"] == wide and not c.get("split"))
    return {"shots": len(cuts), "cuts_per_min": round((len(cuts) - 1) / (dur / 60), 2),
            "avg_shot": round(dur / len(cuts), 2), "shortest": round(min(shots[:-1] or shots), 2),
            "longest_single": round(max(single), 2) if single else None, "longest": round(max(shots), 2),
            "splits": sum(1 for c in cuts if c.get("split")), "split_share": round(100 * split_time / dur, 1),
            "wide_share": round(100 * wide_time / dur, 1)}


def named_styles():
    return [pid for pid, p in load_styles()["presets"].items() if not p.get("custom")]


def style_settings(s, pid):
    """This session's settings with the style `pid` instead of the session's own."""
    return merged(job_config(s), resolve(pid)["config"])


def style_rows(s):
    """One row per named style: its edit of session `s`, measured."""
    s = Path(s)
    meta = read_json(s / "session.json")
    wide = next(c["id"] for c in meta["cameras"] if c["role"] == "wide")
    times = np.round(np.arange(0, meta["duration"], 0.1), 2)
    speaking = speaking_cams(s, times) if (s / "diarization.json").exists() else None
    names = load_styles()["presets"]
    rows = []
    for pid in named_styles():
        cuts, _ = decide(s, cfg=style_settings(s, pid))
        cover = edit_scores(cuts, times, speaking)["speaker_coverage"] if speaking is not None else None
        rows.append({"session": s.name, "style": pid, "name": names[pid]["name"]["en"], **rhythm(cuts, wide),
                     "speaker_coverage": None if cover is None else round(100 * cover, 1)})
    return rows


def markdown(rows):
    """The table for the pull request, + how much more often the liveliest style cuts than the calmest."""
    head = "| Session | Style | " + " | ".join(t for t, _ in COLUMNS) + " |"
    lines = [head, "|" + "---|" * (len(COLUMNS) + 2)]
    for r in rows:
        lines.append(f"| {r['session']} | {r['name']} | " + " | ".join("-" if r[k] is None else str(r[k])
                                                                     for _, k in COLUMNS) + " |")
    for session in dict.fromkeys(r["session"] for r in rows):
        mine = [r for r in rows if r["session"] == session]
        calm, lively = min(mine, key=lambda r: r["cuts_per_min"]), max(mine, key=lambda r: r["cuts_per_min"])
        more = 100 * (lively["cuts_per_min"] - calm["cuts_per_min"]) / calm["cuts_per_min"]
        lines.append(f"\n{session}: {lively['name']} vs {calm['name']}: {more:+.0f}% cuts per minute "
                     f"({lively['cuts_per_min']} vs {calm['cuts_per_min']})")
    return "\n".join(lines)


def render_styles(s, folder="styles"):
    """Every named style's plain edit (no captions, no brand) -> <s>/<folder>/<style>_nocaps.mp4."""
    from ai_director.director.render import render_program
    s = Path(s)
    (s / folder).mkdir(exist_ok=True)
    out = []
    for pid in named_styles():
        cfg = style_settings(s, pid)
        cuts, _ = decide(s, cfg=cfg)
        out.append(render_program(s, cuts, out=f"{folder}/{pid}_nocaps.mp4", cfg=cfg))
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit("usage: python -m eval.style_report <session folder> [...] [--render]")
    print(markdown([r for a in args for r in style_rows(Path(a))]))
    if "--render" in sys.argv:
        for a in args:
            for path in render_styles(Path(a)):
                print("made", path)
