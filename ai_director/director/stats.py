from pathlib import Path

from ai_director.common.io import read_json

TURN_GAP = 1.0          #the same person again within 1 s = the same turn
JUMP_IN = 0.2           #starting less than 0.2 s after someone else stopped (or over them) = jumped in
LAUGH = 0.25            #audio laughter at or above this = a laughter moment ...
LAUGH_JOIN = 3          #and laughing seconds less than 3 s apart are one moment


def read(s, name, default):
    return read_json(s / name) if (s / name).exists() else default


def turns(diar):
    """Diarization pieces -> turns: one person talking, pieces less than TURN_GAP s apart joined."""
    out = []
    for d in sorted(diar, key=lambda d: d["start"]):
        if out and out[-1]["speaker"] == d["speaker"] and d["start"] - out[-1]["end"] < TURN_GAP:
            out[-1]["end"] = max(out[-1]["end"], d["end"])
        else:
            out.append({"speaker": d["speaker"], "start": d["start"], "end": d["end"]})
    return out


def laughter(events):
    """[{start, end, peak}] of the laughter moments."""
    out = []
    for e in events:
        if e.get("laugh", 0) < LAUGH:
            continue
        if out and e["t"] - out[-1]["end"] < LAUGH_JOIN:
            out[-1]["end"], out[-1]["peak"] = e["t"] + 1, max(out[-1]["peak"], e["laugh"])
        else:
            out.append({"start": e["t"], "end": e["t"] + 1, "peak": e["laugh"]})
    return [{**m, "peak": round(m["peak"], 2)} for m in out]


def speaker_stats(session_dir):
    """{"duration", "talk_share", "changes_per_min", "people": [...], "laughs": [...]} or None (no diarization).
    people: speaker, seconds, share (% of all talk), turns, longest {seconds, start}, words, wpm, jumped_in."""
    s = Path(session_dir)
    diar = read(s, "diarization.json", [])
    if not diar:
        return None
    duration = read_json(s / "session.json")["duration"]
    tt = turns(diar)
    words = {}
    for r in read(s, "transcript.json", []):
        words[r.get("speaker")] = words.get(r.get("speaker"), 0) + len(r.get("words") or r.get("text", "").split())
    people = {}
    for t in tt:
        p = people.setdefault(t["speaker"], {"speaker": t["speaker"], "seconds": 0.0, "turns": 0,
                                             "longest": {"seconds": 0.0, "start": 0.0}, "jumped_in": 0})
        p["seconds"] += t["end"] - t["start"]
        p["turns"] += 1
        if t["end"] - t["start"] > p["longest"]["seconds"]:
            p["longest"] = {"seconds": round(t["end"] - t["start"], 1), "start": round(t["start"], 2)}
    for a, b in zip(tt, tt[1:]):
        if a["speaker"] != b["speaker"] and b["start"] - a["end"] < JUMP_IN:
            people[b["speaker"]]["jumped_in"] += 1
    total = sum(p["seconds"] for p in people.values()) or 1.0
    for p in people.values():
        p["share"] = round(100 * p["seconds"] / total, 1)
        p["words"] = words.get(p["speaker"], 0)
        p["wpm"] = round(p["words"] / (p["seconds"] / 60)) if p["seconds"] > 0 else 0
        p["seconds"] = round(p["seconds"], 1)
    changes = sum(1 for a, b in zip(tt, tt[1:]) if a["speaker"] != b["speaker"])
    return {"duration": duration, "talk_share": round(100 * total / duration, 1),
            "changes_per_min": round(changes / (duration / 60), 1),
            "people": sorted(people.values(), key=lambda p: -p["seconds"]),
            "laughs": laughter(read(s, "audio_events.json", []))}
