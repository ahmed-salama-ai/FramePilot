# ai_director/agent/tools.py — the Editor Agent's 6 tools. Every tool = an argument model (Pydantic checks what the LLM
# sends) + a function + a description (the LLM chooses tools only from the descriptions).
# Owner: Eslam ElKharbotly (fixed by Ahmed Salama: speakers and roles from speakers.json, clip times only from tool
# results, clips moved to whole sentences, 9:16 cropped on the speaker's face, errors instead of silent changes)
import re
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field, field_validator, model_validator

from ..common.io import read_json, read_jsonl, write_json
from ..director.render import add_captions, render_clip, render_program      # Ahmed Salama
from ..director.run import make_cuts
from ..highlights.clips import vertical_source                              # Sara (9:16: speaker + face position)
from .search import CFG, embed as bge_m3, search

MODES = Literal["conversation", "reaction", "wide_energy", "demo"]
FORMATS = {"vertical": "9:16", "portrait": "9:16", "9x16": "9:16", "9/16": "9:16",
           "horizontal": "16:9", "landscape": "16:9", "16x9": "16:9", "16/9": "16:9"}


def typed_times(message):
    """Times the user typed, like 2:30 or 1:02:30 -> a range a clip may use (first to last time, or 3 min after one)."""
    ts = [sum(int(p) * 60 ** k for k, p in enumerate(reversed(m.split(":"))))
          for m in re.findall(r"(?<![\d:])\d{1,2}(?::\d{2}){1,2}(?![\d:])", message)]
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


class Job:
    """What the tools know about ONE chat request: the session, the user's message, the time ranges that tools
    returned (a clip may only use those: no invented times) and the clips made so far.
    render=False: decide everything but make no video (fast agent tests). embed: the search model (tests: a fake)."""

    def __init__(self, s, message="", render=True, embed=None):
        self.s, self.message, self.render, self.embed = Path(s), message, render, embed or bge_m3
        self.meta = read_json(self.s / "session.json")
        self.speakers = speaker_list(self.s, self.meta)
        self.seen = typed_times(message)
        self.clips = []

    def saw(self, ranges):
        self.seen += [(float(a), float(b)) for a, b in ranges]

    def allowed(self, a, b):
        """True if the clip overlaps a range that a tool returned (1 s tolerance)."""
        return any(a < y + 1 and x - 1 < b for x, y in self.seen)

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
    top_k: int = Field(5, ge=1, le=10, description="how many moments (1-10)")


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
    end: float = Field(description="seconds")
    format: Literal["16:9", "9:16"] = Field("16:9", description='"9:16" = vertical (TikTok, Reels, Shorts), '
                                                               'else "16:9"')
    focus_speaker: str | None = Field(None, description="SPEAKER_xx of the person to show, or null")
    captions: Literal["ar", "en", "ar+en", "none"] = Field("ar+en", description="caption languages")
    title: str = Field("", description="a short catchy title in the user's language")

    @field_validator("format", mode="before")
    @classmethod
    def format_word(cls, v):                       # "vertical" -> "9:16" (a word, not a ratio)
        return FORMATS.get(str(v).strip().lower(), v)

    @field_validator("focus_speaker", mode="before")
    @classmethod
    def focus_null(cls, v):
        return no_null(v)

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
    moments = search(job.s, a.query, a.top_k, embed=job.embed)
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


def clip_source(job, a, b, fmt, focus):
    """Where the clip is cut from: a person's close-up camera, or the AI edit ("program"); for 9:16 also where to
    crop (face position). Returns (source, crop_x, what the viewer sees)."""
    f = job.s / "features.parquet"
    feats = (pd.read_parquet(f, columns=["t", "cam", "face_area", "face_x"]) if f.exists()
             else pd.DataFrame(columns=["t", "cam", "face_area", "face_x"]))
    if focus:
        cam = job.speaker(focus)["camera"]
        if cam is None:
            return "program", None, f"the AI edit ({focus} has no close-up camera)"
        return cam, (face_x(feats, cam, a, b) if fmt == "9:16" else None), f"camera {cam} ({focus})"
    if fmt == "9:16" and (job.s / "cuts.json").exists():
        source, x = vertical_source(job.s, a, b, read_json(job.s / "cuts.json"), feats)
        return source, x, "the AI edit" if source == "program" else f"camera {source} (the main speaker)"
    return "program", None, "the AI edit"


def make_clip(job, a: ClipArgs):
    s, dur, notes = job.s, job.meta["duration"], []
    if len(job.clips) >= CFG["max_clips"]:
        raise ValueError(f"at most {CFG['max_clips']} clips per request")
    if a.start >= dur - CFG["clip_seconds"][0]:
        raise ValueError(f"start {a.start} s is too close to the end of the video ({dur} s)")
    if not job.allowed(a.start, a.end):
        raise ValueError("these times did not come from a tool. Call search_transcript first and use the start "
                         "of a moment it returns")
    end = a.end
    if end > dur:
        end = dur
        notes.append(f"end moved to the end of the video ({dur} s)")
    segs = read_json(s / "transcript.json") if (s / "transcript.json").exists() else []
    start, end2 = to_sentences(segs, a.start, end)
    if end2 - start <= CFG["clip_seconds"][1]:
        end = end2
    if (start, end) != (round(a.start, 2), round(a.end, 2)) and not notes:
        notes.append(f"moved to whole sentences: {start}-{end} s")
    source, crop_x, shows = clip_source(job, start, end, a.format, a.focus_speaker)
    title = a.title.strip() or " ".join(" ".join(r["text"] for r in segs if start <= r["start"] < end).split()[:6])
    old = read_json(s / "clips.json") if (s / "clips.json").exists() else []
    cid = f"c{max([int(c['id'][1:]) for c in old + job.clips if c['id'][1:].isdigit()], default=0) + 1}"  # new id
    clip = {"id": cid, "start": start, "end": end, "format": a.format, "title": title,
            "file": f"clips/{cid}.mp4", "focus_speaker": a.focus_speaker}
    if job.render:
        render_clip(s, start, end, clip["file"], fmt=a.format, source=source, crop_x=crop_x, langs=a.captions)
        write_json(s / "clips.json", old + [clip])                     # after the video exists
    job.clips.append(clip)
    return {**clip, "seconds": round(end - start, 1), "shows": shows, "notes": notes}


def restyle_video(job, a: RestyleArgs):
    """A new version of the WHOLE video: the director again, with one camera boosted and/or one fixed mode."""
    if not a.focus_speaker and not a.mode:
        raise ValueError("give focus_speaker or mode (or both)")
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
        out += [{k: c.get(k) for k in ("id", "start", "end", "title", "format", "file")}
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
    "make_clip": "Render a clip from start to end (seconds from a tool result), 16:9 or 9:16 (vertical), optionally "
                 "showing one person (focus_speaker). Edges are moved to whole sentences. Returns the clip file.",
    "restyle_video": "Make a new version of the WHOLE video: show one person more (focus_speaker) and/or use one "
                     "editing style (mode). Only when the user wants the whole video changed; takes a few minutes.",
    "list_clips": "The clips and highlights already made for this video (ids, times, titles).",
}
TOOLS = [{"type": "function", "function": {"name": n, "description": DESCRIPTIONS[n],
                                           "parameters": ARGS[n].model_json_schema()}} for n in FUNCS]
