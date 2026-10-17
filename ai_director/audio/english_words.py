import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import soundfile as sf
import yaml
from pydantic import BaseModel

from ..common.io import read_json, session_from_argv, write_json
from ..common.paths import CONFIGS
from .gemini import clients, with_keys

CFG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["audio"]
ARABIC = re.compile(r"[؀-ۿ]")
LATIN = re.compile(r"[A-Za-z]")

PROMPT = """This audio is part of a conversation in Egyptian Arabic. The people often use English words (technical
terms, names of models, products and companies).
Below are numbered lines: their start and end time in THIS audio, the speaker, and the draft text from a
speech-to-text system. The draft is good, BUT it often LEAVES OUT the English words, or writes them in Arabic letters.
Correct each draft line using the audio:
- Put back every English word that was said in that line, in English letters, where it was said
  (for example: accuracy, users, model, API, LLM).
- An English word written in Arabic letters (for example ايكورسي, يوزرز) -> the English word (accuracy, users).
- Keep every other word of the draft exactly as it is (same Arabic words, same spelling). Do not move words to
  another line, do not add or remove Arabic words, do not translate, do not change it to Modern Standard Arabic.
Return every numbered line with its number, also the lines that need no change.
{context}
{lines}"""


class Line(BaseModel):
    n: int
    text: str


class Lines(BaseModel):
    lines: list[Line]


def windows(rows, seconds=60.0):
    """Rows -> groups of neighbouring rows that last at most `seconds` together (a row is never cut)."""
    out, cur = [], []
    for r in rows:
        if cur and r["end"] - cur[0]["start"] > seconds:
            out.append(cur)
            cur = []
        cur.append(r)
    return out + [cur] if cur else out


def prompt_for(rows, t0, before=(), after=()):
    """The prompt for one window; times are given from the start of the window's audio (t0). before/after = the
    neighbouring lines, in the audio and the prompt as context only: a word at the edge of a window needs what was
    said just before it (s03 3:08 "Qwen", right after a window edge, was heard as "Cohere" without it)."""
    line = lambda r: f'{r["start"] - t0:.1f}-{r["end"] - t0:.1f} s, {r["speaker"]} | draft: {r["text"]}'  # noqa: E731
    context = ""
    if before or after:
        context = ("\nContext only (said just before / after these lines, do NOT return them):\n"
                   + "\n".join(f"- {line(r)}" for r in [*before, *after]) + "\n")
    return PROMPT.format(context=context, lines="\n".join(f"{i}. {line(r)}" for i, r in enumerate(rows, 1)))


def ask_flash(path, prompt, model, start=0, keyed=None):
    def call(client):
        f = client.files.upload(file=str(path))
        try:
            r = client.models.generate_content(model=model, contents=[f, prompt], config={
                "response_mime_type": "application/json", "response_schema": Lines, "temperature": 0,
                "http_options": {"timeout": 180_000}})
            return {x.n: x.text for x in r.parsed.lines} if r.parsed else {}
        finally:
            try:
                client.files.delete(name=f.name)                      #delete audio
            except Exception:
                pass
    return with_keys(call, start=start, keyed=keyed)


def plain(text):
    """plain arabic words"""
    text = re.sub(r"[ً-ْـ]", "", text)
    text = re.sub("[أإآ]", "ا", text).replace("ة", "ه").replace("ى", "ي")
    return {w.strip(".,!?؟،") for w in text.split() if ARABIC.search(w)}


def plausible(draft, new):
    old = {w for w in plain(draft) if len(w) >= 3}
    return len(old) < 3 or len(old & plain(new)) >= len(old) / 2


def spread(row, text):
    ws = text.split()
    step = (row["end"] - row["start"]) / len(ws)
    words = [{"w": w, "start": round(row["start"] + i * step, 2), "end": round(row["start"] + (i + 1) * step, 2)}
             for i, w in enumerate(ws)]
    return {**row, "text": text, "translation": "", "words": words}


