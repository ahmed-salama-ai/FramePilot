import json
from pathlib import Path

import yaml

from ..common.paths import CONFIGS

CFG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["brain"]


def read_rows(path: Path) -> list:
    """The lines of scene.partial.jsonl. A broken last line (the program was stopped while writing) is skipped."""
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def laughs(session_dir: Path):
    """{second: laughter 0..1} from audio_events.json (audio stage), or None if there is no such file."""
    f = session_dir / "audio_events.json"
    return {int(x["t"]): x["laugh"] for x in json.loads(f.read_text(encoding="utf-8"))} if f.exists() else None


def smooth_modes(session_dir: Path | str, every=5):
    """Don't change the style on one noisy answer: a new mode needs the same suggestion twice in a row (10 s).
    Laughter switches to "reaction" at once: the audio hears laughter in these 5 s (>= brain.laugh), or the vision
    model says "laughter" AND the audio hears at least a little around it (>= brain.laugh_agree"""
    session_dir = Path(session_dir)
    rows = sorted(read_rows(session_dir / "scene.partial.jsonl"), key=lambda r: r["t"])
    audio = laughs(session_dir)
    near = lambda a, b: max((audio.get(k, 0.0) for k in range(int(a), int(b))), default=0.0)
    cur, prev = "conversation", None
    for r in rows:
        r["raw_mode"] = r["mode"]                                     #what the model said
        if r["raw_mode"] == prev:                                     #same suggestion twice in a row -> switch
            cur = r["raw_mode"]
        heard = audio is not None and near(r["t"], r["t"] + every) >= CFG["laugh"]
        seen = r["event"] == "laughter" and (audio is None or near(r["t"] - every, r["t"] + every) >= CFG["laugh_agree"])
        if heard or seen:                                             #laughter reacts at once
            cur = "reaction"
        r["mode"], prev = cur, r["raw_mode"]                          #what the director uses
    with open(session_dir / "scene.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    print(f"  scene.jsonl: {len(rows)} lines")
