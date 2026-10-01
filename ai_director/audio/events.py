# audio/events.py  (Day 8) - one row per second -> audio_events.json (written LAST = "done" file)
from pathlib import Path
import numpy as np
import soundfile as sf
import torch
from scipy.signal import resample_poly
from panns_inference import AudioTagging, labels
from ..common.io import write_json


def run_events(s: Path):
    out = s / "audio_events.json"
    if out.exists():
        return
    wav, sr = sf.read(s / "audio.wav", dtype="float32")  # 16 kHz mono
    n = len(wav) // sr
    rms = np.sqrt((wav[: n * sr].reshape(n, sr) ** 2).mean(axis=1))
    loud_db = 20 * np.log10(rms + 1e-9)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    at = AudioTagging(checkpoint_path=None, device=device)  # PANNs wants 32 kHz
    x32 = resample_poly(wav, 2, 1).astype("float32")[: n * 32000].reshape(n, 32000)
    LAUGH = labels.index("Laughter")
    laugh = np.concatenate([at.inference(x32[b:b + 64])[0][:, LAUGH] for b in range(0, n, 64)])

    write_json(out, [{"t": i, "loudness_db": round(float(loud_db[i]), 2),
                      "laugh": round(float(laugh[i]), 3)} for i in range(n)])
