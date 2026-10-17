from pathlib import Path

from ai_director.common.io import read_json

EDGE = 30.0             # never from the first / last 30 s (the greeting, the goodbye)
ENDS = (".", "?", "!", "؟", "…")


def strongest_moment(session_dir, shortest=6.0, longest=12.0):
    """(start, end) of whole transcript rows, shortest..longest s, around the strongest second"""
    s = Path(session_dir)
    if not all((s / f).exists() for f in ("audio_events.json", "diarization.json", "transcript.json")):
        return None
    from ai_director.highlights.interest import interest_curve
    ev = interest_curve(s)
    duration = read_json(s / "session.json")["duration"]
    inside = ev[(ev.t >= EDGE) & (ev.t <= duration - EDGE)]
    if inside.empty:
        inside = ev
    peak = float(inside.t[inside.interest.idxmax()])
    rows = [r for r in read_json(s / "transcript.json") if r["end"] > r["start"]]
    best = None
    for i, r in enumerate(rows):
        if r["start"] > peak or r["start"] < peak - longest:
            continue
        for j in range(i, len(rows)):
            a, b = rows[i]["start"], rows[j]["end"]
            if b - a > longest:
                break
            if b - a < shortest or b < peak:
                continue
            sentence = rows[j]["text"].strip().endswith(ENDS)
            score = (1.0 if sentence else 0.0) - abs((b - a) - (shortest + longest) / 2) / longest
            if best is None or score > best[0]:
                best = (score, a, b)
    return (round(best[1], 2), round(best[2], 2)) if best else None
