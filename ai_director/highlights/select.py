# ai_director/highlights/select.py — the peaks of the interest curve -> candidate clips -> an LLM picks 3-5 + titles
# Owner: Sara Walid (taken over by Ahmed Salama)
import json

import numpy as np
from pydantic import BaseModel
from scipy.signal import find_peaks

from .interest import CFG

PROMPT = """You edit a talk show. Below are candidate moments (id, start and end in seconds, what was said).
Choose the {lo}-{hi} most interesting moments, the best first. For each one give: a short catchy title in Egyptian
Arabic (title_ar), the same title in English (title_en), and a one-line English hook that makes people want to watch
(hook). Only use ids from the list.
Candidates:
"""


class Pick(BaseModel):            # the answer format the LLM must follow
    id: int
    title_ar: str
    title_en: str
    hook: str


class Picks(BaseModel):
    picks: list[Pick]


def snap(segs, a0, b0, duration):
    """Clip times -> sentence boundaries: start at the start of a row, end at the end of a row, 20-45 s long."""
    lo, hi = CFG["min_length"], CFG["max_length"]
    a = max([r["start"] for r in segs if r["start"] <= a0], default=max(a0, 0.0))
    ends = [r["end"] for r in segs if a + lo <= r["end"] <= min(a + hi, duration)]
    b = min(ends, key=lambda e: abs(e - b0)) if ends else min(a + hi, duration)   # the row end nearest the plan
    return round(a, 2), round(b, 2)


def candidates(ev, segs, duration):
    """The best peaks (at least 30 s apart, in the top 15%), each as a clip window. Windows never overlap."""
    peaks, _ = find_peaks(ev.interest.values, distance=CFG["peak_distance"],
                          height=np.percentile(ev.interest, CFG["peak_percentile"]))
    out = []
    for p in sorted(peaks, key=lambda p: -ev.interest[p]):            # most interesting first
        a, b = snap(segs, ev.t[p] - CFG["before"], ev.t[p] + CFG["after"], duration)
        if b - a < CFG["min_length"] - 0.5 or any(a < c["end"] and c["start"] < b for c in out):
            continue                                                  # too short (video end) or overlapping
        rows = [r for r in segs if a <= r["start"] and r["end"] <= b]
        out.append({"id": len(out), "start": a, "end": b, "peak": float(ev.t[p]),
                    "interest": round(float(ev.interest[p]), 3),
                    "text": " ".join(r["text"] for r in rows)[:800],
                    "translation": " ".join(r.get("translation", "") for r in rows).strip()[:800]})
        if len(out) == CFG["candidates"]:
            break
    return out


def fallback(c, n, language):
    """Titles without an LLM: the first words of what was said (and of its translation)."""
    first = lambda text: " ".join(text.split()[:6])
    said, other = first(c["text"]), first(c["translation"])
    ar, en = (said, other) if language == "ar" else (other, said)
    return {"title_ar": ar, "title_en": en or f"Highlight {n}", "hook": ""}


def pick(cands, language, ask=None):
    """The LLM chooses and writes titles. Wrong ids are ignored, doubles removed; if it chose too few (or the LLM is
    not available), the most interesting remaining candidates are added with fallback titles."""
    lo, hi = min(CFG["min_picks"], len(cands)), min(CFG["max_picks"], len(cands))
    by_id, chosen = {c["id"]: c for c in cands}, []
    try:
        if ask is None:
            from ..brain.llm_client import chat_json                  # Eslam's client (needs the ollama package)
            from ..common.paths import CONFIGS
            import yaml
            model = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["ollama"]["text_model"]
            ask = lambda prompt: chat_json(model, prompt, Picks, think=False)
        brief = [{k: c[k] for k in ("id", "start", "end", "text", "translation")} for c in cands]
        for p in ask(PROMPT.format(lo=lo, hi=hi) + json.dumps(brief, ensure_ascii=False)).picks:
            if p.id in by_id and p.id not in [c["id"] for c, _ in chosen] and len(chosen) < hi:
                chosen.append((by_id[p.id], {"title_ar": p.title_ar.strip(), "title_en": p.title_en.strip(),
                                             "hook": p.hook.strip()}))
    except Exception as e:                                            # no ollama package / Ollama off / bad answer
        print(f"  WARNING: the LLM could not pick ({type(e).__name__}: {str(e)[:120]}) -> best peaks, simple titles")
    for c in cands:                                                   # too few chosen -> add the best remaining
        if len(chosen) >= lo:
            break
        if c["id"] not in [x["id"] for x, _ in chosen]:
            chosen.append((c, fallback(c, len(chosen) + 1, language)))
    return chosen
