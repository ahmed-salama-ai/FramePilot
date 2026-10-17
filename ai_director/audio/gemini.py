import os
import re
import time

import yaml

from ..common.env import load_env
from ..common.paths import CONFIGS

CFG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["audio"]
PREFIX = CFG["api_key_prefix"]
KEY_NAME = re.compile(rf"^{PREFIX}(_\d+)?$")
BUSY = ("429", "RESOURCE_EXHAUSTED", "500", "503", "504", "UNAVAILABLE", "INTERNAL", "overloaded", "DEADLINE",
        "timed out", "Timeout")
_CLIENTS = []


def key_names(env=None):
    env = os.environ if env is None else env
    names = [n for n, v in env.items() if KEY_NAME.match(n) and v.strip()]
    return sorted(names, key=lambda n: int(n[len(PREFIX) + 1:] or 0) if n != PREFIX else 1)


def clients():
    if not _CLIENTS:
        load_env()
        names = key_names()
        if not names:
            raise RuntimeError(f"No Gemini API key. Put {PREFIX}=... (and {PREFIX}_2=..., {PREFIX}_3=..., if you "
                               "have more) in the .env file in the repo folder (copy .env.example).")
        from google import genai
        _CLIENTS.extend((n, genai.Client(api_key=os.environ[n])) for n in names)
    return _CLIENTS


def with_keys(fn, start=0, keyed=None, rounds=6, wait=30):
    keyed = keyed if keyed is not None else clients()
    alive = list(range(len(keyed)))
    for rnd in range(rounds):
        if not alive:
            break
        first = start % len(alive)
        for i in alive[first:] + alive[:first]:
            try:
                return fn(keyed[i][1]), keyed[i][0]
            except Exception as e:
                msg = str(e)
                if "PerDay" in msg or "per day" in msg.lower():
                    alive.remove(i)
                    print(f"    {keyed[i][0]}: daily limit used up -> skipped")
                elif any(b in msg for b in BUSY):
                    print(f"    {keyed[i][0]}: busy / rate limit -> next key ({msg[:120]})")
                else:
                    raise
        if alive and rnd < rounds - 1:
            print(f"    all keys busy -> waiting {wait * (rnd + 1)} s")
            time.sleep(wait * (rnd + 1))
    raise RuntimeError("Gemini: no key can be used right now (rate or daily limits). Try again later; finished "
                       "pieces are saved. If every key says 'limit: 0', the model needs billing switched on.")


def ask_json(model, prompt, schema, temperature=0.2, timeout=120):
    def call(client):
        r = client.models.generate_content(model=model, contents=prompt, config={
            "response_mime_type": "application/json", "response_schema": schema, "temperature": temperature,
            "http_options": {"timeout": timeout * 1000}})
        return r.parsed if r.parsed is not None else schema.model_validate_json(r.text or "{}")
    return with_keys(call)[0]