def fix_english_words(s: Path, ask=ask_flash):
    model = CFG.get("english_words_model")
    if not model or read_json(s / "session.json")["language"] != "ar":
        return 0
    rows = read_json(s / "transcript.json")
    (s / "tmp").mkdir(exist_ok=True)
    first = s / "tmp" / "transcript_asr.json"
    key = lambda rs: [(r["id"], r["start"], r["end"]) for r in rs]
    if first.exists() and key(read_json(first)) == key(rows):
        draft = read_json(first)                                       #already done
    else:
        draft = rows
        write_json(first, rows)
    audio, sr = sf.read(s / "audio.wav", dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    groups = windows(draft, CFG.get("english_words_window", 60))
    keyed = clients() if ask is ask_flash else []
    pos = {r["id"]: i for i, r in enumerate(draft)}
    fallback = CFG.get("english_words_fallback")
    main_ok = [True]                                  #once the main model fails the other windows skip it

    def one(k):
        g = groups[k]
        i0, i1 = pos[g[0]["id"]], pos[g[-1]["id"]]
        before = [r for r in draft[max(i0 - 2, 0):i0] if r["end"] >= g[0]["start"] - 10]   #2 lines of context
        after = [r for r in draft[i1 + 1:i1 + 3] if r["start"] <= g[-1]["end"] + 10]       #each side, if near
        t0, t1 = max((before or g)[0]["start"] - 0.5, 0.0), (after or g)[-1]["end"] + 0.5
        prompt = prompt_for(g, t0, before, after)
        raw = s / "tmp" / f"gemini_words_{k:03d}.json"
        if raw.exists():                                 #saved answer for the same draft lines
            saved = read_json(raw)
            if saved.get("prompt") == prompt and saved.get("model") in (model, fallback):
                return {int(n): t for n, t in saved["lines"].items()}
        path = s / "tmp" / f"words_piece_{k:03d}.wav"
        sf.write(path, audio[int(t0 * sr):int(t1 * sr)], sr, subtype="PCM_16")
        try:
            used = model if main_ok[0] or not fallback else fallback
            try:
                lines, name = ask(path, prompt, used, start=k, keyed=keyed or None)
            except Exception as e:                       #no quota left or no key works >> the fallback model
                if used == fallback or not fallback:
                    raise
                main_ok[0] = False
                print(f"    {model} can't be used ({type(e).__name__}: {str(e)[:100]}) -> {fallback}", flush=True)
                used = fallback
                lines, name = ask(path, prompt, used, start=k, keyed=keyed or None)
        finally:
            path.unlink(missing_ok=True)
        write_json(raw, {"model": used, "prompt": prompt, "key": name,
                         "lines": {str(n): t for n, t in lines.items()}})
        print(f"    window {k + 1}/{len(groups)} ({t0:.0f}-{t1:.0f} s) done with {used} ({name})", flush=True)
        return lines

    with ThreadPoolExecutor(max_workers=max(len(keyed), 1)) as pool:   #one worker per key
        answers = list(pool.map(one, range(len(groups))))
    by_id = {r["id"]: r for r in rows}
    changed = ignored = 0
    for g, lines in zip(groups, answers):
        for i, d in enumerate(g, 1):
            new = " ".join(str(lines.get(i, "")).split())
            if not new or new == by_id[d["id"]]["text"]:
                continue
            if not plausible(d["text"], new):                          #the answer slid to a neighbouring line
                ignored += 1
                continue
            by_id[d["id"]] = spread(by_id[d["id"]], new)
            changed += 1
    out = [by_id[r["id"]] for r in rows]
    if changed:
        write_json(s / "transcript.json", out)
    english = sum(bool(LATIN.search(w)) for r in out for w in r["text"].split())
    print(f"    {changed} of {len(rows)} lines rewritten, {ignored} answers ignored (looked like another line), "
          f"{english} English words in the transcript now")
    return changed


if __name__ == "__main__":
    fix_english_words(session_from_argv())
