import json
import re
import urllib.request
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from ..common.io import read_json, write_json
from ..common.paths import CONFIGS
from .bleep import MARKS, bleep_enabled, mark_source, normalize, save_marks, saved_marks, session_phrases, split_marks

_CFG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))
TEXT_MODEL = _CFG["ollama"]["text_model"]
GEMINI_MODEL = _CFG["audio"].get("translate_model")
ARABIC = re.compile(r"[؀-ۿ]")
NUMBER = re.compile(r"^\s*\(?\d+\s*[.)\-:]\s*")

try:
    from ..brain.llm_client import chat_json, unload
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


class Line(BaseModel):
    n: int
    text: str


class Lines(BaseModel):
    lines: list[Line]


class MarkedLines(BaseModel):
    """The separate call's answer: each translation as given, the bleeped words' translation in [[ ]]."""
    lines: list[Line]


class One(BaseModel):
    text: str


def clean(text):
    """Remove a number the model copied to the front anyway ("1. Hello" -> "Hello")."""
    return NUMBER.sub("", text).strip()


def right_language(text, to_arabic):
    """An English translation has no Arabic letters; an Arabic one has some. Empty = wrong."""
    return bool(text) and bool(ARABIC.search(text)) == to_arabic


def target_language(to_arabic):
    return "simple Egyptian Arabic" if to_arabic else "English"


def batch_prompt(batch, target, from_arabic, before=(), after=(), texts=None):
    """The translation request for up to 10 rows. texts = the lines as shown (bleeped words in [[ ]])."""
    texts = texts or [x["text"] for x in batch]
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
    if any(t != x["text"] for t, x in zip(texts, batch)):
        lines.append("Words in [[ ]] will be bleeped: translate them normally and put [[ ]] around the words of your "
                     "translation that mean them.")
    lines.append("Return one entry per line: n = the line's number, text = only its translation (no number).")
    return "\n".join(lines + [f"{k}. {t}" for k, t in enumerate(texts, 1)])


def ask_gemini(prompt, schema):
    """The same request answered by Gemini (audio.translate_model). A bad answer -> ValidationError"""
    from .gemini import ask_json
    return ask_json(GEMINI_MODEL, prompt, schema)


class Translator:
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
            except Exception as e:
                print(f"  Gemini translation stopped ({type(e).__name__}: {str(e)[:120]}) -> {TEXT_MODEL} for the rest")
                self.gemini = False
        self.used.add(TEXT_MODEL)
        return chat_json(TEXT_MODEL, prompt, schema, think=False)


def translate_one(text, target, to_arabic, context="", ask=None):
    """One row alone (when the batch answer was missing or in the wrong language). '' if it fails again."""
    ask = ask or Translator()
    note = f"Context (do not translate): {context}\n" if context else ""
    try:
        t = split_marks(clean(ask(f"{note}Translate to {target}. Answer with the translation only.\n{text}",
                                  One).text))[0]
    except ValidationError:
        return ""
    return t if right_language(t, to_arabic) else ""


def marks_in(answer, translation):
    """The [[ ]] word positions of `answer` if it is `translation` word for word (case and punctuation aside), else []."""
    plain, hide = split_marks(answer)
    a, b = plain.split(), str(translation).split()
    same = len(a) == len(b) and all(normalize(x) == normalize(y) for x, y in zip(a, b))
    return hide if same else []


