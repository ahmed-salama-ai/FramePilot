# ai_director/audio/run.py — stage 2: audio.wav -> speech, speakers, transcript, captions, events
#   python -m ai_director.audio.run data/sessions/s01
# Owner: Nada Ali (edited by Ahmed Salama: automatic device, translation never blocks the stage)
from pathlib import Path

from ..common.io import session_from_argv
from .asr import pick_device, run_asr
from .diarize import run_diarize
from .events import run_events
from .subtitles import write_all_captions
from .translate import run_translate
from .vad import run_vad


def main(s: Path, model_id=None, device=None, translate=True):
    device = device or pick_device()
    print("  device:", device)
    print("  [1/6] VAD");          run_vad(s)
    print("  [2/6] diarization");  run_diarize(s)
    print("  [3/6] Whisper ASR");  run_asr(s, model_id, device)
    if translate:
        print("  [4/6] translation")
        try:
            run_translate(s)
        except Exception as e:                       # e.g. Ollama not running: captions without translation
            print(f"  WARNING: translation skipped ({type(e).__name__}: {e})")
    print("  [5/6] captions");     write_all_captions(s)
    print("  [6/6] loudness + laughter"); run_events(s)   # audio_events.json LAST: the "done" file


if __name__ == "__main__":
    main(session_from_argv())
