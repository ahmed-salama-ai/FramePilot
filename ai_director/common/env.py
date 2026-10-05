# ai_director/common/env.py — read secrets (HF token, API keys) from the .env file in the repo root.
# .env is in .gitignore: it never goes to GitHub. Copy .env.example to .env and fill it in.
import os
from pathlib import Path

from .paths import ROOT


def load_env(path: Path | None = None):
    """KEY=VALUE lines from .env -> environment variables. A variable already set in Windows wins;
    empty values and # comments are ignored."""
    path = Path(path) if path else ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():          # utf-8-sig: Notepad's BOM is fine
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and value and not os.environ.get(key):
            os.environ[key] = value
