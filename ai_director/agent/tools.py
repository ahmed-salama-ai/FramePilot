# ai_director/agent/tools.py — the Editor Agent's 6 tools. Every tool = an argument model (Pydantic checks what the LLM
# sends) + a function + a description (the LLM chooses tools only from the descriptions).
# Owner: Eslam ElKharbotly (fixed by Ahmed Salama: speakers and roles from speakers.json, clip times only from tool
# results, clips moved to whole sentences, 9:16 cropped on the speaker's face, errors instead of silent changes;
# 2026-10-08: the clip length and captions the user asked for are read by the code (asks.py), titles are checked)
import re
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field, field_validator, model_validator

from ..common.io import read_json, read_jsonl, write_json
from ..director.render import add_captions, render_clip, render_program      # Ahmed Salama
from ..director.run import decide, make_cuts
from ..highlights.clips import people_x, strip_shots, vertical_source      # 9:16: speaker + face position
from .asks import (CAPTION, CJK, LENGTH_WORD, NAMES, asked_captions, asked_count, asked_format, asked_length,
                   default_captions, language, length_change, title_problem)
from .search import CFG, embed as bge_m3, search

MODES = Literal["conversation", "reaction", "wide_energy", "demo"]
CONVERSATION = re.compile(r"conversation|talk|حوار|محادث|كلام", re.I)    # the user asked for the plain talk style
FORMATS = {"vertical": "9:16", "portrait": "9:16", "9x16": "9:16", "9/16": "9:16",
           "horizontal": "16:9", "landscape": "16:9", "16x9": "16:9", "16/9": "16:9"}


def typed_times(message):
    """Times the user typed, like 2:30 or 1:02:30 -> a range a clip may use (first to last time, or 3 min after one)."""
    ts = [sum(int(p) * 60 ** k for k, p in enumerate(reversed(m.split(":"))))     # not "1:20 minutes" (a length)
          for m in re.findall(r"(?<![\d:])\d{1,2}(?::\d{2}){1,2}(?![\d:])(?!\s*-?\s*(?:minute|min\b|mins\b|دقيق|دقايق|دقائق))",
                              message.lower())]
    if not ts:
        return []
    return [(min(ts), max(ts) if max(ts) > min(ts) else min(ts) + 180)]


def speaker_list(s, meta):
    """Who is in the video: [{id, role, name, camera, talk_seconds, description}], most talking first.
    role + description: speakers.json (audio stage). Names typed at upload win. camera: speaker_map.json (perception)."""
    info = {x["speaker"]: x for x in read_json(s / "speakers.json")} if (s / "speakers.json").exists() else {}
    cams = read_json(s / "speaker_map.json") if (s / "speaker_map.json").exists() else {}
    names, talk = meta.get("speaker_names", {}), {}
    for d in read_json(s / "diarization.json") if (s / "diarization.json").exists() else []:
        talk[d["speaker"]] = talk.get(d["speaker"], 0) + d["end"] - d["start"]
    ids = sorted(set(info) | set(talk), key=lambda k: (-talk.get(k, 0), k))
    return [{"id": k, "role": info.get(k, {}).get("role", ""),
             "name": names.get(k) or info.get(k, {}).get("name", ""),
             "camera": cams.get(k), "talk_seconds": round(talk.get(k, 0)),
             "description": info.get(k, {}).get("description", "")} for k in ids]


def previous_clips(s, lang):
    """The clips (the last 5) and highlights already made for this video, newest last, so a follow-up ("make it
    vertical", "make it longer", "خليه أقصر") can use them: [{id, start, end, format, title}]."""
    out = []
    if (s / "highlights.json").exists():
        out += [{"id": h["id"], "start": h["start"], "end": h["end"], "format": "16:9 and 9:16",
                 "title": h.get(f"title_{lang}") or h.get("title_en", "")} for h in read_json(s / "highlights.json")]
    if (s / "clips.json").exists():
        out += [{k: c.get(k) for k in ("id", "start", "end", "format", "title")} for c in read_json(s / "clips.json")[-5:]]
    return out


