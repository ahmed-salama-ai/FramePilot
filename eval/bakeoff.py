# eval/bakeoff.py — which Whisper model + audio works best on OUR recordings?   (run on a GPU: Lightning)
#   python -m eval.bakeoff data/sessions/s01 0 300 eval/ref_s01.txt large-v3-turbo large-v3 data/models/whisper-eg
# ref_s01.txt = what was REALLY said between 0 and 300 s, typed/corrected by hand (UTF-8).
# Every model is tried 3 ways: raw audio (the old way), cleaned audio, cleaned audio + hint words.
# Owner: Nada Ali (rewritten by Ahmed Salama to use exactly the pipeline's settings)
import sys
import time
from pathlib import Path

import jiwer
import soundfile as sf

from ai_director.audio.asr import CFG, hint_words, is_hallucination, pick_device, transcribe
from ai_director.common.io import read_json, run
from eval.wer import norm_ar, norm_en


def window(path, start, end):
    x, sr = sf.read(path, dtype="float32")
    return x[int(start * sr):int(end * sr)]


if __name__ == "__main__":
    s, start, end, ref_path, *models = sys.argv[1:]
    s, start, end = Path(s), float(start), float(end)
    lang = read_json(s / "session.json")["language"]
    norm = norm_ar if lang == "ar" else norm_en
    ref = norm(Path(ref_path).read_text(encoding="utf-8"))
    (s / "tmp").mkdir(exist_ok=True)
    run(["ffmpeg", "-y", "-i", "audio.wav", "-af", CFG["asr_filter"], "-ac", "1", "-ar", "16000",
         "tmp/audio_bakeoff_clean.wav"], cwd=s)
    raw, clean = window(s / "audio.wav", start, end), window(s / "tmp/audio_bakeoff_clean.wav", start, end)
    hints = hint_words(s, lang)
    variants = [("raw", raw, None), ("clean", clean, None), ("clean+hints", clean, hints)]
    out_dir = Path("eval/bakeoff_out"); out_dir.mkdir(parents=True, exist_ok=True)

    from faster_whisper import WhisperModel
    device = pick_device()
    print(f"hint words: {hints}\n")
    print(f"{'model':38} {'audio':12} {'WER':>6} {'CER':>6} {'invented':>8} {'sec':>6}")
    for mid in models:
        model = WhisperModel(mid, device=device, compute_type="int8_float16" if device == "cuda" else "int8")
        for name, audio, hw in variants:
            t0 = time.time()
            segs = transcribe(model, audio, lang, hw)
            sec = time.time() - t0
            invented = sum(is_hallucination(x.text) for x in segs)
            text = " ".join(x.text.strip() for x in segs if not is_hallucination(x.text))
            (out_dir / f"{Path(mid).name}_{name}.txt").write_text(text, encoding="utf-8")
            hyp = norm(text)
            print(f"{mid:38} {name:12} {jiwer.wer(ref, hyp):6.3f} {jiwer.cer(ref, hyp):6.3f} {invented:8d} {sec:6.1f}")
        del model                                                     # free the GPU before the next model
    print(f"\nLowest WER wins: put its model id in configs/default.yaml -> audio.asr_models.{lang}; "
          f"if 'raw' beats 'clean', set audio.clean_audio: false. Texts saved in {out_dir}/")
