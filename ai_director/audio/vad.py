# audio/vad.py  (Day 3) -> speech.json
# Edited by Ahmed Salama: the audio is read with soundfile and given to Silero as numbers, so neither torchaudio nor
# torchcodec is needed (silero-vad 6 cannot open a file without one of them).
from pathlib import Path

import soundfile as sf
import torch
from scipy.signal import resample_poly
from silero_vad import load_silero_vad, get_speech_timestamps
from ..common.io import write_json


def run_vad(s: Path):
    out = s / "speech.json"
    if out.exists():
        return
    wav, sr = sf.read(s / "audio.wav", dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    if sr != 16000:                                   # audio.wav is 16 kHz already (ingest); just in case
        wav = resample_poly(wav, 16000, sr).astype("float32")
    speech = get_speech_timestamps(
        torch.from_numpy(wav), load_silero_vad(), sampling_rate=16000,
        return_seconds=True, min_silence_duration_ms=300,
    )
    write_json(out, [{"start": x["start"], "end": x["end"]} for x in speech])
