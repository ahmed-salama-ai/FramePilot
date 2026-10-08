# eval/wer.py  (Day 9) — caption accuracy: WER / CER of our transcript against text corrected by hand (wer_set.json)
#   python -m eval.wer          every session in wer_set.json        python -m eval.wer s01      one session
# Owner: Nada Ali (taken over by Ahmed Salama: a function for eval.run, unfinished references are skipped)
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESSIONS = ROOT / "data" / "sessions"
WER_SET = ROOT / "eval" / "wer_set.json"


def norm_ar(t):
    t = re.sub(r"[ً-ْـ]", "", t)   # remove tashkeel + tatweel
    t = re.sub(r"[إأآ]", "ا", t)
    t = t.replace("ى", "ي").replace("ة", "ه")
    return " ".join(re.sub(r"[^\w\s]", " ", t).split())


def norm_en(t):
    return " ".join(re.sub(r"[^\w\s']", " ", t.lower()).split())


def hyp_for(item, root=SESSIONS):
    """Our transcript's words between start and end (what the captions say)."""
    tr = json.loads(Path(f"{root}/{item['session']}/transcript.json").read_text(encoding="utf-8"))
    return " ".join(w["w"] for seg in tr for w in seg["words"]
                    if item["start"] <= w["start"] < item["end"])


def ready(item):
    """A reference someone has really typed (not the placeholder text)."""
    return bool(item["reference"].strip()) and "PASTE" not in item["reference"]


def wer_table(items, root=SESSIONS):
    """{"ar": {"wer", "cer", "words", "minutes"}, "en": {...}} over the ready items (a language without any: left out).
    WER = (wrong + missing + extra words) / words in the reference; CER = the same with letters. Lower is better."""
    out = {}
    for lang in ("ar", "en"):
        norm = norm_ar if lang == "ar" else norm_en
        sel = [x for x in items if x["lang"] == lang and ready(x)]
        if not sel:
            continue
        import jiwer                                 # only when there is text to score (pip package "jiwer")
        refs = [norm(x["reference"]) for x in sel]
        hyps = [norm(hyp_for(x, root)) for x in sel]
        out[lang] = {"wer": round(jiwer.wer(refs, hyps), 3), "cer": round(jiwer.cer(refs, hyps), 3),
                     "words": sum(len(r.split()) for r in refs),
                     "minutes": round(sum(x["end"] - x["start"] for x in sel) / 60, 1)}
    return out


def load_set(path=WER_SET):
    return json.loads(Path(path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    items = load_set()
    if len(sys.argv) > 1:
        items = [x for x in items if x["session"] == sys.argv[1]]
    table = wer_table(items)
    for lang, r in table.items():
        print(f"{lang}  WER {r['wer']:.3f}  CER {r['cer']:.3f}  ({r['words']} words, {r['minutes']} min)")
    if not table:
        print("No hand-corrected text yet: fill the 'reference' fields in eval/wer_set.json")
