import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.signal import resample_poly

from ..common.env import load_env
from .gemini import CFG

_MODEL = {}


def wavlm_embed(clips, sr):
    """One voice fingerprint per audio clip"""
    import torch
    from transformers import AutoFeatureExtractor, WavLMForXVector
    if not _MODEL:
        load_env()
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        _MODEL.update(fe=AutoFeatureExtractor.from_pretrained(CFG["voice_model"]), dev=dev,
                      model=WavLMForXVector.from_pretrained(CFG["voice_model"]).to(dev).eval())
    out = []
    for c in clips:
        c = resample_poly(c, 16000, sr).astype("float32") if sr != 16000 else c
        inp = _MODEL["fe"]([c], sampling_rate=16000, return_tensors="pt").to(_MODEL["dev"])
        with torch.no_grad():
            e = _MODEL["model"](**inp).embeddings[0]
        out.append(torch.nn.functional.normalize(e, dim=-1).cpu().numpy())
    return np.stack(out)


def speaker_audio(audio, sr, spans, max_seconds=30.0):
    """The parts of the audio where this speaker talks, joined (at most `max_seconds`)."""
    parts, total = [], 0.0
    for a, b in spans:
        parts.append(audio[int(a * sr):int(b * sr)])
        total += b - a
        if total >= max_seconds:
            break
    return np.concatenate(parts) if parts else np.zeros(0, dtype="float32")


def link_speakers(pieces, audio, sr, n_speakers=None, same_voice=0.75, min_seconds=1.0, embed=wavlm_embed):
    """pieces: one {local label: [(start, end), ...]} per piece, in time order.
    Returns {(piece index, local label): speaker number, or None if too short to recognise}. Two voices of the same
    piece never get the same number (unless n_speakers are all used up); a voice gets a NEW number only if no known
    voice is similar enough (cosine >= same_voice) and fewer than n_speakers are known."""
    cents, weights, out = [], [], {}
    for k, spk in enumerate(pieces):
        labels = [l for l in spk if spk[l]]
        secs = {l: sum(b - a for a, b in spk[l]) for l in labels}
        with_audio = [l for l in labels if secs[l] >= 0.3]
        emb = dict(zip(with_audio, embed([speaker_audio(audio, sr, spk[l]) for l in with_audio], sr))) if with_audio else {}
        full = lambda: n_speakers is not None and len(cents) >= n_speakers
        if cents and emb:                                  #best one-to-one match with the known voices
            L = list(emb)
            sim = np.array([[float(emb[l] @ c) for c in cents] for l in L])
            for i, g in zip(*linear_sum_assignment(-sim)):
                if sim[i, g] >= same_voice or full():
                    out[(k, L[i])] = int(g)
        for l in sorted(labels, key=lambda l: -secs[l]):   #the rest: a new voice, or the closest known one
            if (k, l) in out:
                continue
            if l not in emb:
                out[(k, l)] = None                         #too short to recognise: takes the speaker before it
            elif (secs[l] >= min_seconds or not cents) and not full():
                cents.append(emb[l]); weights.append(0.0)
                out[(k, l)] = len(cents) - 1
            else:
                out[(k, l)] = int(np.argmax([float(emb[l] @ c) for c in cents]))
        for l in emb:                                      #known voices learn from this piece
            g = out[(k, l)]
            c = cents[g] * weights[g] + emb[l] * secs[l]
            cents[g] = c / (np.linalg.norm(c) or 1.0)
            weights[g] += secs[l]
    return out


def merge_extra_voices(spans, audio, sr, n_speakers, same_voice=0.95, embed=wavlm_embed):
    """One request = Gemini's own speaker labels, and it sometimes makes one person two labels. More labels than the people typed at upload -> the
    smallest label joins the voice it sounds most like, but ONLY if the two are nearly the same (cosine >= same_voice)"""
    secs = {l: sum(b - a for a, b in v) for l, v in spans.items() if v}
    if not n_speakers or len(secs) <= n_speakers:
        return {}
    alive = sorted(secs, key=secs.get)                                   #the smallest label first
    emb = dict(zip(alive, embed([speaker_audio(audio, sr, sorted(spans[l], key=lambda x: x[0] - x[1]))
                                 for l in alive], sr)))                  #its longest turns: the clearest voice
    joined = {}
    while len(alive) > n_speakers:
        for x in alive:
            y = max((y for y in alive if y != x), key=lambda y: float(emb[x] @ emb[y]))
            if float(emb[x] @ emb[y]) >= same_voice:
                joined[x] = y
                alive.remove(x)
                break
        else:
            break                                                        #every voice left is a different person
    for x in list(joined):
        while joined[x] in joined:
            joined[x] = joined[joined[x]]
    return joined


def merge_session(s):
    """An existing session: join its extra labels in transcript.json, diarization.json and speakers.json
    (no new Gemini request, no new translation). Then run perception again (speaker_map.json uses the labels)."""
    import soundfile as sf
    from ..common.io import read_json, write_json
    from .asr import make_diarization
    meta = read_json(s / "session.json")
    up = read_json(s / "upload.json") if (s / "upload.json").exists() else {}
    rows, spans = read_json(s / "transcript.json"), {}
    for d in read_json(s / "diarization.json"):
        spans.setdefault(d["speaker"], []).append((d["start"], d["end"]))
    audio, sr = sf.read(s / "audio.wav", dtype="float32")
    joined = merge_extra_voices(spans, audio.mean(axis=1) if audio.ndim > 1 else audio, sr,
                                meta.get("num_speakers") or up.get("num_speakers"), CFG["merge_voice"])
    if joined:
        rows = [{**r, "speaker": joined.get(r["speaker"], r["speaker"])} for r in rows]
        write_json(s / "diarization.json", make_diarization(rows))
        if (s / "speakers.json").exists():
            write_json(s / "speakers.json", [x for x in read_json(s / "speakers.json") if x["speaker"] not in joined])
        write_json(s / "transcript.json", rows)
    return joined


if __name__ == "__main__":
    from ..common.io import session_from_argv
    print("joined:", merge_session(session_from_argv()) or "nothing (every label is a different voice)")
