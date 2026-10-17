import numpy as np
import soundfile as sf
from scipy.signal import correlate

from ai_director.common.io import run


def extract_audio(video, wav, sr=16000):
    """Video -> mono WAV at 16 kHz (first audio track only)."""
    run(["ffmpeg", "-y", "-i", video, "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(sr), wav])


def audio_offset(ref_wav, other_wav, sr=16000, seconds=60):
    """Seconds 'other' started before 'ref' (> 0: other started earlier)."""
    ref, _ = sf.read(ref_wav)
    other, _ = sf.read(other_wav)
    ref, other = ref[: sr * seconds], other[: sr * seconds]
    c = correlate(other, ref, mode="full", method="fft")
    lag = np.argmax(c) - (len(ref) - 1)
    return lag / sr