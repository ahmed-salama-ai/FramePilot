# audio/events.py  (Day 8) - one row per second -> audio_events.json (written LAST = "done" file)
from pathlib import Path
import numpy as np
import soundfile as sf
import torch
from scipy.signal import resample_poly

import urllib.request
PANNS_DIR = Path.home() / "panns_data"
PANNS_FILES = {
    "class_labels_indices.csv": "http://storage.googleapis.com/us_audioset/youtube_corpus/v1/csv/class_labels_indices.csv",
    "Cnn14_mAP=0.431.pth": "https://zenodo.org/record/3987831/files/Cnn14_mAP%3D0.431.pth?download=1",
}

def ensure_panns_files():
    """panns_inference downloads with 'wget', which Windows doesn't have, so we download the files ourselves."""
    PANNS_DIR.mkdir(exist_ok=True)
    for name, url in PANNS_FILES.items():
        path = PANNS_DIR / name
        if not path.exists() or path.stat().st_size == 0:
            print(f"Downloading {name} ...")
            urllib.request.urlretrieve(url, path)

ensure_panns_files()
from panns_inference import AudioTagging, labels
from ..common.io import write_json


LAUGHS = [l for l in labels if any(k in l.lower() for k in ("laugh", "giggle", "snicker", "chuckle", "chortle"))]


def laughter(at, x32, n, window=3):
    """Second t -> the strongest of ALL laughter kinds (Laughter, Giggle, Snicker, Belly laugh, Chuckle...) in the
    `window` seconds around t. Ahmed Salama 2026-10-08: only "Laughter" in 1 s pieces gave s01 at most 0.16; the whole
    family over 3 s gives 0.48 at the same moments (a laugh is longer than 1 s and often a chuckle under speech)."""
    idx, sr = [labels.index(l) for l in LAUGHS], 32000
    pad = np.concatenate([np.zeros(sr * (window // 2), "float32"), x32, np.zeros(sr * window, "float32")])
    clips = np.stack([pad[i * sr:(i + window) * sr] for i in range(n)])                # second i in the middle
    return np.concatenate([at.inference(clips[b:b + 32])[0][:, idx].max(axis=1) for b in range(0, n, 32)])


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
    laugh = laughter(at, resample_poly(wav, 2, 1).astype("float32"), n)

    write_json(out, [{"t": i, "loudness_db": round(float(loud_db[i]), 2),
                      "laugh": round(float(laugh[i]), 3)} for i in range(n)])
