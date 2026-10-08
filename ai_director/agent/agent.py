# ai_director/agent/agent.py — ⑨ the Editor Agent: the user asks in the chat, the LLM calls tools until the job is done
#   python -m ai_director.agent.run data/sessions/s01 "اعمل كليب دقيقة عن المرتبات"
# Used by the web app (Ahmed Sameh):  from ai_director.agent.agent import chat  ->  {"reply", "steps", "clips"}
# Owner: Eslam ElKharbotly (fixed by Ahmed Salama: the LLM decides (no keyword shortcuts), every error becomes a
# message (never a crash), honest replies in the user's language, model from configs, think=False)
import json
import re
from pathlib import Path

from pydantic import ValidationError

from .prompts import SYSTEM, speaker_lines
from .search import CFG, OLLAMA
from .tools import ARGS, FUNCS, TOOLS, Job

TEXT = {   # the only fixed answers (everything else is written by the LLM)
    "ar": {"no_llm": "عذراً، مش قادر أوصل لنموذج الذكاء الاصطناعي دلوقتي ({e}). جرّب تاني بعد شوية.",
           "not_ready": "عذراً، الجلسة دي مش جاهزة لسه ({e}).",
           "gave_up": "عذراً، ما قدرتش أخلّص الطلب ده. جرّب تكتبه بطريقة أبسط.",
           "made": "خلصت! الكليبات: {clips}"},
    "en": {"no_llm": "Sorry, I can't reach the AI model right now ({e}). Please try again in a minute.",
           "not_ready": "Sorry, this session is not ready yet ({e}).",
           "gave_up": "Sorry, I couldn't finish that. Please ask in a simpler way.",
           "made": "Done! Clips: {clips}"}}


def ask_ollama(messages, tools):
    """One LLM turn. think=False: qwen3 answers at once, without a long hidden "thinking" part (faster, and the
    thinking can't eat the answer)."""
    import ollama                     # only here: tests use a fake LLM and don't need the package
    model = OLLAMA["text_model"]
    extra = {"think": False} if model.startswith("qwen3") else {}
    return ollama.chat(model=model, messages=messages, tools=tools or None, keep_alive=CFG["keep_alive"],
                       options={"temperature": CFG["temperature"], "num_ctx": CFG["num_ctx"]}, **extra).message


def language(message):
    return "ar" if re.search("[\u0600-\u06FF]", message) else "en"


def summarize(result):
    """One short line per step for the chat window."""
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
    """One tool call -> its result. Every problem becomes {"error": ...}: the LLM reads it and fixes its call."""
    if isinstance(raw, str):                                          # some models send the arguments as JSON text
        try:
            raw = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {"error": "the arguments are not valid JSON"}
    if name not in FUNCS:
        return {"error": f"there is no tool called {name!r}. Tools: {', '.join(FUNCS)}"}
    try:
        return FUNCS[name](job, ARGS[name](**(raw or {})))
    except ValidationError as e:                                      # Pydantic: wrong or missing arguments
        return {"error": "wrong arguments: " + "; ".join(
            f"{'.'.join(map(str, x['loc'])) or 'arguments'}: {x['msg']}" for x in e.errors())[:300]}
    except (ValueError, KeyError) as e:                               # our checks (times, speakers, length, ...)
        return {"error": str(e)[:300]}
    except Exception as e:                                            # FFmpeg failed, Ollama (search) is off, ...
        return {"error": f"{type(e).__name__}: {str(e)[:300]}"}


def clip_list(clips):
    return ", ".join(f"{c['id']} ({c['start']:.0f}-{c['end']:.0f} s, {c['format']})" for c in clips)


def chat(session_dir, message, history=(), ask=ask_ollama, render=True, embed=None):
    """The agent loop. history = the earlier chat [{"role": "user"/"assistant", "content": ...}] (last 10 used).
    ask = the LLM (tests: a fake), render=False: decide but make no video (fast tests), embed = the search model."""
    lang, steps = language(message), []
    try:
        job = Job(session_dir, message, render=render, embed=embed)
    except Exception as e:                                            # e.g. no session.json yet
        return {"reply": TEXT[lang]["not_ready"].format(e=type(e).__name__), "steps": [], "clips": []}
    meta = job.meta
    messages = [{"role": "system", "content": SYSTEM.format(duration=meta["duration"], language=meta["language"],
                                                            speakers=speaker_lines(job.speakers),
                                                            max_clips=CFG["max_clips"])}]
    messages += [{"role": m["role"], "content": m["content"]} for m in list(history)[-10:]]   # short memory
    messages.append({"role": "user", "content": message})
    while True:
        last = len(steps) >= CFG["max_steps"]                         # 6 tool calls used: it must answer now
        try:
            msg = ask(messages, [] if last else TOOLS)
        except Exception as e:                                        # Ollama off, model missing, out of memory
            reply = TEXT[lang]["no_llm"].format(e=type(e).__name__)
            if job.clips:
                reply += " " + TEXT[lang]["made"].format(clips=clip_list(job.clips))
            return {"reply": reply, "steps": steps, "clips": job.clips}
        messages.append(msg)
        text = re.sub(r"<think>.*?</think>", "", msg.content or "", flags=re.S).strip()
        if not msg.tool_calls or last:                                # no tool call = the final answer
            if not text:
                text = (TEXT[lang]["made"].format(clips=clip_list(job.clips)) if job.clips
                        else TEXT[lang]["gave_up"])
            return {"reply": text, "steps": steps, "clips": job.clips}
        for call in msg.tool_calls:
            name, raw = call.function.name, call.function.arguments
            if len(steps) >= CFG["max_steps"]:
                result = {"error": f"no more tool calls (max {CFG['max_steps']}): answer the user now"}
            else:
                result = run_tool(job, name, raw)
                steps.append({"tool": name, "args": raw, "summary": summarize(result)})
            messages.append({"role": "tool", "content": json.dumps(result, ensure_ascii=False)[:4000],
                             "tool_name": name})                      # older ollama versions: "name"
