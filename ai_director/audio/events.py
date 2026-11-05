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
PANNS_MIN_SIZE = {"class_labels_indices.csv": 1, "Cnn14_mAP=0.431.pth": 300_000_000}

def ensure_panns_files():
    """panns_inference downloads with 'wget', which Windows doesn't have, so we download the files ourselves."""
    PANNS_DIR.mkdir(exist_ok=True)
    for name, url in PANNS_FILES.items():
        path = PANNS_DIR / name
        minimum = PANNS_MIN_SIZE[name]
        if not path.exists() or path.stat().st_size < minimum:
            print(f"Downloading {name} ...")
            temporary = path.with_name(path.name + ".download")
            try:
                urllib.request.urlretrieve(url, temporary)
                size = temporary.stat().st_size
                if size < minimum:
                    raise RuntimeError(f"Incomplete PANNs download for {name}: {size} bytes (expected at least "
                                       f"{minimum}). Delete the partial download and try again.")
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)

from panns_inference import AudioTagging, labels
from ..common.io import write_json


LAUGHS = [l for l in labels if any(k in l.lower() for k in ("laugh", "giggle", "snicker", "chuckle", "chortle"))]


def laughter(at, x32, n, window=3):
    """Second t -> the strongest of ALL laughter kinds (Laughter, Giggle, Snicker, Belly laugh, Chuckle...) in the
    `window` seconds around t."""
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

    ensure_panns_files()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    at = AudioTagging(checkpoint_path=None, device=device)  # PANNs wants 32 kHz
    laugh = laughter(at, resample_poly(wav, 2, 1).astype("float32"), n)

    write_json(out, [{"t": i, "loudness_db": round(float(loud_db[i]), 2),
                      "laugh": round(float(laugh[i]), 3)} for i in range(n)])
