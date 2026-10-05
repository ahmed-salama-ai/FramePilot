# ai_director/audio/gemini.py — Gemini API keys for the audio stage (Ahmed Salama)
# Keys come from .env (or Windows environment variables): GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_API_KEY_3, ...
# as many as you have. Never write a key in code, configs or Git.
import os
import re
import time

import yaml

from ..common.env import load_env
from ..common.paths import CONFIGS

CFG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["audio"]
PREFIX = CFG["api_key_prefix"]
KEY_NAME = re.compile(rf"^{PREFIX}(_\d+)?$")
BUSY = ("429", "RESOURCE_EXHAUSTED", "500", "503", "504", "UNAVAILABLE", "INTERNAL", "overloaded", "DEADLINE")
_CLIENTS = []


def key_names(env=None):
    """Names of every Gemini key that is set: GEMINI_API_KEY, GEMINI_API_KEY_2, ... (any number), in order."""
    env = os.environ if env is None else env
    names = [n for n, v in env.items() if KEY_NAME.match(n) and v.strip()]
    return sorted(names, key=lambda n: int(n[len(PREFIX) + 1:] or 0) if n != PREFIX else 1)


def clients():
    """One Gemini client per key, as [(key name, client), ...], made once."""
    if not _CLIENTS:
        load_env()
        names = key_names()
        if not names:
            raise RuntimeError(f"No Gemini API key. Put {PREFIX}=... (and {PREFIX}_2=..., {PREFIX}_3=..., if you "
                               "have more) in the .env file in the repo folder (copy .env.example).")
        from google import genai                                  # import only when Gemini is really used
        _CLIENTS.extend((n, genai.Client(api_key=os.environ[n])) for n in names)
    return _CLIENTS


def with_keys(fn, start=0, keyed=None, rounds=6, wait=30):
    """Return (fn(client), key name) with the first key that works, starting at key number `start`.
    Busy / rate limit -> the next key; every key busy -> wait and try again; daily limit -> skip that key."""
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
