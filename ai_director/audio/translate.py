# ai_director/audio/translate.py — every transcript row gets its translation (10 rows per LLM call: faster, keeps context)
# Owner: Nada Ali (edited by Ahmed Salama: works before Eslam's llm_client exists; model from configs; qwen3 answers
# without "thinking"; the GPU is freed at the end; 2026-10-08: numbers are a separate field (no more "1." in the
# captions), every answer is matched to ITS row by number, and an answer in the wrong language is asked again)
import json
import re
import urllib.request
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from ..common.io import read_json, write_json
from ..common.paths import CONFIGS

TEXT_MODEL = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["ollama"]["text_model"]
ARABIC = re.compile(r"[؀-ۿ]")
NUMBER = re.compile(r"^\s*\(?\d+\s*[.)\-:]\s*")                     # "1. ", "2) ", "(3) ", "4 - " at the start

try:
    from ..brain.llm_client import chat_json, unload                 # Eslam's client (needs the ollama package)
except ImportError:
    def chat_json(model, prompt, schema, think=False, **_):
        """Stand-in without the ollama package: ask local Ollama directly, answer forced into the schema."""
        body = {"model": model, "stream": False, "think": think, "keep_alive": 0,
                "options": {"temperature": 0.2}, "format": schema.model_json_schema(),
                "messages": [{"role": "user", "content": prompt}]}
        req = urllib.request.Request("http://localhost:11434/api/chat", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return schema.model_validate_json(json.loads(r.read())["message"]["content"])

    def unload(model):
        """Nothing to do: the stand-in already uses keep_alive 0."""


class Line(BaseModel):            # one translated row: its number is a separate field, never part of the text
    n: int
    text: str


class Lines(BaseModel):
    lines: list[Line]


class One(BaseModel):
    text: str


def clean(text):
    """Remove a number the model copied to the front anyway ("1. Hello" -> "Hello")."""
    return NUMBER.sub("", text).strip()


def right_language(text, to_arabic):
    """An English translation has no Arabic letters; an Arabic one has some. Empty = wrong."""
    return bool(text) and bool(ARABIC.search(text)) == to_arabic


def translate_one(text, target, to_arabic):
    """One row alone (when the batch answer was missing or in the wrong language). '' if it fails again."""
    try:
        t = clean(chat_json(TEXT_MODEL, f"Translate to {target}. Answer with the translation only.\n{text}",
                            One, think=False).text)
    except ValidationError:
        return ""
    return t if right_language(t, to_arabic) else ""


def run_translate(s: Path, batch_size=10):
    segs = read_json(s / "transcript.json")
    if segs and all(x.get("translation") for x in segs):
        return
    to_arabic = read_json(s / "session.json")["language"] == "en"
    target = "simple Egyptian Arabic" if to_arabic else "English"
    again = empty = 0
    for b in range(0, len(segs), batch_size):
        batch = segs[b:b + batch_size]
        prompt = (f"Translate each numbered line to {target}. Short and natural, like subtitles. "
                  f"Return one entry per line: n = the line's number, text = only its translation (no number).\n"
                  + "\n".join(f"{k}. {x['text']}" for k, x in enumerate(batch, 1)))
        try:
            got = {line.n: clean(line.text) for line in chat_json(TEXT_MODEL, prompt, Lines, think=False).lines}
        except ValidationError:
            got = {}
        for k, x in enumerate(batch, 1):
            t = got.get(k, "")
            if not right_language(t, to_arabic):                     # missing, not translated, or mixed up
                again += 1
                t = translate_one(x["text"], target, to_arabic)
                empty += not t
            x["translation"] = t
    write_json(s / "transcript.json", segs)
    unload(TEXT_MODEL)                                                # free the GPU for the next model
    print(f"  translated {len(segs)} rows ({again} asked again one by one, {empty} left empty)")
