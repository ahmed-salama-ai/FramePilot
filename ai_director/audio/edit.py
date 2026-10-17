import shutil
from datetime import datetime
from pathlib import Path

from ..common.io import read_json, write_json
from .subtitles import write_all_captions


def history(s):
    h = Path(s) / "history"
    return sorted(h.glob("transcript_2*.json")) if h.exists() else []


def new_words(row, text):
    """The row's words for a new text. The same number of words (a typo fixed): every word keeps its own time. Else the
    new words share the time the old ones were spoken (first word's start to last word's end) evenly."""
    ws = text.split()
    old = row.get("words") or []
    if len(ws) == len(old):
        return [{**w, "w": x} for w, x in zip(old, ws)]
    a, b = (old[0]["start"], old[-1]["end"]) if old else (row["start"], row["end"])
    step = (b - a) / len(ws)
    return [{"w": w, "start": round(a + i * step, 2), "end": round(a + (i + 1) * step, 2)} for i, w in enumerate(ws)]


def backup(s):
    """backup old transcript"""
    h = Path(s) / "history"
    h.mkdir(exist_ok=True)
    base = f"transcript_{datetime.now():%Y%m%d_%H%M%S_%f}"
    path, k = h / f"{base}.json", 0
    while path.exists():
        k += 1
        path = h / f"{base}_{k:02d}.json"
    shutil.copyfile(Path(s) / "transcript.json", path)


def _after_change(s):
    write_all_captions(s)
    (s / "search_index.npy").unlink(missing_ok=True)


def edit_rows(session_dir, changes):
    s = Path(session_dir)
    rows = read_json(s / "transcript.json")
    by_id = {r["id"]: r for r in rows}
    changed = []
    for ch in changes:
        r = by_id.get(int(ch["id"]))
        if r is None:
            continue
        new = dict(r)
        text = " ".join(str(ch.get("text") or "").split())
        if text and text != r["text"]:
            new = {**r, "text": text, "words": new_words(r, text)}             #translation stays
        if "translation" in ch and ch["translation"] is not None:
            new["translation"] = " ".join(str(ch["translation"]).split())      #unless it was edited too
        if new != r:
            changed.append(new)
    if not changed:
        return 0
    (s / "history").mkdir(exist_ok=True)
    if not (s / "history" / "transcript_original.json").exists():
        shutil.copyfile(s / "transcript.json", s / "history" / "transcript_original.json")
    backup(s)
    for new in changed:
        by_id[new["id"]].clear()
        by_id[new["id"]].update(new)
    write_json(s / "transcript.json", rows)
    _after_change(s)
    return len(changed)


def undo(session_dir):
    """Back to the transcript before the last edit"""
    s = Path(session_dir)
    saves = history(s)
    if not saves:
        return False
    shutil.move(str(saves[-1]), str(s / "transcript.json"))
    _after_change(s)
    return True


def restore_original(session_dir):
    """Back to the original transcript"""
    s = Path(session_dir)
    orig = s / "history" / "transcript_original.json"
    if not orig.exists():
        return False
    backup(s)
    shutil.copyfile(orig, s / "transcript.json")
    _after_change(s)
    return True
