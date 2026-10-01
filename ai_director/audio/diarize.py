# audio/diarize.py  (Day 4) -> diarization.json
import os
from pathlib import Path
import torch
import soundfile as sf
from pyannote.audio import Pipeline
from ..common.io import read_json, write_json


def _annotation(d):
    """pyannote 3.x returns an Annotation; pyannote 4 returns a DiarizeOutput wrapping one."""
    if hasattr(d, "itertracks"):
        return d
    for name in ("speaker_diarization", "diarization", "annotation", "exclusive_speaker_diarization"):
        a = getattr(d, name, None)
        if a is not None and hasattr(a, "itertracks"):
            return a
    for v in getattr(d, "__dict__", {}).values():
        if hasattr(v, "itertracks"):
            return v
    raise RuntimeError(f"Unknown diarization output {type(d)}; attributes: "
                       f"{[x for x in dir(d) if not x.startswith('_')]}")


def run_diarize(s: Path):
    out = s / "diarization.json"
    if out.exists():
        return
    token = os.environ["HF_TOKEN"]  # never commit the token to Git
    try:
        pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=token)
    except TypeError:  # newer pyannote versions
        pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=token)
    if torch.cuda.is_available():
        pipe.to(torch.device("cuda"))

    # pass a waveform dict instead of a path: avoids file-loading problems on Windows
    wav, sr = sf.read(s / "audio.wav", dtype="float32")
    audio = {"waveform": torch.from_numpy(wav)[None], "sample_rate": sr}

    meta = read_json(s / "session.json")
    up = read_json(s / "upload.json") if (s / "upload.json").exists() else {}
    n = meta.get("num_speakers") or up.get("num_speakers")
    diar = pipe(audio, **({"num_speakers": n} if n else {}))
    diar = _annotation(diar)
    write_json(out, [
        {"start": round(t.start, 2), "end": round(t.end, 2), "speaker": spk}
        for t, _, spk in diar.itertracks(yield_label=True)
    ])