class Job:
    """What the tools know about ONE chat request: the session, the user's message (its language and the clip length
    it asks for), the time ranges that tools returned (a clip may only use those: no invented times) and the clips
    made so far.
    render=False: decide everything but make no video (fast agent tests). embed: the search model (tests: a fake).
    focus: who to show and how much, read by an LLM ({"person", "level", "share"}; None = not read)."""

    def __init__(self, s, message="", render=True, embed=None, focus=None):
        self.s, self.message, self.render, self.embed = Path(s), message, render, embed or bge_m3
        self.focus = focus
        self.meta = read_json(self.s / "session.json")
        self.speakers = speaker_list(self.s, self.meta)
        self.seen = typed_times(message)
        self.lang, self.wanted = language(message), asked_length(message)
        self.count, self.change = asked_count(message), length_change(message)    # 2026-10-09
        self.format = asked_format(message)
        if self.change and self.change[1] is not None:
            self.wanted = None                        # "30 seconds longer": the number is how much to add, not the length
        self.previous = previous_clips(self.s, self.lang)          # a follow-up may reuse an earlier clip (reuses)
        self.clips, self.title_tries = [], 0

    def saw(self, ranges):
        self.seen += [(float(a), float(b)) for a, b in ranges]

    def allowed(self, a, b):
        """True if the clip overlaps a range that a tool returned (1 s tolerance)."""
        return any(a < y + 1 and x - 1 < b for x, y in self.seen)

    def earlier(self, a, b):
        """The earlier clip a..b is made from ("make it vertical / longer"): more than half of both overlap; else None."""
        over = lambda c: min(b, c["end"]) - max(a, c["start"])                 # noqa: E731
        best = max(self.previous, key=over, default=None)
        if best and over(best) > 0.5 * max(best["end"] - best["start"], b - a):
            return best
        return None

    def base_length(self, a, b):
        """The length of the earlier clip a..b is made from, else a..b itself."""
        c = self.earlier(a, b)
        return c["end"] - c["start"] if c else b - a

    def person(self, who):
        """A role or a name ("guest", "Islam") -> the SPEAKER id, if exactly one person fits (else None)."""
        fits = [x["id"] for x in self.speakers if who and who.strip().lower() in (x["role"].lower(), x["name"].lower())]
        return fits[0] if len(fits) == 1 else None

    def speaker(self, sid):
        known = {x["id"]: x for x in self.speakers}
        if sid not in known:
            raise ValueError(f"unknown speaker {sid!r}. Use one of: " +
                             ", ".join(f"{k} ({v['role'] or 'speaker'}{' ' + v['name'] if v['name'] else ''})"
                                       for k, v in known.items()))
        return known[sid]


# ---------- the argument models (what the LLM must send) ----------

def no_null(v):
    """The LLM sometimes writes "" or "null" instead of null."""
    return None if isinstance(v, str) and v.strip().lower() in ("", "null", "none") else v


class SearchArgs(BaseModel):
    query: str = Field(description="the topic in a few words, Arabic or English (e.g. المرتبات / salaries)")
    top_k: int = Field(5, ge=1, le=10, description="how many moments (5-10; at least 5 are returned)")


class ScenesArgs(BaseModel):
    start: float = Field(ge=0, description="seconds")
    end: float = Field(description="seconds")

    @model_validator(mode="after")
    def check(self):
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class NoArgs(BaseModel):
    pass


class ClipArgs(BaseModel):
    start: float = Field(ge=0, description="seconds: the start of a moment that a tool returned")
    end: float = Field(description="seconds: the end of that moment")
    seconds: float | None = Field(None, gt=0, description='the clip length the user asked for, in seconds ("1 minute" '
                                                          '= 60, "1-2 minutes" = 90), or null')
    format: Literal["16:9", "9:16"] = Field("16:9", description='"9:16" = vertical (TikTok, Reels, Shorts), '
                                                               'else "16:9"')
    focus_speaker: str | None = Field(None, description="SPEAKER_xx of the person to show, or null")
    captions: Literal["ar", "en", "ar+en", "none"] | None = Field(
        None, description='caption languages, only if the user named them ("English subtitles" -> "en", '
                          '"no captions" -> "none"), else null')
    title: str = Field("", description="3-7 catchy words in the user's language that say what the clip is about "
                                       "(not copied from the transcript)")

    @field_validator("format", mode="before")
    @classmethod
    def format_word(cls, v):                       # "vertical" -> "9:16" (a word, not a ratio)
        return FORMATS.get(str(v).strip().lower(), v)

    @field_validator("focus_speaker", "seconds", mode="before")
    @classmethod
    def nulls(cls, v):
        return None if v in (0, "0") else no_null(v)

    @field_validator("captions", mode="before")
    @classmethod
    def captions_null(cls, v):                     # here "none" means no captions (not null)
        return None if isinstance(v, str) and v.strip().lower() in ("", "null") else v

    @model_validator(mode="after")
    def check_length(self):
        lo, hi = CFG["clip_seconds"]
        if not lo <= self.end - self.start <= hi:
            raise ValueError(f"a clip must be {lo}-{hi} s long, but {self.start}-{self.end} is "
                             f"{self.end - self.start:.1f} s")
        return self


