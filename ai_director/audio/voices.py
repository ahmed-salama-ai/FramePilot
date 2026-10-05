# ai_director/audio/voices.py — the same person in different 1-minute pieces gets ONE name (Ahmed Salama)
# Gemini names the speakers of every piece on its own (its "spk_0" in minute 1 may be "spk_1" in minute 2), so each
# piece's speakers are matched by how their VOICE sounds: a voice fingerprint (WavLM x-vector, a list of numbers that
# is similar for the same voice) is compared with the speakers found so far.
import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.signal import resample_poly

from ..common.env import load_env
from .gemini import CFG

_MODEL = {}


def wavlm_embed(clips, sr):
    """One voice fingerprint per audio clip (length 1, so a dot product = cosine similarity)."""
    import torch
    from transformers import AutoFeatureExtractor, WavLMForXVector
    if not _MODEL:
        load_env()                                         # HF_TOKEN from .env, used by Hugging Face downloads
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
        if cents and emb:                                  # best one-to-one match with the known voices
            L = list(emb)
            sim = np.array([[float(emb[l] @ c) for c in cents] for l in L])
            for i, g in zip(*linear_sum_assignment(-sim)):
                if sim[i, g] >= same_voice or full():
                    out[(k, L[i])] = int(g)
        for l in sorted(labels, key=lambda l: -secs[l]):   # the rest: a new voice, or the closest known one
            if (k, l) in out:
                continue
            if l not in emb:
                out[(k, l)] = None                         # too short to recognise: takes the speaker before it
            elif (secs[l] >= min_seconds or not cents) and not full():
                cents.append(emb[l]); weights.append(0.0)
                out[(k, l)] = len(cents) - 1
            else:
                out[(k, l)] = int(np.argmax([float(emb[l] @ c) for c in cents]))
        for l in emb:                                      # known voices learn from this piece
            g = out[(k, l)]
            c = cents[g] * weights[g] + emb[l] * secs[l]
            cents[g] = c / (np.linalg.norm(c) or 1.0)
            weights[g] += secs[l]
    return out
