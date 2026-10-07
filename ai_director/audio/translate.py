# ai_director/audio/translate.py — 10 lines per LLM call (faster, keeps context)
# Owner: Nada Ali (edited by Ahmed Salama: works before Eslam's llm_client exists; model from configs;
# qwen3 answers without "thinking"; the GPU is freed at the end)
import json
import urllib.request
from pathlib import Path

import yaml
from pydantic import BaseModel

from ..common.io import read_json, write_json
from ..common.paths import CONFIGS

TEXT_MODEL = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["ollama"]["text_model"]

try:
    from ..brain.llm_client import chat_json, unload                 # Eslam's client (needs the ollama package)
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


class Tr(BaseModel):
    translations: list[str]


def run_translate(s: Path, batch_size=10):
    segs = read_json(s / "transcript.json")
    if segs and all(x.get("translation") for x in segs):
        return
    lang = read_json(s / "session.json")["language"]
    target = "English" if lang == "ar" else "simple Egyptian Arabic"
    for b in range(0, len(segs), batch_size):
        batch = segs[b:b + batch_size]
        prompt = (f"Translate each numbered line to {target}. Short and natural, like subtitles. "
                  f"Return exactly {len(batch)} translations in the same order.\n"
                  + "\n".join(f"{k + 1}. {x['text']}" for k, x in enumerate(batch)))
        res = chat_json(TEXT_MODEL, prompt, Tr, think=False)
        if len(res.translations) != len(batch):  # the model miscounted -> one by one
            res.translations = [
                chat_json(TEXT_MODEL, f"Translate to {target}: {x['text']}", Tr, think=False).translations[0]
                for x in batch
            ]
        for x, t in zip(batch, res.translations):
            x["translation"] = t
    write_json(s / "transcript.json", segs)
    unload(TEXT_MODEL)                                                # free the GPU for the next model