class RestyleArgs(BaseModel):
    focus_speaker: str | None = Field(None, description="SPEAKER_xx to show more in the whole video, or null")
    mode: MODES | None = Field(None, description="one editing style for the whole video: conversation, reaction "
                                                 "(more reaction shots), wide_energy (more wide shots), demo; or null")

    @field_validator("focus_speaker", "mode", mode="before")
    @classmethod
    def nulls(cls, v):
        return no_null(v)


# ---------- the tools ----------

def search_transcript(job, a: SearchArgs):
    # at least 5 moments: told "1 clip", qwen asked for top_k=1 and could not pick the best moment (2026-10-09 eval)
    moments = search(job.s, a.query, max(a.top_k, 5), embed=job.embed)
    job.saw((m["start"], m["end"]) for m in moments)
    return {"moments": moments}


def get_scenes(job, a: ScenesArgs):
    """What the AI Brain saw (scene.jsonl, every 5 s). More than 20 lines -> the 20 most interesting
    (highlight, laughter / demo / standing, energy), in time order."""
    if not (job.s / "scene.jsonl").exists():
        return {"scenes": [], "note": "no AI Brain output (scene.jsonl) for this session"}
    rows = [r for r in read_jsonl(job.s / "scene.jsonl") if a.start <= r["t"] <= a.end]
    rows = sorted(sorted(rows, key=lambda r: (not r.get("highlight"), r.get("event") == "talking",
                                              -r.get("energy", 0)))[:20], key=lambda r: r["t"])
    job.saw((r["t"], r["t"] + 5) for r in rows)
    return {"scenes": [{k: r[k] for k in ("t", "scene", "event", "energy", "highlight") if k in r} for r in rows]}


def get_speakers(job, a: NoArgs):
    return {"speakers": job.speakers}


def to_sentences(segs, a, b):
    """Clip edges -> sentence edges: a start inside a row moves to that row's start, an end inside a row to that row's
    end. (Times in a pause between rows stay.)"""
    a = next((r["start"] for r in segs if r["start"] <= a < r["end"]), a)
    b = next((r["end"] for r in segs if r["start"] < b <= r["end"]), b)
    return round(a, 2), round(b, 2)


def face_x(feats, cam, a, b):
    """Median face position (0..1) of one camera in a time range, None if no face was seen."""
    x = feats[(feats.cam == cam) & feats.t.between(a, b) & (feats.face_area > 0)].face_x
    return round(float(x.median()), 3) if len(x) else None


def clip_shots(cuts, a, b):
    """The shots of a cut list inside a..b (cut at the clip edges). A piece shorter than 1 s at an edge joins its
    neighbour (no flash at the start or the end)."""
    shots = [{**c, "start": max(c["start"], a), "end": min(c["end"], b)} for c in cuts   # keeps a split screen
             if c["end"] > a and c["start"] < b]
    if len(shots) > 1 and shots[0]["end"] - shots[0]["start"] < 1.0:
        shots[1]["start"] = shots.pop(0)["start"]
    if len(shots) > 1 and shots[-1]["end"] - shots[-1]["start"] < 1.0:
        shots[-2]["end"] = shots.pop()["end"]
    return [{**c, "start": round(c["start"], 3), "end": round(c["end"], 3)} for c in shots]


def on_screen(shots):
    """{camera: % of the clip on screen}"""
    time = {}
    for c in shots:
        time[c["cam"]] = time.get(c["cam"], 0) + c["end"] - c["start"]
    return {cam: round(100 * t / sum(time.values())) for cam, t in sorted(time.items())}


