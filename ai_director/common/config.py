import copy
from pathlib import Path

import yaml

from ai_director.common.io import read_json
from ai_director.common.paths import CONFIGS, UPLOAD


def merged(base, over):
    """`base` with `over` on top: nested sections are merged key by key, other values replaced. Copies, never edits."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = merged(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def job_config(session_dir):
    """default.yaml + this job's editing style (upload.json -> style -> config)."""
    defaults = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))
    up = Path(session_dir) / UPLOAD
    style = (read_json(up).get("style") or {}) if up.exists() else {}
    return merged(defaults, style.get("config"))
