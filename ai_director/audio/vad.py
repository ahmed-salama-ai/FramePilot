# audio/vad.py  (Day 3) -> speech.json
from pathlib import Path
from silero_vad import load_silero_vad, read_audio, get_speech_timestamps
from ..common.io import write_json


def run_vad(s: Path):
    out = s / "speech.json"
    if out.exists():
        return
    wav = read_audio(str(s / "audio.wav"), sampling_rate=16000)
    speech = get_speech_timestamps(
        wav, load_silero_vad(), sampling_rate=16000,
        return_seconds=True, min_silence_duration_ms=300,
    )
    write_json(out, [{"start": x["start"], "end": x["end"]} for x in speech])
