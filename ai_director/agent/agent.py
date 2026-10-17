import json
import re
from pathlib import Path

from pydantic import ValidationError

from .asks import CJK, NAMES, language, name_people, people_labels, read_focus, reply_language
from .prompts import SYSTEM, count_text, focus_line, previous_lines, speaker_lines
from .search import CFG, OLLAMA, ollama_client
from .tools import ARGS, FUNCS, TOOLS, Job

TEXT = {
    "ar": {"no_llm": "عذراً، مش قادر أوصل لنموذج الذكاء الاصطناعي دلوقتي ({e}). جرّب تاني بعد شوية.",
           "slow": "عذراً، نموذج الذكاء الاصطناعي اتأخر أكتر من {s} ثانية. جرّب تاني بعد شوية.",
           "not_ready": "عذراً، الجلسة دي مش جاهزة لسه ({e}).",
           "gave_up": "عذراً، ما قدرتش أخلّص الطلب ده. جرّب تكتبه بطريقة أبسط.",
           "made": "خلصت!"},
    "en": {"no_llm": "Sorry, I can't reach the AI model right now ({e}). Please try again in a minute.",
           "slow": "Sorry, the AI model took longer than {s} seconds. Please try again in a minute.",
           "not_ready": "Sorry, this session is not ready yet ({e}).",
           "gave_up": "Sorry, I couldn't finish that. Please ask in a simpler way.",
           "made": "Done!"}}
CLIP_WORDS = {
    "ar": {"16:9": "أفقي 16:9", "9:16": "عمودي 9:16", "sec": "ثانية", "captions": "الترجمة", "focus": "مع التركيز على",
           "ar": "عربي", "en": "إنجليزي", "ar+en": "عربي + إنجليزي", "none": "بدون", "sep": "، "},
    "en": {"16:9": "horizontal 16:9", "9:16": "vertical 9:16", "sec": "s", "captions": "captions", "focus": "showing",
           "ar": "Arabic", "en": "English", "ar+en": "Arabic + English", "none": "none", "sep": ", "}}
LISTY = re.compile(r"^\s*(?:[-•*]|\d+[.)]\s|#)|\S*\.mp4|\]\(")


def ask_ollama(messages, tools):
    model = OLLAMA["text_model"]
    extra = {"think": False} if model.startswith("qwen3") else {}
    return ollama_client().chat(model=model, messages=messages, tools=tools or None, keep_alive=CFG["keep_alive"],
                                options={"temperature": CFG["temperature"], "num_ctx": CFG["num_ctx"]},
                                **extra).message


def answer_text(msg):
    return re.sub(r"<think>.*?</think>", "", msg.content or "", flags=re.S).strip()


def rewrite(ask, messages, lang):
    """The answer came in the wrong language"""
    messages.append({"role": "user", "content": f"Write that answer again in {NAMES[lang]} only, with the same facts."})
    try:
        msg = ask(messages, [])
    except Exception:
        return ""
    messages.append(msg)
    text = answer_text(msg)
    return text if text and reply_language(text) == lang and not CJK.search(text) else ""


def summarize(result):
    """One short line per step for the chat"""
    if "error" in result:
        return "error: " + result["error"][:80]
    if "moments" in result:
        return f"found {len(result['moments'])} moments"
    if "speakers" in result:
        return f"{len(result['speakers'])} speakers"
    if "scenes" in result:
        return f"{len(result['scenes'])} scene descriptions"
    if "clips" in result:
        return f"{len(result['clips'])} clips and highlights"
    if "file" in result:
        return f"rendered {result['file']}"
    return "ok"


def run_tool(job, name, raw):
    """tool call"""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {"error": "the arguments are not valid JSON"}
    if name not in FUNCS:
        return {"error": f"there is no tool called {name!r}. Tools: {', '.join(FUNCS)}"}
    try:
        return FUNCS[name](job, ARGS[name](**(raw or {})))
    except ValidationError as e:                                      #Pydantic
        return {"error": "wrong arguments: " + "; ".join(
            f"{'.'.join(map(str, x['loc'])) or 'arguments'}: {x['msg']}" for x in e.errors())[:300]}
    except (ValueError, KeyError) as e:                               #our checks (times, speakers, length)
        return {"error": str(e)[:300]}
    except Exception as e:                                            #FFmpeg failed. Ollama (search) is off
        return {"error": f"{type(e).__name__}: {str(e)[:300]}"}


