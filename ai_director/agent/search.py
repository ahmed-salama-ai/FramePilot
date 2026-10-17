import hashlib
import json
from itertools import takewhile

import numpy as np
import yaml

from ..common.io import read_json
from ..common.paths import CONFIGS

_ALL = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))
CFG, OLLAMA = _ALL["agent"], _ALL["ollama"]


def windows(segs, length=None, step=None):
    """The transcript as overlapping 30s pieces made of whole rows so every piece starts and ends with a sentence"""
    length, step = length or CFG["window_seconds"], step or CFG["window_step"]
    out, last = [], None
    for i, r in enumerate(segs):
        if last is not None and r["start"] < last + step:
            continue                                                  #a new piece every 10s
        rows = list(takewhile(lambda x: x["end"] <= r["start"] + length, segs[i:])) or [r]
        if out and rows[-1]["end"] <= out[-1]["end"]:
            continue                                                  #the end of the video
        out.append({"start": r["start"], "end": rows[-1]["end"], "rows": rows})
        last = r["start"]
    return out


def piece_text(w):
    text = " ".join(r["text"] for r in w["rows"])
    translation = " ".join(r.get("translation", "") for r in w["rows"]).strip()
    return f"{text} | {translation}" if translation else text


_CLIENT = []


def ollama_client():
    if not _CLIENT:
        import ollama
        _CLIENT.append(ollama.Client(timeout=CFG["timeout"]))
    return _CLIENT[0]


def embed(texts):
    vecs = [np.array(ollama_client().embed(model=OLLAMA["embed_model"], input=texts[i:i + 32],
                                           keep_alive=CFG["keep_alive"]).embeddings, dtype="float32")
            for i in range(0, len(texts), 32)]
    v = np.vstack(vecs)
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-10)


def moment(w, score):
    """One search result: where (start/end = sentence edges), who talks most, what was said (shortened)."""
    talk = {}
    for r in w["rows"]:
        talk[r["speaker"]] = talk.get(r["speaker"], 0) + r["end"] - r["start"]
    short = lambda t: t if len(t) <= 200 else t[:200] + "…"
    return {"start": round(w["start"], 2), "end": round(w["end"], 2), "speaker": max(talk, key=talk.get),
            "text": short(" ".join(r["text"] for r in w["rows"])),
            "translation": short(" ".join(r.get("translation", "") for r in w["rows"]).strip()),
            "score": round(float(score), 3)}


def topic(pieces, scores, i, taken=(), drop=None, longest=None):
    drop, longest = drop or CFG["topic_drop"], longest or CFG["topic_max"]
    a = b = i
    while True:
        near = [j for j in (a - 1, b + 1) if 0 <= j < len(pieces) and scores[j] >= scores[i] - drop
                and pieces[max(b, j)]["end"] - pieces[min(a, j)]["start"] <= longest
                and not any(pieces[j]["start"] < m["end"] and m["start"] < pieces[j]["end"] for m in taken)]
        if not near:
            return a, b
        j = max(near, key=lambda j: scores[j])
        a, b = min(a, j), max(b, j)


def search(s, query, top_k=5, embed=embed):
    segs = read_json(s / "transcript.json")
    if not segs:
        return []
    pieces = windows(segs)
    settings = json.dumps([OLLAMA["embed_model"], CFG["window_seconds"], CFG["window_step"]]).encode()
    key = hashlib.md5((s / "transcript.json").read_bytes() + settings).hexdigest()
    index, key_file = s / "search_index.npy", s / "tmp" / "search_index.key"
    if index.exists() and key_file.exists() and key_file.read_text() == key:
        vecs = np.load(index)
    else:
        vecs = embed([piece_text(w) for w in pieces])
        np.save(index, vecs)
        key_file.parent.mkdir(exist_ok=True)
        key_file.write_text(key)
    scores = vecs @ embed([query])[0]                                 # cosine similarity (all vectors have length 1)
    out = []
    for i in np.argsort(-scores):
        w = pieces[i]
        if any(w["start"] < m["end"] and m["start"] < w["end"] for m in out):
            continue                                                  # overlaps a better piece: same moment
        a, b = topic(pieces, scores, i, out)
        out.append({**moment(w, scores[i]), "start": round(pieces[a]["start"], 2), "end": round(pieces[b]["end"], 2)})
        if len(out) == top_k:
            break
    return out


_MARKS = dict.fromkeys(list(range(0x064B, 0x0653)) + [0x0670, 0x0640])          # Arabic short vowels + tatweel
_SAME = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})


def normal(text):
    return " ".join(text.translate(_MARKS).translate(_SAME).lower().split())


def find_words(s, query, limit=50):
    import re
    q = normal(query)
    if not q:
        return []
    pattern = re.compile((r"(?<![a-z0-9])" if q[0].isascii() else "") + re.escape(q))
    out = []
    for r in read_json(s / "transcript.json"):
        if pattern.search(normal(r.get("text", ""))) or pattern.search(normal(r.get("translation", ""))):
            out.append({k: r.get(k) for k in ("start", "end", "speaker", "text", "translation")})
            if len(out) == limit:
                break
    return out