def boosted_shots(job, cam, a, b, target):
    """The AI edit of a..b with camera `cam` boosted just enough to be on screen `target` % of the clip: the smallest
    boost in configs agent.boosts that reaches it (none if the edit already does), else the one that gets closest.
    The director (scorer + switcher, 0.2 s for s01) still makes every cut. Returns (shots, {cam: %}, boost)."""
    best = None
    for factor in [1.0] + CFG["boosts"]:
        cuts, _ = decide(job.s, boost={"cam": cam, "factor": factor} if factor > 1 else None)
        shots = clip_shots(cuts, a, b)
        share = on_screen(shots)
        if best is None or share.get(cam, 0) > best[1].get(cam, 0):
            best = (shots, share, factor)
        if share.get(cam, 0) >= target:
            break
    return best


def clip_source(job, a, b, fmt, focus, target=100):
    """Where the clip is cut from: a person's close-up camera (target 100 %), the AI edit with that camera boosted
    (target < 100 %: "mostly" / "more"), or the AI edit ("program"); for 9:16 also where to crop (face position).
    Returns (source, crop_x, what the viewer sees, notes)."""
    f = job.s / "features.parquet"
    feats = (pd.read_parquet(f, columns=["t", "cam", "face_area", "face_x"]) if f.exists()
             else pd.DataFrame(columns=["t", "cam", "face_area", "face_x"]))
    if focus:
        cam = job.speaker(focus)["camera"]
        if cam is None:
            return "program", None, f"the AI edit ({focus} has no close-up camera)", []
        mine = people_x(job.s, feats).get(cam, {}).get(focus) if fmt == "9:16" else None   # THAT person (2 on a camera)
        if target < 100 and f.exists():
            shots, share, boost = boosted_shots(job, cam, a, b, target)
            crops = None
            if fmt == "9:16":                                         # each shot on its face; the asked person stays
                shots = strip_shots(job.s, shots, feats, keep={cam: mine} if mine is not None else None)
            shows = (f"the AI edit with {focus} (camera {cam}) on screen {share.get(cam, 0)}% of the clip; " +
                     ", ".join(f"camera {c} {p}%" for c, p in share.items()))
            notes = ([f"{focus} is on screen {share.get(cam, 0)}%, the most the editing rules give here "
                      f"(asked {target}%)"] if share.get(cam, 0) < target else [])
            return shots, crops, shows, notes
        x = (mine if mine is not None else face_x(feats, cam, a, b)) if fmt == "9:16" else None
        return cam, x, f"camera {cam} ({focus})", []
    if fmt == "9:16" and (job.s / "cuts.json").exists():
        source, x = vertical_source(job.s, a, b, read_json(job.s / "cuts.json"), feats)
        cams = {c["cam"] for c in source} if isinstance(source, list) else set()
        about = ("the AI edit" if source == "program" else f"camera {cams.pop()} (the strip moves to whoever talks)"
                 if len(cams) == 1 else "the AI edit's shots, each from its own camera" if cams
                 else f"camera {source} (the main speaker)")
        return source, x, about, []
    return "program", None, "the AI edit", []


def focus_target(job, focus):
    """(who to show, % of the clip on their camera) from the LLM reader (job.focus) and the agent's focus_speaker.
    Nobody asked for -> nobody (the agent sometimes adds a person by itself). No reader -> the agent's person, 100 %."""
    if job.focus is None:
        return focus, 100
    if not job.focus["level"]:
        return None, 100
    focus = focus or job.person(job.focus["person"])                  # the agent forgot the id: the role/name
    return focus, min(100, job.focus["share"] or CFG["focus_share"][job.focus["level"]])


def clip_length(job, a):
    """(the clip length the user asked for, a note), or (None, "") = the moment's own length. The CODE reads it from
    the message ("1-2 minutes" -> 60-120 s: the LLM's seconds if inside, else the middle). The LLM's seconds alone
    only if the message has a length word the code can't read (no length word = the LLM invented it: ignored)."""
    lo, hi = CFG["clip_seconds"]
    if job.wanted:
        w_lo, w_hi = job.wanted
        want = a.seconds if a.seconds and w_lo <= a.seconds <= w_hi else (w_lo + w_hi) / 2
    elif job.change:                                                  # "make it longer / 30 s shorter" (2026-10-09)
        kind, delta = job.change
        base = job.base_length(a.start, a.end)
        if delta:
            want = base + delta if kind == "longer" else base - delta
        else:                                                         # no number: half as long again / two thirds
            want = max(base * 1.5, base + 10) if kind == "longer" else min(base / 1.5, base - 10)
        want = min(max(want, lo), hi)
        return want, f"{want:.0f} s long ({kind} than the {base:.0f} s before, as the user asked)"
    elif a.seconds and LENGTH_WORD.search(job.message):
        want = a.seconds
    else:
        return None, ""
    if not lo <= want <= hi:
        return min(max(want, lo), hi), f"a clip can be {lo}-{hi} s long, so it is {min(max(want, lo), hi):.0f} s"
    return want, f"{want:.0f} s long, as the user asked"


