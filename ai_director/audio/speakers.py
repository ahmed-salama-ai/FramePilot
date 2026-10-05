# ai_director/audio/speakers.py — who is each speaker (host, guest, ...) -> speakers.json (Ahmed Salama)
# A Gemini text model reads transcript.json and gives every SPEAKER_XX a role, a name (if it is said) and a
# one-sentence description.
from pathlib import Path

from pydantic import BaseModel

from ..common.io import read_json, write_json
from .gemini import CFG, with_keys

ROLES = ("host", "co-host", "guest", "interviewer", "interviewee", "moderator", "panelist", "presenter",
         "audience", "other")


class _Speaker(BaseModel):          # the answer format Gemini must follow (no defaults: every field is asked)
    speaker: str
    role: str
    name: str
    description: str


class _Answer(BaseModel):
    speakers: list[_Speaker]


def transcript_text(rows, max_chars=40000):
    """'[mm:ss] SPEAKER_00: text' lines; a very long transcript keeps every k-th line (spread over the session)."""
    lines = [f"[{int(r['start'] // 60):02d}:{int(r['start'] % 60):02d}] {r['speaker']}: {r['text']}"
             for r in rows if r["speaker"]]
    k = -(-sum(len(x) + 1 for x in lines) // max_chars)            # ceil
    return "\n".join(lines[::max(k, 1)])


def speakers_prompt(s: Path, rows):
    meta = read_json(s / "session.json")
    up = read_json(s / "upload.json") if (s / "upload.json").exists() else {}
    labels = sorted({r["speaker"] for r in rows if r["speaker"]})
    known = meta.get("speaker_names") or up.get("speaker_names") or {}
    lines = [f"Recording: {up.get('name') or meta.get('id', '')} (language: {meta['language']}).",
             f"Speaker labels: {', '.join(labels)}."]
    if known:
        lines.append("Names given by the user: " + ", ".join(f"{k} = {v}" for k, v in known.items()) + ".")
    lines += ["Read the transcript and say who each speaker is IN THIS RECORDING. For every label give:",
              f"- role: exactly one of {', '.join(ROLES)}",
              "- name: the person's name if it is said in the conversation or given above, else an empty string",
              "- description: one short English sentence about what this person does in the conversation",
              "Return exactly one entry per speaker label.", "", "Transcript:", transcript_text(rows)]
    return "\n".join(lines)


def describe(prompt, model):
    """Ask the Gemini text model (keys take turns). Returns an _Answer."""
    from google.genai import types
    cfg = types.GenerateContentConfig(temperature=0, response_mime_type="application/json", response_schema=_Answer,
                                      automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))

    def call(client):
        r = client.models.generate_content(model=model, contents=prompt, config=cfg)
        return _Answer.model_validate_json(r.text or "")
    return with_keys(call)[0]


def run_speakers(s: Path, ask=describe):
    out = s / "speakers.json"
    if out.exists():
        return
    rows = read_json(s / "transcript.json")
    labels = sorted({r["speaker"] for r in rows if r["speaker"]})
    meta = read_json(s / "session.json")
    up = read_json(s / "upload.json") if (s / "upload.json").exists() else {}
    known = meta.get("speaker_names") or up.get("speaker_names") or {}
    got = {}
    if labels:
        got = {x.speaker: x for x in ask(speakers_prompt(s, rows), CFG["speaker_model"]).speakers}
    result = []
    for lab in labels:                                                 # exactly one entry per label, always
        x = got.get(lab)
        role = x.role.strip().lower() if x else "other"
        result.append({"speaker": lab, "role": role if role in ROLES else "other",
                       "name": (x.name.strip() if x else "") or known.get(lab, ""),
                       "description": x.description.strip() if x else ""})
    write_json(out, result)
