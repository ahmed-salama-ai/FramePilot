import shutil
from datetime import datetime
from pathlib import Path

from ai_director.common.io import read_json, write_json

V1 = {"id": "v1", "made_by": "pipeline", "note": "", "created": "", "cuts": "cuts.json",
      "nocaps": "program_nocaps.mp4", "program": "program.mp4", "clean": "program_clean.mp4", "intro": 0.0,
      "removed": [], "cold_open": None}
DEFAULTS = {"clean": "", "intro": 0.0, "removed": [], "cold_open": None}       # fields older versions don't have


def list_versions(session_dir):
    """[version, ...] oldest first; v1 always first when its video exists."""
    s = Path(session_dir)
    items = read_json(s / "versions.json") if (s / "versions.json").exists() else []
    items = [{**DEFAULTS, **v} for v in items]
    if not any(v["id"] == "v1" for v in items) and ((s / "program.mp4").exists() or (s / "program_nocaps.mp4").exists()):
        items.insert(0, dict(V1))
    if not (s / "versions.json").exists() and (s / "program_v2.mp4").exists():
        items.append({"id": "v2", "made_by": "agent", "note": "restyle (made before version history)", "created": "",
                      "cuts": "cuts_v2.json", "nocaps": "program_v2_nocaps.mp4", "program": "program_v2.mp4",
                      **DEFAULTS})
    return items


def get_version(session_dir, vid):
    """A version by its id; "latest" = the newest one."""
    items = list_versions(session_dir)
    if vid == "latest" and items:
        return items[-1]
    v = next((v for v in items if v["id"] == vid), None)
    if v is None:
        raise ValueError(f"no version {vid!r}; there are: {', '.join(x['id'] for x in items)}")
    return v


def new_version(session_dir, made_by, note="", base=None):
    """The next free version (vN) with its folder made; add it with add_version() AFTER its videos exist.
    base = the version an update is made from: the new one shares its cut list and plain edit (no new edit) and so
    the pauses cut out of it."""
    s = Path(session_dir)
    used = [int(v["id"][1:]) for v in list_versions(s) if v["id"][1:].isdigit()]
    if (s / "versions").exists():
        used += [int(p.name[1:]) for p in (s / "versions").iterdir() if p.name[1:].isdigit()]
    vid = f"v{max(used + [1]) + 1}"
    (s / "versions" / vid).mkdir(parents=True, exist_ok=True)
    folder = f"versions/{vid}"
    return {"id": vid, "made_by": made_by, "note": note, "created": datetime.now().isoformat(timespec="seconds"),
            "cuts": base["cuts"] if base else f"{folder}/cuts.json",
            "nocaps": base["nocaps"] if base else f"{folder}/program_nocaps.mp4",
            "program": f"{folder}/program.mp4", "clean": f"{folder}/program_clean.mp4", "intro": 0.0,
            "removed": list((base or {}).get("removed") or []), "cold_open": None}


def add_version(session_dir, version):
    """Save a version in versions.json (a version with the same id is replaced)."""
    s = Path(session_dir)
    items = list_versions(s)
    if any(v["id"] == version["id"] for v in items):
        items = [version if v["id"] == version["id"] else v for v in items]
    else:
        items.append(version)
    write_json(s / "versions.json", items)
    return items


def delete_version(session_dir, vid, trash):
    """Remove a version (never v1): its folder moves to `trash` (not erased). A version whose files another version
    still uses (an update made from it) can't be deleted before that one. Returns the remaining versions."""
    s = Path(session_dir)
    if vid == "v1":
        raise ValueError("v1 is the pipeline's edit and can't be deleted")
    v = get_version(s, vid)
    folder = Path(v["program"]).parent
    if folder != Path("."):
        users = [x["id"] for x in list_versions(s) if x["id"] != vid and
                 any(Path(x[k]).parent == folder for k in ("cuts", "nocaps"))]
        if users:
            raise ValueError(f"{', '.join(users)} {'was' if len(users) == 1 else 'were'} made from {vid} and still "
                             f"use{'s' if len(users) == 1 else ''} its files: delete {', '.join(users)} first")
        if (s / folder).exists():
            Path(trash).mkdir(parents=True, exist_ok=True)
            shutil.move(str(s / folder), str(Path(trash) / f"{s.name}_{vid}_{datetime.now():%Y%m%d_%H%M%S}"))
    else:                                                    # an old restyle: its files sit in the session folder
        for key in ("cuts", "nocaps", "program"):
            (s / v[key]).unlink(missing_ok=True)
    items = [x for x in list_versions(s) if x["id"] != vid]
    write_json(s / "versions.json", items)
    return items


def video_time(version, t):
    """A time of the edit (the cameras' time: cuts, captions, chapters) -> the time in this version's finished video
    (pauses cut out, then the cold open + brand intro in front)."""
    from ai_director.director.pauses import out_time
    return round(out_time(t, version.get("removed")) + (version.get("intro") or 0.0), 3)


def version_captions(session_dir, version, langs="ar", fmt="srt"):
    """The captions as SRT / VTT text timed for this version's finished video (the session's
    captions_*.srt are in the cameras' time; with a brand intro or cut pauses they would be early)."""
    from ai_director.audio.subtitles import caption_items, ts
    items = []
    for x in caption_items(Path(session_dir), langs):
        a, b = video_time(version, x["start"]), video_time(version, x["end"])
        if b - a >= 0.05:
            items.append((a, b, x["text"]))
    if fmt == "vtt":
        return "WEBVTT\n\n" + "\n".join(f"{ts(a, '.')} --> {ts(b, '.')}\n{t}\n" for a, b, t in items)
    return "\n".join(f"{i}\n{ts(a)} --> {ts(b)}\n{t}\n" for i, (a, b, t) in enumerate(items, 1))