def auto_title(job, segs, a, b):
    """The first words said in the clip, in the user's language (when the LLM gives no usable title)."""
    key = "text" if job.lang == job.meta["language"] else "translation"
    return CJK.sub("", " ".join(" ".join(r.get(key, "") for r in segs if a <= r["start"] < b).split()[:6])).strip()


def make_clip(job, a: ClipArgs):
    s, dur, notes = job.s, job.meta["duration"], []
    limit = min(job.count or CFG["max_clips"], CFG["max_clips"])      # 1 unless the user asked for more (2026-10-09)
    if len(job.clips) >= limit:
        if (job.count or CFG["max_clips"] + 1) > CFG["max_clips"]:
            raise ValueError(f"at most {CFG['max_clips']} clips per request")
        raise ValueError(f"the user asked for {limit} clip{'s' if limit > 1 else ''} and "
                         f"{'it is' if limit == 1 else 'they are'} made: make no more clips, answer the user now")
    if a.start >= dur - CFG["clip_seconds"][0]:
        raise ValueError(f"start {a.start} s is too close to the end of the video ({dur} s)")
    if not (job.allowed(a.start, a.end) or job.earlier(a.start, a.end)):    # a tool's moment, or an earlier clip
        raise ValueError("these times did not come from a tool. Call search_transcript first and use the start "
                         "of a moment it returns")
    start, end = a.start, a.end
    want, note = clip_length(job, a)
    if want:                                                          # the asked length (the code does the maths)
        start, end = a.start, a.start + want
        if end > dur:                                                 # near the end of the video: start earlier
            start, end = max(0.0, dur - want), dur
        notes.append(note)
    if end > dur:
        end = dur
        notes.append(f"end moved to the end of the video ({dur} s)")
    segs = read_json(s / "transcript.json") if (s / "transcript.json").exists() else []
    start, end2 = to_sentences(segs, start, end)
    if end2 - start <= CFG["clip_seconds"][1]:
        end = end2
    if (start, end) != (round(a.start, 2), round(a.end, 2)) and not notes:
        notes.append(f"moved to whole sentences: {start}-{end} s")
    title = a.title.strip()
    problem = title_problem(title, job.lang, " ".join(r["text"] for r in segs if start <= r["start"] < end))
    if problem and job.title_tries < 2:                               # the LLM writes it again (at most twice)
        job.title_tries += 1
        raise ValueError(f"{problem}. Call make_clip again with a title of 3-7 catchy words in {NAMES[job.lang]}")
    if problem or not title:
        title = auto_title(job, segs, start, end)
    captions = (asked_captions(job.message)                           # what the user typed, read by the code
                or (a.captions if CAPTION.search(job.message) else None)   # ... or by the LLM (words we don't know)
                or default_captions(job.lang))                        # not asked: English -> ar+en, Arabic -> ar
    focus, target = focus_target(job, a.focus_speaker)
    if a.focus_speaker and not focus:
        notes.append("the user did not ask to show a particular person: the AI edit")
    prev = job.earlier(a.start, a.end)                                # the format: asked > the earlier clip's > 16:9
    fmt = job.format or (prev["format"] if prev and prev["format"] in ("16:9", "9:16") else "16:9")
    source, crop_x, shows, more = clip_source(job, start, end, fmt, focus, target)
    notes += more
    old = read_json(s / "clips.json") if (s / "clips.json").exists() else []
    cid = f"c{max([int(c['id'][1:]) for c in old + job.clips if c['id'][1:].isdigit()], default=0) + 1}"  # new id
    clip = {"id": cid, "start": start, "end": end, "format": fmt, "title": title,
            "file": f"clips/{cid}.mp4", "focus_speaker": focus, "captions": captions}
    if job.render:
        render_clip(s, start, end, clip["file"], fmt=fmt, source=source, crop_x=crop_x, langs=captions)
        write_json(s / "clips.json", old + [clip])                     # after the video exists
    job.clips.append(clip)
    return {**clip, "seconds": round(end - start, 1), "shows": shows, "notes": notes}


