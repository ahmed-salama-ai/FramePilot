# ai_director/brain/scene.py — every 5 s: a 2x2 picture of all cameras + what was said -> the vision model describes
# the moment and suggests a director mode -> scene.partial.jsonl -> (modes.py) scene.jsonl
# Owner: Eslam ElKharbotly (fixed by Ahmed Salama: model from configs, English text for moondream, one bad answer
# no longer stops the stage, crash-safe resume, the wide camera's id comes from session.json)
import json
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
import yaml
from pydantic import BaseModel, Field, ValidationError

from ..common.io import read_json
from ..common.paths import CONFIGS
from .grid import grid_at
from .llm_client import chat_json, unload
from .modes import read_rows, smooth_modes

_ALL = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))
OLLAMA, CFG = _ALL["ollama"], _ALL["brain"]


class Scene(BaseModel):                       # the answer format the model must follow (= schemas.SceneLine)
    scene: str
    event: Literal["talking", "laughter", "demo", "standing", "silence", "other"]
    energy: float = Field(ge=0, le=1)
    mode: Literal["conversation", "reaction", "wide_energy", "demo"]
    highlight: bool


PROMPT = """You are a TV director watching a multi-camera show. The image shows the cameras (CAM {wide} is the wide shot).
What people said in the last {window} seconds: "{text}"
Return JSON:
scene: one short English sentence;
event;
energy from 0 (calm) to 1 (very lively);
mode: best editing style now: conversation (normal talk), reaction (laughing, surprise), wide_energy (many people move or react), demo (someone shows an object or a screen);
highlight: true only if this moment is memorable."""

FALLBACK = {"scene": "unknown", "event": "other", "energy": 0.3, "mode": "conversation", "highlight": False}


def ensure_english(s: Path):
    """Arabic session: every transcript row needs its English translation, because the vision model (moondream)
    only understands English. The audio stage normally made it (step 4); if that was skipped (Ollama was not
    running), it is made now, and the captions are written again so captions_en.srt is filled too."""
    if read_json(s / "session.json")["language"] != "ar" or not CFG["english_text"]:
        return
    if all(x.get("translation") for x in read_json(s / "transcript.json")):
        return
    from ..audio.subtitles import write_all_captions                  # Nada's code (taken over by Ahmed)
    from ..audio.translate import run_translate
    print("  the transcript has no English yet -> translating it first ...", flush=True)
    run_translate(s)                                                  # fills "translation" in transcript.json
    write_all_captions(s)


def said(tr, t, english, window):
    """What was said in the `window` seconds before t (the English translation if wanted), max 600 characters."""
    rows = [x for x in tr if t - window <= x["start"] < t]
    text = " ".join((x.get("translation") or x["text"]) if english else x["text"] for x in rows)
    return text[-600:] or "(silence)"


def run(s: Path):
    s = Path(s)
    ensure_english(s)
    meta, tr = read_json(s / "session.json"), read_json(s / "transcript.json")
    english = meta["language"] == "ar" and CFG["english_text"]
    wide = next(c["id"] for c in meta["cameras"] if c["role"] == "wide")
    model = OLLAMA["vision_model"]
    think = False if model.startswith("qwen3") else None              # only qwen3 models can "think"
    caps = {c["id"]: cv2.VideoCapture(str(s / f"video/cam{c['id']}_640.mp4")) for c in meta["cameras"]}
    part = s / "scene.partial.jsonl"
    (s / "tmp").mkdir(exist_ok=True)
    done = {r["t"] for r in read_rows(part)} if part.exists() else set()   # resumable: skip times already done
    print(f"  {model}, one picture every {CFG['every_seconds']} s, English text: {english}, "
          f"{len(done)} moments already done", flush=True)
    for t in np.arange(0, meta["duration"], CFG["every_seconds"]):
        t = round(float(t), 1)
        if t in done:
            continue
        grid = grid_at(caps, t, s / "tmp" / "grid.jpg")
        prompt = PROMPT.format(wide=wide, window=CFG["text_window"], text=said(tr, t, english, CFG["text_window"]))
        try:
            sc = chat_json(model, prompt, Scene, images=[grid], think=think).model_dump()
        except ValidationError:                                       # no usable answer twice: neutral line, go on
            sc = dict(FALLBACK)
            print(f"  [{t:6.1f} s] no usable answer -> neutral line", flush=True)
        with open(part, "a", encoding="utf-8") as f:                  # one line at a time: a crash loses max 1
            f.write(json.dumps({"t": t, **sc}, ensure_ascii=False) + "\n")
        print(f"  [{t:6.1f} s] {sc['mode']:12s} {sc['event']:9s} energy {sc['energy']:.2f}  {sc['scene'][:70]}",
              flush=True)
    for cap in caps.values():
        cap.release()
    unload(model)                                                     # free the GPU for the next stage
    smooth_modes(s)                                                   # writes scene.jsonl LAST (the done file)