def mark_translations(rows, phrases, target, ask=None, tries=2, batch_size=20):
    """The separate call: which words of each row's existing translation mean its bleeped words. Saves them in the row
    (row[MARKS]); the translation itself is never changed. A row the model keeps getting wrong is left as it was (only
    listed words starred in its translation) with a warning. Returns how many rows got their marks."""
    ask = ask or Translator()
    todo = [r for r in rows if r.get("translation") and mark_source(r.get("words") or [], phrases)]
    done = 0
    for _ in range(tries):
        left = []
        for b in range(0, len(todo), batch_size):
            batch = todo[b:b + batch_size]
            prompt = "\n".join(
                [f"Each numbered item is a line of a conversation, with the words that will be bleeped in [[ ]], and "
                 f"its {target} translation. Return each translation exactly as given, word for word, only with "
                 f"[[ ]] around the words that translate the [[ ]] words of the line. n = the item's number."]
                + [f"{k}. {mark_source(r['words'], phrases)}\n   {target}: {r['translation']}"
                   for k, r in enumerate(batch, 1)])
            try:
                got = {line.n: line.text for line in ask(prompt, MarkedLines).lines}
            except Exception as e:                                       #a bad answer or no model: try again
                print(f"  bleeped words in the translation: no answer ({type(e).__name__}: {str(e)[:120]})")
                got = {}
            for k, r in enumerate(batch, 1):
                hide = marks_in(got.get(k, ""), r["translation"])
                if hide:
                    save_marks(r, hide)
                    done += 1
                else:
                    left.append(r)
        todo = left
        if not todo:
            break
    for r in todo:
        print(f"  WARNING: row {r.get('id')}: the bleeped words were not found in its translation, only listed words "
              f"are starred there ({r['translation'][:60]})")
    return done


def refresh_bleep_marks(s: Path, rows):
    """After a caption edit: the separate call for the given rows that have a bleeped word but no marks for their
    current text and translation. Changes the rows in place; returns how many got marks."""
    s = Path(s)
    for r in rows:
        if saved_marks(r) is None:
            r.pop(MARKS, None)                                           #made for the text before the edit
    if not bleep_enabled(s):
        return 0
    phrases = session_phrases(s)
    todo = [r for r in rows if r.get("translation") and MARKS not in r and mark_source(r.get("words") or [], phrases)]
    if not todo:
        return 0
    ask = Translator()
    try:
        return mark_translations(todo, phrases, target_language(read_json(s / "session.json")["language"] == "en"),
                                 ask)
    finally:
        if TEXT_MODEL in ask.used:
            unload(TEXT_MODEL)


def run_translate(s: Path, batch_size=10, again=False):
    """again=True: translate every row anew (e.g. after the prompt got better). With bleeping on, the bleeped words go
    in [[ ]] and the translator marks their translation the same way (saved in the row, the [[ ]] removed)."""
    segs = read_json(s / "transcript.json")
    if segs and all(x.get("translation") for x in segs) and not again:
        return
    to_arabic = read_json(s / "session.json")["language"] == "en"
    target = target_language(to_arabic)
    phrases = session_phrases(s) if bleep_enabled(s) else None
    marked = [mark_source(x.get("words") or [], phrases) if phrases else None for x in segs]
    ask, retried, empty = Translator(), 0, 0
    for b in range(0, len(segs), batch_size):
        batch = segs[b:b + batch_size]
        prompt = batch_prompt(batch, target, not to_arabic, segs[max(0, b - 2):b],
                              segs[b + batch_size:b + batch_size + 2],
                              [marked[b + k] or x["text"] for k, x in enumerate(batch)])
        try:
            got = {line.n: clean(line.text) for line in ask(prompt, Lines).lines}
        except ValidationError:
            got = {}
        for k, x in enumerate(batch, 1):
            i = b + k - 1
            t, hide = split_marks(got.get(k, ""))
            if not right_language(t, to_arabic):
                retried += 1
                around = " / ".join(r["text"] for r in segs[max(0, i - 2):i + 3] if r is not x)
                t, hide = translate_one(x["text"], target, to_arabic, around, ask), []
                empty += not t
            x["translation"] = t
            x.pop(MARKS, None)
            if marked[i] and hide:
                save_marks(x, hide)
    missing = [x for i, x in enumerate(segs) if marked[i] and x["translation"] and MARKS not in x]
    if missing:                                                          #marks dropped or a row translated alone
        mark_translations(missing, phrases, target, ask)
    write_json(s / "transcript.json", segs)
    if TEXT_MODEL in ask.used:
        unload(TEXT_MODEL)
    print(f"  translated {len(segs)} rows with {' + '.join(sorted(ask.used)) or 'nothing'} "
          f"({retried} asked again one by one, {empty} left empty"
          + (f", {sum(MARKS in x for x in segs)}/{sum(map(bool, marked))} bleeped rows marked" if phrases else "")
          + ")")


if __name__ == "__main__":
    import sys
    from ..common.io import session_from_argv
    run_translate(session_from_argv(), again="--again" in sys.argv)