def restyle_video(job, a: RestyleArgs):
    """A new version of the WHOLE video: the director again, with one camera boosted and/or one fixed mode."""
    if not a.focus_speaker and not a.mode:
        raise ValueError("give focus_speaker or mode (or both)")
    person = focus_target(job, a.focus_speaker)[0]                    # nobody asked for -> nobody
    if not person and a.mode in (None, "conversation") and not CONVERSATION.search(job.message):
        # "خلي الفيديو أحسن" / "make the video better" became a restyle with an invented person (2026-10-09 eval)
        raise ValueError("the user named no person and no style, so nothing would change. Do NOT call tools: ask the "
                         "user ONE short question about what to change (e.g. show someone more, more reactions)")
    a.focus_speaker = person
    cam = None
    if a.focus_speaker:
        cam = job.speaker(a.focus_speaker)["camera"]
        if cam is None:
            raise ValueError(f"{a.focus_speaker} has no close-up camera, so the video can't show them more")
    if not job.render:
        return {"file": "program_v2.mp4", "note": "test run: nothing rendered"}
    cuts = make_cuts(job.s, boost={"cam": cam, "factor": 1.4} if cam else None, force_mode=a.mode, out="cuts_v2.json")
    render_program(job.s, cuts, out="program_v2_nocaps.mp4")
    add_captions(job.s, "program_v2_nocaps.mp4", "program_v2.mp4")
    return {"file": "program_v2.mp4", "shots": len(cuts), "note": "a new version of the whole video "
                                                                   "(the first version program.mp4 is kept)"}


def list_clips(job, a: NoArgs):
    out = []
    if (job.s / "highlights.json").exists():
        out += [{k: h[k] for k in ("id", "start", "end", "title_ar", "title_en", "files")}
                for h in read_json(job.s / "highlights.json")]
    if (job.s / "clips.json").exists():
        out += [{k: c.get(k) for k in ("id", "start", "end", "title", "format", "captions", "file")}
                for c in read_json(job.s / "clips.json")]
    job.saw((c["start"], c["end"]) for c in out)                       # "make highlight h1 vertical" may use its times
    return {"clips": out}


FUNCS = {"search_transcript": search_transcript, "get_scenes": get_scenes, "get_speakers": get_speakers,
         "make_clip": make_clip, "restyle_video": restyle_video, "list_clips": list_clips}
ARGS = {"search_transcript": SearchArgs, "get_scenes": ScenesArgs, "get_speakers": NoArgs,
        "make_clip": ClipArgs, "restyle_video": RestyleArgs, "list_clips": NoArgs}
DESCRIPTIONS = {
    "search_transcript": "Search what was said in the video by meaning (Arabic or English). Returns moments (about "
                         "30 s each, best first) with start/end seconds, the main speaker and the text. Use this "
                         "before making any clip.",
    "get_scenes": "What the cameras showed between start and end (seconds): scene description, event (talking, "
                  "laughter, demo, ...), energy 0-1, highlight. Use it to find funny or lively moments.",
    "get_speakers": "The people in the video: SPEAKER id, role (host, guest, ...), name, close-up camera and "
                    "talking time.",
    "make_clip": "Render a clip: start and end = a moment that a tool returned; if the user asked for a length, also "
                 "seconds (the clip is made that long for you). 16:9 or 9:16 (vertical), optionally showing one "
                 "person (focus_speaker). Edges are moved to whole sentences. Returns the clip file.",
    "restyle_video": "Make a new version of the WHOLE video: show one person more (focus_speaker) and/or use one "
                     "editing style (mode). Only when the user wants the whole video changed; takes a few minutes.",
    "list_clips": "The clips and highlights already made for this video (ids, times, titles).",
}
TOOLS = [{"type": "function", "function": {"name": n, "description": DESCRIPTIONS[n],
                                           "parameters": ARGS[n].model_json_schema()}} for n in FUNCS]
