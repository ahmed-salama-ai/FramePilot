from pathlib import Path

from pydantic import BaseModel

from ..audio.speakers import transcript_text
from ..common.io import read_json, session_from_argv, write_json
from ..common.schemas import Publish
from .interest import CFG

PROMPT = """Write a blog article about this talk-show episode, once in Arabic (article_ar, Modern Standard Arabic that
Egyptians read easily; quotes stay as they were said) and once in English (article_en). Markdown:
- "# " a catchy title, then a short intro paragraph (who talks about what),
- 3-5 sections with "## " headings that follow the topics of the conversation, in order,
- 1-3 short quotes in "> " lines with who said them (use the names below, else their role),
- a short closing paragraph.
400-700 words each. Only facts and opinions from the transcript; never invent numbers or names.
Episode: {title} (spoken language: {language}).
Who is who: {people}

Transcript ([mm:ss] speaker: text):
{transcript}
"""


class Answer(BaseModel):
    article_ar: str
    article_en: str


def people_line(s):
    items = read_json(s / "speakers.json") if (s / "speakers.json").exists() else []
    return "; ".join(f"{x['speaker']} = {x.get('name') or 'no name'} ({x.get('role') or 'speaker'})" for x in items) \
        or "unknown"


def default_ask(prompt):
    """Gemini (highlights.title_model); the local model only if Gemini can't be used."""
    if CFG.get("title_model"):
        try:
            from ..audio.gemini import ask_json
            return ask_json(CFG["title_model"], prompt, Answer, timeout=180)
        except Exception as e:
            print(f"  Gemini article failed ({type(e).__name__}: {str(e)[:120]}) -> the local model")
    from ..brain.llm_client import chat_json
    from ..common.paths import CONFIGS
    import yaml
    model = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["ollama"]["text_model"]
    return chat_json(model, prompt, Answer, think=False)


def clean(md):
    """The model's Markdown, tidied: no ``` fences, no empty lines at the ends."""
    md = md.strip()
    if md.startswith("```"):
        md = md.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return md


def make_article(s, ask=None):
    """publish.json with article_ar / article_en (the rest of the publish kit is kept). Returns the two texts."""
    s = Path(s)
    meta = read_json(s / "session.json")
    up = read_json(s / "upload.json") if (s / "upload.json").exists() else {}
    prompt = PROMPT.format(title=up.get("name") or meta.get("id", ""), language=meta["language"],
                           people=people_line(s), transcript=transcript_text(read_json(s / "transcript.json")))
    a = (ask or default_ask)(prompt)
    ar, en = clean(a.article_ar), clean(a.article_en)
    if not ar and not en:
        raise ValueError("the model wrote no article")
    p = read_json(s / "publish.json") if (s / "publish.json").exists() else {}
    p.update(article_ar=ar, article_en=en)
    Publish.model_validate(p)                                          # follows the contract
    write_json(s / "publish.json", p)
    return {"article_ar": ar, "article_en": en}


if __name__ == "__main__":
    a = make_article(session_from_argv())
    print(f"article: {len(a['article_ar'].split())} Arabic words, {len(a['article_en'].split())} English words")