def clip_lines(clips, lang, labels):
    """clips made"""
    w, lines = CLIP_WORDS[lang], []
    for c in clips:
        parts = [f"{c['end'] - c['start']:.0f} {w['sec']}", w[c["format"]], f"{w['captions']}: {w[c['captions']]}"]
        if c.get("focus_speaker"):
            parts.append(f"{w['focus']} {labels.get(c['focus_speaker'], c['focus_speaker'])}")
        lines.append(f"- {c['title']} ({c['id']}): " + w["sep"].join(parts))
    return "\n".join(lines)


def tidy(text, made, labels):
    """LLM answer"""
    text = name_people(text, labels).replace("**", "")
    if made:
        keep = []
        for line in text.splitlines():
            if LISTY.search(line):
                break
            keep.append(line.strip())
        text = re.split(r"(?<=[.!?؟])\s+", " ".join(x for x in keep if x))[0]
    return text.strip()


def final_reply(text, job, lang, labels):
    """LLM final answer"""
    text = tidy(text, job.clips, labels)
    if job.clips:
        return (text or TEXT[lang]["made"]) + "\n" + clip_lines(job.clips, lang, labels)
    return text or TEXT[lang]["gave_up"]


def chat(session_dir, message, history=(), ask=ask_ollama, render=True, embed=None, read=None):
    """llm chat"""
    lang, steps = language(message), []
    try:
        job = Job(session_dir, message, render=render, embed=embed)
    except Exception as e:
        return {"reply": TEXT[lang]["not_ready"].format(e=type(e).__name__), "steps": [], "clips": []}
    if read is None and ask is ask_ollama:
        read = lambda m: read_focus(m, OLLAMA["text_model"], CFG["keep_alive"], CFG["num_ctx"])
    try:
        job.focus = read(message) if read else None 
    except Exception:                                                 #Ollama off
        job.focus = None
    meta, labels = job.meta, people_labels(job.speakers, lang)
    messages = [{"role": "system", "content": SYSTEM.format(duration=meta["duration"], language=meta["language"],
                                                            speakers=speaker_lines(job.speakers, labels),
                                                            previous=previous_lines(job.previous),
                                                            count=count_text(job.count, CFG["max_clips"]),
                                                            user_language=NAMES[lang], focus=focus_line(job.focus))}]
    messages += [{"role": m["role"], "content": m["content"]} for m in list(history)[-10:]]   #short memory
    messages.append({"role": "user", "content": message})
    while True:
        last = len(steps) >= CFG["max_steps"]                         #max tool calls answer now
        try:
            msg = ask(messages, [] if last else TOOLS)
        except Exception as e:                                        #Ollama off, model missing, out of memory
            slow = "timeout" in type(e).__name__.lower()              #agent.timeout passed
            reply = (TEXT[lang]["slow"].format(s=CFG["timeout"]) if slow
                     else TEXT[lang]["no_llm"].format(e=type(e).__name__))
            if job.clips:
                reply += "\n" + clip_lines(job.clips, lang, labels)
            return {"reply": reply, "steps": steps, "clips": job.clips}
        messages.append(msg)
        text = answer_text(msg)
        if not msg.tool_calls or last:                                #no tool call = the final answer
            if text and (reply_language(text) != lang or CJK.search(text)):
                text = rewrite(ask, messages, lang) or text
            text = CJK.sub("", text).strip()
            return {"reply": final_reply(text, job, lang, labels), "steps": steps, "clips": job.clips}
        for call in msg.tool_calls:
            name, raw = call.function.name, call.function.arguments
            if len(steps) >= CFG["max_steps"]:
                result = {"error": f"no more tool calls (max {CFG['max_steps']}): answer the user now"}
            else:
                result = run_tool(job, name, raw)
                steps.append({"tool": name, "args": raw, "summary": summarize(result)})
            messages.append({"role": "tool", "content": json.dumps(result, ensure_ascii=False)[:4000],
                             "tool_name": name})
