# ai_director/audio/translate.py — every transcript row gets its translation (10 rows per LLM call: faster, keeps context)
# Owner: Nada Ali (edited by Ahmed Salama: works before Eslam's llm_client exists; model from configs; qwen3 answers
# without "thinking"; the GPU is freed at the end; 2026-10-08: numbers are a separate field (no more "1." in the
# captions), every answer is matched to ITS row by number, and an answer in the wrong language is asked again;
# 2026-10-09: Gemini (audio.translate_model) first, the local qwen3:8b only when Gemini can't be used)
import json
import re
import urllib.request
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from ..common.io import read_json, write_json
from ..common.paths import CONFIGS

_CFG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))
TEXT_MODEL = _CFG["ollama"]["text_model"]                           # the local model (also the plan B)
GEMINI_MODEL = _CFG["audio"].get("translate_model")                 # 2026-10-09: Gemini first (null = local only)
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


def batch_prompt(batch, target, from_arabic, before=(), after=()):
    """The translation request for up to 10 rows. 2026-10-08: the rows around the batch go in as context and the model
    is told the lines are ONE conversation (one-word rows were translated alone: "فاضيين" -> "Empty"), and that
    Egyptian speakers say English words in Arabic letters (Gemini writes "موديل", "اليوزر": they came back as "a robot",
    "Yousers")."""
    ctx = lambda rows: " / ".join(x["text"] for x in rows)
    lines = [f"Translate each numbered line to {target}. Short and natural, like subtitles. The lines are consecutive "
             f"lines of ONE conversation between several people: translate every line in the context of the lines "
             f"around it (a short line like a single word is usually a reply to the line before)."]
    if from_arabic:
        lines.append("Egyptian speakers often say English words written in Arabic letters (موديل = model, "
                     "اليوزر = the user, اودبوت = output, داتا = data, ايكورسي = accuracy): translate them as those "
                     "English words.")
    if before:
        lines.append(f"Said just before (context only, do not translate): {ctx(before)}")
    if after:
        lines.append(f"Said just after (context only, do not translate): {ctx(after)}")
    lines.append("Return one entry per line: n = the line's number, text = only its translation (no number).")
    return "\n".join(lines + [f"{k}. {x['text']}" for k, x in enumerate(batch, 1)])


def ask_gemini(prompt, schema):
    """The same request answered by Gemini (audio.translate_model). A bad answer -> ValidationError (like the local
    model); no usable key (daily limit, no internet) -> RuntimeError and others."""
    from .gemini import ask_json                                     # import only when Gemini is really used
    return ask_json(GEMINI_MODEL, prompt, schema)


class Translator:
    """Asks Gemini (audio.translate_model) while it works, then the local model (ollama.text_model) for the rest.
    2026-10-09, s01 + s03 with the same prompt: gemini-3.1-flash-lite better on 19 of 37 sample lines, qwen3:8b on 1
    (qwen: "البني ادمين" -> "admins", "المدارس الفنيه" -> "art schools", "اي بي اي" -> "AI", "فاضيين" -> "Empty");
    no GPU needed, 1-2 min per session, ~20-26 requests."""
    def __init__(self):
        self.gemini, self.used = bool(GEMINI_MODEL), set()

    def __call__(self, prompt, schema):
        if self.gemini:
            try:
                answer = ask_gemini(prompt, schema)
                self.used.add(GEMINI_MODEL)
                return answer
            except ValidationError:
                raise
            except Exception as e:                                   # no key / limit / no internet: local from now on
                print(f"  Gemini translation stopped ({type(e).__name__}: {str(e)[:120]}) -> {TEXT_MODEL} for the rest")
                self.gemini = False
        self.used.add(TEXT_MODEL)
        return chat_json(TEXT_MODEL, prompt, schema, think=False)


def translate_one(text, target, to_arabic, context="", ask=None):
    """One row alone (when the batch answer was missing or in the wrong language). '' if it fails again."""
    ask = ask or Translator()
    note = f"Context (do not translate): {context}\n" if context else ""
    try:
        t = clean(ask(f"{note}Translate to {target}. Answer with the translation only.\n{text}", One).text)
    except ValidationError:
        return ""
    return t if right_language(t, to_arabic) else ""


def run_translate(s: Path, batch_size=10, again=False):
    """again=True: translate every row anew (e.g. after the prompt got better)."""
    segs = read_json(s / "transcript.json")
    if segs and all(x.get("translation") for x in segs) and not again:
        return
    to_arabic = read_json(s / "session.json")["language"] == "en"
    target = "simple Egyptian Arabic" if to_arabic else "English"
    ask, retried, empty = Translator(), 0, 0
    for b in range(0, len(segs), batch_size):
        batch = segs[b:b + batch_size]
        prompt = batch_prompt(batch, target, not to_arabic, segs[max(0, b - 2):b],
                              segs[b + batch_size:b + batch_size + 2])
        try:
            got = {line.n: clean(line.text) for line in ask(prompt, Lines).lines}
        except ValidationError:
            got = {}
        for k, x in enumerate(batch, 1):
            t = got.get(k, "")
            if not right_language(t, to_arabic):                     # missing, not translated, or mixed up
                retried += 1
                i = b + k - 1
                around = " / ".join(r["text"] for r in segs[max(0, i - 2):i + 3] if r is not x)
                t = translate_one(x["text"], target, to_arabic, around, ask)
                empty += not t
            x["translation"] = t
    write_json(s / "transcript.json", segs)
    if TEXT_MODEL in ask.used:
        unload(TEXT_MODEL)                                            # free the GPU for the next model
    print(f"  translated {len(segs)} rows with {' + '.join(sorted(ask.used)) or 'nothing'} "
          f"({retried} asked again one by one, {empty} left empty)")


if __name__ == "__main__":      # python -m ai_director.audio.translate data/sessions/s01 --again   (translate anew)
    import sys
    from ..common.io import session_from_argv
    run_translate(session_from_argv(), again="--again" in sys.argv)
