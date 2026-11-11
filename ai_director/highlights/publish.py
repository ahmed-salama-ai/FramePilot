import json
from pathlib import Path

from pydantic import BaseModel

from ..audio.speakers import transcript_text
from ..common.io import read_json, session_from_argv, write_json
from ..common.schemas import Publish
from .interest import CFG

MIN_GAP = 30.0              # chapters at least 30 s apart

PROMPT = """You prepare a talk-show episode for publishing. The transcript has [mm:ss] times. Return JSON with:
- chapters: 4-8 chapters that follow the topics of the conversation, in time order. start = the [mm:ss] time (in
  seconds) of the line where the topic starts; the first chapter starts at 0. title_ar = a short title (2-6 words) in
  Egyptian Arabic, title_en = the same in English.
- summary_ar / summary_en: 2-3 sentences about the episode (who talks about what), Arabic and English.
- key_points_ar / key_points_en: 3-5 short points that were said.
- posts: one social-media post per highlight below (highlight = its id): text_ar and text_en, 1-2 lively sentences
  that make people watch the clip, and 3-5 hashtags without spaces (no # sign needed).
Only facts from the transcript. Episode: {title} (language: {language}).

Highlights:
{highlights}

Transcript:
{transcript}
"""


class _Chapter(BaseModel):
    start: float
    title_ar: str
    title_en: str


class _Post(BaseModel):
    highlight: str
    text_ar: str
    text_en: str
    hashtags: list[str]


class Answer(BaseModel):            # what the model must return (the descriptions are written by the code)
    chapters: list[_Chapter]
    summary_ar: str
    summary_en: str
    key_points_ar: list[str]
    key_points_en: list[str]
    posts: list[_Post]


def mmss(t):
    t = int(t)
    return f"{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def clean_chapters(chapters, rows, duration):
    """The model's chapters -> YouTube rules: each start moved to the nearest transcript line, time order, the first at
    0:00, at least 30 s apart, inside the video. Fewer than 3 left -> no chapters (YouTube needs 3)."""
    starts = sorted({0.0, *[float(r["start"]) for r in rows]})
    out = []
    for c in sorted(chapters, key=lambda c: c.start):
        t = 0.0 if not out else min(starts, key=lambda x: abs(x - c.start))
        title_ar, title_en = c.title_ar.strip(), c.title_en.strip()
        if not (title_ar or title_en) or t >= duration - MIN_GAP or (out and t - out[-1]["start"] < MIN_GAP):
            continue
        out.append({"start": round(t, 2), "title_ar": title_ar or title_en, "title_en": title_en or title_ar})
    return out if len(out) >= 3 else []


def hashtag(x):
    return "#" + "".join(x.replace("#", "").split())


def description(summary, chapters, key_points, tags, lang):
    """The text to paste under a YouTube video: summary, chapters (0:00 Title), key points, hashtags."""
    parts = [summary.strip()]
    if chapters:
        parts.append(("الفصول:" if lang == "ar" else "Chapters:") + "\n" +
                     "\n".join(f"{mmss(c['start'])} {c[f'title_{lang}']}" for c in chapters))
    if key_points:
        parts.append(("أهم النقاط:" if lang == "ar" else "Key points:") + "\n" + "\n".join(f"- {k}" for k in key_points))
    if tags:
        parts.append(" ".join(tags))
    return "\n\n".join(p for p in parts if p)


def tags_of(posts):
    """The description's hashtags: the posts' hashtags, each once, at most 6."""
    return list(dict.fromkeys(t for p in posts for t in p["hashtags"]))[:6]


def descriptions_for(p, version):
    """publish.json's YouTube descriptions with the chapter times of one version's finished video"""
    from ..director.versions import video_time
    chapters = [{**c, "start": 0.0 if k == 0 else video_time(version, c["start"])}
                for k, c in enumerate(p.get("chapters") or [])]
    tags = tags_of(p.get("posts") or [])
    return {lang: description(p.get(f"summary_{lang}", ""), chapters, p.get(f"key_points_{lang}") or [],
                              tags if lang == "ar" else [t for t in tags if t.isascii()], lang) for lang in ("ar", "en")}


def default_ask(prompt):
    """Gemini (highlights.title_model); the local model only if Gemini can't be used (like the highlight titles)."""
    if CFG.get("title_model"):
        try:
            from ..audio.gemini import ask_json
            return ask_json(CFG["title_model"], prompt, Answer)
        except Exception as e:
            print(f"  Gemini publish kit failed ({type(e).__name__}: {str(e)[:120]}) -> the local model")
    from ..brain.llm_client import chat_json
    from ..common.paths import CONFIGS
    import yaml
    model = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["ollama"]["text_model"]
    return chat_json(model, prompt, Answer, think=False)


def make_publish(s, highlights=None, ask=None):
    """publish.json for session s (highlights = the highlights.json items, read from the file if None)."""
    s = Path(s)
    meta = read_json(s / "session.json")
    up = read_json(s / "upload.json") if (s / "upload.json").exists() else {}
    rows = read_json(s / "transcript.json")
    if highlights is None:
        highlights = read_json(s / "highlights.json") if (s / "highlights.json").exists() else []
    brief = [{"id": h["id"], "start": h["start"], "end": h["end"], "title_ar": h.get("title_ar", ""),
              "title_en": h.get("title_en", "")} for h in highlights]
    prompt = PROMPT.format(title=up.get("name") or meta.get("id", ""), language=meta["language"],
                           highlights=json.dumps(brief, ensure_ascii=False), transcript=transcript_text(rows))
    a = (ask or default_ask)(prompt)
    chapters = clean_chapters(a.chapters, rows, meta["duration"])
    ids = {h["id"] for h in highlights}
    posts = [{"highlight": p.highlight, "text_ar": p.text_ar.strip(), "text_en": p.text_en.strip(),
              "hashtags": [hashtag(x) for x in p.hashtags if x.strip()][:5]}
             for p in a.posts if p.highlight in ids]
    tags = tags_of(posts)
    kp_ar, kp_en = [k.strip() for k in a.key_points_ar if k.strip()][:5], [k.strip() for k in a.key_points_en if k.strip()][:5]
    out = {"chapters": chapters, "summary_ar": a.summary_ar.strip(), "summary_en": a.summary_en.strip(),
           "key_points_ar": kp_ar, "key_points_en": kp_en, "posts": posts,
           "description_ar": description(a.summary_ar, chapters, kp_ar, tags, "ar"),
           "description_en": description(a.summary_en, chapters, kp_en, [t for t in tags if t.isascii()], "en")}
    Publish.model_validate(out)                                        # follows the contract
    write_json(s / "publish.json", out)
    return out


if __name__ == "__main__":
    p = make_publish(session_from_argv())
    print(f"publish.json: {len(p['chapters'])} chapters, {len(p['posts'])} posts")
