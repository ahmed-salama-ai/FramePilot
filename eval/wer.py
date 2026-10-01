# eval/wer.py  (Day 9) - python eval/wer.py   -> WER / CER for Arabic and English
import re, json
from pathlib import Path
import jiwer


def norm_ar(t):
    t = re.sub(r"[\u064B-\u0652\u0640]", "", t)   # remove tashkeel + tatweel
    t = re.sub(r"[إأآ]", "ا", t)
    t = t.replace("ى", "ي").replace("ة", "ه")
    return " ".join(re.sub(r"[^\w\s]", " ", t).split())


def norm_en(t):
    return " ".join(re.sub(r"[^\w\s']", " ", t.lower()).split())


def hyp_for(item, root="data/sessions"):
    tr = json.loads(Path(f"{root}/{item['session']}/transcript.json").read_text(encoding="utf-8"))
    return " ".join(w["w"] for seg in tr for w in seg["words"]
                    if item["start"] <= w["start"] < item["end"])


if __name__ == "__main__":
    wer_set = json.loads(Path("eval/wer_set.json").read_text(encoding="utf-8"))
    for lang in ("ar", "en"):
        norm = norm_ar if lang == "ar" else norm_en
        refs, hyps = [], []
        for item in [x for x in wer_set if x["lang"] == lang]:
            refs.append(norm(item["reference"]))
            hyps.append(norm(hyp_for(item)))
        if refs:
            print(lang, "WER", round(jiwer.wer(refs, hyps), 3), "CER", round(jiwer.cer(refs, hyps), 3))
