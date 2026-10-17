# eval/highlight_eval.py — do our top-3 highlights match the moments humans marked? (precision@3)
#   python -m eval.highlight_eval data/sessions/s01
# Needs highlight_labels.csv in the session (start,end,reason: made with the web app's labelling tool, or by hand).
# Owner: Sara Walid (taken over by Ahmed Salama)
import sys
from pathlib import Path

import pandas as pd

from ai_director.common.io import read_json


def iou(a, b):
    """Overlap of two time ranges / their total span: 0 = apart, 1 = the same range."""
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    return inter / (max(a[1], b[1]) - min(a[0], b[0]))


def precision_at_3(s, min_iou=0.3):
    """Share of our first 3 highlights that overlap (IoU >= 0.3) at least one human-marked moment."""
    human = pd.read_csv(s / "highlight_labels.csv")
    ours = read_json(s / "highlights.json")[:3]
    hits = [max((iou((h["start"], h["end"]), (r.start, r.end)) for r in human.itertuples()), default=0) >= min_iou
            for h in ours]
    return (sum(hits) / len(ours) if ours else 0.0), hits


if __name__ == "__main__":
    s = Path(sys.argv[1])
    p, hits = precision_at_3(s)
    print(f"precision@3 = {p:.2f}  (hits per highlight: {hits})")
