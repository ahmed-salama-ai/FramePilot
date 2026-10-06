# ai_director/perception/speaker.py — who is talking: speaker_prob per camera + speaker_map.json
# Owner: Sara Walid (taken over by Ahmed Salama)
import numpy as np

from ..common.io import read_json


def speech_mask(times, segments):
    """True at every time that falls inside one of the segments."""
    m = np.zeros(len(times), bool)
    for seg in segments:
        m |= (times >= seg["start"]) & (times < seg["end"])
    return m


def add_speaker_prob(s, df):
    """speaker_prob = this camera's mouth movement (0..1 compared with its own busiest 5%), but only while
    somebody speaks (speech.json). Laughing or chewing in silence -> 0."""
    df["mm"] = df.groupby("cam").mouth_motion.transform(lambda x: (x / (x.quantile(0.95) + 1e-6)).clip(0, 1))
    df["speaker_prob"] = (df.mm * speech_mask(df.t.values, read_json(s / "speech.json"))).round(4)


def speaker_map(s, df):
    """{"SPEAKER_00": 2, ...}: for each speaker, the close-up camera where the mouth moves most while
    diarization says that speaker talks. Needs df["mm"] from add_speaker_prob."""
    roles = {c["id"]: c["role"] for c in read_json(s / "session.json")["cameras"]}
    close = df[df.cam.map(roles) == "closeup"]
    diar = read_json(s / "diarization.json")
    out = {}
    for spk in sorted({d["speaker"] for d in diar}):
        rows = close[speech_mask(close.t.values, [d for d in diar if d["speaker"] == spk])]
        if len(rows):
            out[spk] = int(rows.groupby("cam").mm.mean().idxmax())
    return out
