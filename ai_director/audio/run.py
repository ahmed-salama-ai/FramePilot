# ai_director/audio/run.py — stage 2: audio.wav -> speech, transcript + speakers, speaker roles, captions, events
#   python -m ai_director.audio.run data/sessions/s01
# Owner: Nada Ali (edited by Ahmed Salama: Gemini 3.5 Transcribe replaces Whisper + pyannote; speaker roles;
# translation and speaker roles never block the stage)
from pathlib import Path

from ..common.io import session_from_argv
from .asr import run_asr
from .events import run_events
from .speakers import run_speakers
from .subtitles import write_all_captions
from .translate import run_translate
from .vad import run_vad


def main(s: Path, translate=True):
    print("  [1/6] speech detection (Silero VAD)");              run_vad(s)
    print("  [2/6] text + word times + speakers (Gemini 3.5)");  run_asr(s)
    print("  [3/6] who is each speaker")
    try:
        run_speakers(s)
    except Exception as e:                           # e.g. no internet: the rest still works without speakers.json
        print(f"  WARNING: speaker roles skipped ({type(e).__name__}: {e})")
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
