from pathlib import Path

from ai_director.common.io import read_json

ROLE_LABELS = {
    "ar": {"host": "مقدم البرنامج", "co-host": "مقدم مشارك", "guest": "ضيف الحلقة", "interviewer": "المحاور",
           "interviewee": "الضيف", "moderator": "مدير الحوار", "panelist": "متحدث", "presenter": "المقدم",
           "audience": "من الجمهور", "other": ""},
    "en": {"host": "Host", "co-host": "Co-host", "guest": "Guest", "interviewer": "Interviewer", "interviewee": "Guest",
           "moderator": "Moderator", "panelist": "Panelist", "presenter": "Presenter", "audience": "Audience",
           "other": ""},
}
SECONDS = 4.0          #card time
MIN_TALK = 1.5         #min talk to show
MIN_ON = 2.0           #min camera time


def read(s, name, default):
    return read_json(s / name) if (s / name).exists() else default


def face_side(s, speaker, cam, diar):
    """ left/right position"""
    f = s / "features.parquet"
    if not f.exists():
        return None
    import pandas as pd
    rows = pd.read_parquet(f, columns=["t", "cam", "face_area", "face_x"])
    rows = rows[(rows.cam == cam) & (rows.face_area > 0)]
    own = pd.Series(False, index=rows.index)
    for d in diar:
        if d["speaker"] == speaker:
            own |= rows.t.between(d["start"], d["end"])
    if own.sum() < 20:
        return None
    x = float(rows.face_x[own].median())
    return "left" if x < 0.45 else "right" if x > 0.55 else None


def name_cards(session_dir, cuts):
    s = Path(session_dir)
    named = [x for x in read(s, "speakers.json", []) if x.get("name_source") == "user" and x.get("name", "").strip()]
    if not named or not cuts:
        return []
    cam_of = read(s, "speaker_map.json", {})
    diar = sorted(read(s, "diarization.json", []), key=lambda d: d["start"])
    lang = read_json(s / "session.json")["language"]
    cards = []
    for x in named:
        cam = cam_of.get(x["speaker"])
        if cam is None:
            continue
        card = None
        for d in (d for d in diar if d["speaker"] == x["speaker"] and d["end"] - d["start"] >= MIN_TALK):
            for c in cuts:
                on = cam == c["cam"] or cam in (c.get("split") or [])
                a, b = max(d["start"], c["start"]), min(d["end"], c["end"])
                start = round(a + 0.3, 2)
                end = round(min(start + SECONDS, c["end"] - 0.1), 2)
                if on and b - a >= MIN_ON and end - start >= MIN_ON and \
                        not any(start < o["end"] + 0.5 and o["start"] < end + 0.5 for o in cards):
                    card = {"start": start, "end": end, "speaker": x["speaker"], "name": x["name"].strip(),
                            "role": ROLE_LABELS[lang].get(x.get("role", ""), ""),
                            "side": (("left" if c["split"].index(cam) == 0 else "right")    #its half of split
                                     if cam in (c.get("split") or []) else face_side(s, x["speaker"], cam, diar))}
                    break
            if card:
                break
        if card:
            cards.append(card)
    return sorted(cards, key=lambda c: c["start"])
