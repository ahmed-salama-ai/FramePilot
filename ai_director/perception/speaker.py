# ai_director/perception/speaker.py — who is talking: speaker_prob per camera + speaker_map.json
# Owner: Sara Walid (taken over by Ahmed Salama; 2026-10-08: the "lift" map + the transcript in speaker_prob, tested on
# s01-s03 against speaker -> camera maps checked on frames; 2026-10-09: the map per person, see CLAUDE.md)
import numpy as np
import pandas as pd

from ..common.io import read_json


def speech_mask(times, segments):
    """True at every time that falls inside one of the segments."""
    m = np.zeros(len(times), bool)
    for seg in segments:
        m |= (times >= seg["start"]) & (times < seg["end"])
    return m


def talker(times, diar):
    """For every time: the speaker who talks then (diarization), or None."""
    who = np.full(len(times), None, dtype=object)
    for d in diar:
        who[(times >= d["start"]) & (times < d["end"])] = d["speaker"]
    return who


def add_speaker_prob(s, df):
    """speaker_prob = this camera's mouth movement (0..1 compared with its own busiest 5%), but only while
    somebody speaks (speech.json). Laughing or chewing in silence -> 0."""
    df["mm"] = df.groupby("cam").mouth_motion.transform(lambda x: (x / (x.quantile(0.95) + 1e-6)).clip(0, 1))
    df["speaker_prob"] = (df.mm * speech_mask(df.t.values, read_json(s / "speech.json"))).round(4)


def person_map(s, persons, min_samples=20):
    """{"SPEAKER_00": {"cam": 2, "x": 0.77, "lift": 4.7}, ...}: for each speaker, the PERSON (one tracked head on a
    close-up camera, x = where they sit, 0..1) whose mouth moves MORE THAN USUAL while that speaker talks (the lift of
    speaker_map, per person: two people on one camera no longer share one mouth number). The camera-level map gave
    s03's woman (next to the presenter on camera 2) to camera 3; per person: 100 % of the speech right on s01-s03.
    persons = run.py's rows (t, cam, id, x, found, mouth_motion). Only people whose face was seen for min_samples
    (2 s) both while the speaker talks and while the others talk; a speaker with nobody like that is left out."""
    roles = {c["id"]: c["role"] for c in read_json(s / "session.json")["cameras"]}
    if persons is None or not len(persons):
        return {}
    p = persons[(persons.cam.map(roles) == "closeup") & persons.found & persons.mouth_motion.notna()]
    diar = read_json(s / "diarization.json")
    who, mm, out = talker(p.t.values, diar), p.mouth_motion.values, {}
    groups = p.groupby(["cam", "id"]).indices                          # one tracked person -> their rows
    for spk in sorted({d["speaker"] for d in diar}):
        mine, others = who == spk, (who != spk) & (who != None)                     # noqa: E711
        for (cam, _), i in groups.items():
            on, off = mm[i][mine[i]], mm[i][others[i]]
            if len(on) < min_samples or len(off) < min_samples:
                continue
            lift = (on.mean() + 1e-3) / (off.mean() + 1e-3)
            if spk not in out or lift > out[spk]["lift"]:
                out[spk] = {"cam": int(cam), "x": round(float(np.median(p.x.values[i])), 2), "lift": round(float(lift), 2)}
    return out


def follow_talker(s, df, persons, people, near=0.25):
    """A camera that shows two people: while a speaker talks (diarization) whose person (person_map) sits on it, the
    camera's face numbers become THAT person's face, instead of the biggest face (often the listener, e.g. the man
    next to s01's host). The scorer then sees the talker's face and the 9:16 crop (face_x) goes to them. Rows where
    the talker's face wasn't found (or nobody talks) keep the biggest face. near = how far (0..1 of the width) a head
    may be from the person's usual place."""
    if not people or persons is None or not len(persons):
        return
    p = persons[persons.found]
    who = talker(p.t.values, read_json(s / "diarization.json"))
    pick = np.zeros(len(p), bool)
    for spk, v in people.items():
        pick |= (who == spk) & (p.cam.values == v["cam"]) & (np.abs(p.x.values - v["x"]) < near)
    cols = ["face_area", "face_x", "frontalness", "mouth_motion"]
    chosen = (p[pick].sort_values("face_area").drop_duplicates(["t", "cam"], keep="last")   # one face per camera
              .set_index(["t", "cam"])[cols].fillna({"mouth_motion": 0.0}))
    at = pd.MultiIndex.from_arrays([df.t.values, df.cam.values])
    hit = at.isin(chosen.index)
    df.loc[hit, cols] = chosen.loc[at[hit], cols].values


def speaker_map(s, df, people=None):
    """{"SPEAKER_00": 2, ...}: the camera of each speaker. From person_map (people) when it knows the speaker; else
    the close-up camera whose mouth moves MORE THAN USUAL while diarization says that speaker talks: lift = mouth
    movement while they talk / while the others talk, only where a face was found. The old rule ("moves most") gave
    every s03 speaker to the camera with the clearest face (8 % of the speech right). No face found at all -> the old
    rule. Needs df["mm"] from add_speaker_prob."""
    roles = {c["id"]: c["role"] for c in read_json(s / "session.json")["cameras"]}
    close = df[df.cam.map(roles) == "closeup"]
    seen = close[close.face_area > 0] if "face_area" in close else close
    diar = read_json(s / "diarization.json")
    out = {k: v["cam"] for k, v in (people or {}).items()}
    for spk in sorted({d["speaker"] for d in diar} - set(out)):
        who, mm, cams = talker(seen.t.values, diar), seen.mm.values, seen.cam.values
        mine, others = who == spk, (who != spk) & (who != None)                     # noqa: E711
        lifts = {int(c): (mm[(cams == c) & mine].mean() + 1e-3) / (mm[(cams == c) & others].mean() + 1e-3)
                 for c in np.unique(cams) if ((cams == c) & mine).any() and ((cams == c) & others).any()}
        if lifts:
            out[spk] = max(lifts, key=lifts.get)
        else:
            rows = close[speech_mask(close.t.values, [d for d in diar if d["speaker"] == spk])]
            if len(rows):
                out[spk] = int(rows.groupby("cam").mm.mean().idxmax())
    return dict(sorted(out.items()))


def add_transcript_talk(s, df, spk_map):
    """speaker_prob = max(the mouth, the transcript): 1 on the camera of the person who talks (diarization +
    speaker_map), even when their face isn't found (standing, turned away: the s03 presenter's face was found in about a
    third of the frames). Tested: speaker coverage s01-s03 79/74/70 % -> 86/89/85 %; an average was worse than max."""
    talk = np.zeros(len(df), bool)
    for d in read_json(s / "diarization.json"):
        cam = spk_map.get(d["speaker"])
        if cam is not None:
            talk |= (df.cam.values == cam) & (df.t.values >= d["start"]) & (df.t.values < d["end"])
    df["speaker_prob"] = np.maximum(df.speaker_prob.values, talk.astype(float)).round(4)
