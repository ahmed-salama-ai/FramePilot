# ai_director/brain/modes.py — smooth the director modes and write the final scene.jsonl (the done file)
# Owner: Eslam ElKharbotly
import json
from pathlib import Path


def read_rows(path: Path) -> list:
    """The lines of scene.partial.jsonl. A broken last line (the program was stopped while writing) is skipped."""
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def smooth_modes(session_dir: Path | str):
    """Don't change the style on one noisy answer: a new mode needs the same suggestion twice in a row (10 s);
    laughter switches to "reaction" at once. Writes scene.jsonl at the very end (the stage's done file)."""
    session_dir = Path(session_dir)
    rows = sorted(read_rows(session_dir / "scene.partial.jsonl"), key=lambda r: r["t"])
    cur, prev = "conversation", None
    for r in rows:
        r["raw_mode"] = r["mode"]                                     # what the model said
        if r["raw_mode"] == prev:                                     # same suggestion twice in a row -> switch
            cur = r["raw_mode"]
        if r["event"] == "laughter":                                  # laughter reacts at once
            cur = "reaction"
        r["mode"], prev = cur, r["raw_mode"]                          # what the director uses
    with open(session_dir / "scene.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    print(f"  scene.jsonl: {len(rows)} lines")
