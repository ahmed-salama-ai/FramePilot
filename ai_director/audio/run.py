from pathlib import Path

from ..common.io import session_from_argv
from .asr import run_asr
from .english_words import fix_english_words
from .events import run_events
from .speakers import run_speakers
from .subtitles import write_all_captions
from .translate import run_translate
from .vad import run_vad


def main(s: Path, translate=True):
    print("  [1/7] speech detection (Silero VAD)");              run_vad(s)
    print("  [2/7] text + word times + speakers (Gemini 3.5)");  run_asr(s)
    print("  [3/7] English words in Arabic speech (Gemini 3.5 Flash)")
    try:
        fix_english_words(s)
    except Exception as e:
        print(f"  WARNING: English words skipped ({type(e).__name__}: {e})")
    print("  [4/7] who is each speaker")
    try:
        run_speakers(s)
    except Exception as e:
        print(f"  WARNING: speaker roles skipped ({type(e).__name__}: {e})")
    if translate:
        print("  [5/7] translation")
        try:
            run_translate(s)
        except Exception as e:
            print(f"  WARNING: translation skipped ({type(e).__name__}: {e})")
    print("  [6/7] captions");     write_all_captions(s)
    print("  [7/7] loudness + laughter"); run_events(s)

if __name__ == "__main__":
    main(session_from_argv())
