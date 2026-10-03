# CLAUDE.md — handoff for Claude Code (AI Director / FramePilot)

Read this first. It describes the project, how Ahmed wants to work, what is done, and what to do next.
The specs are the PDFs in `instructions/` (Team Guide, Architecture, 5 personal guides) — they are the
source of truth. Ignore the `docs/` folder.

## The user
- **Ahmed Salama**, team lead of a 5-person NTI HireReady graduation project. **Beginner programmer.**
- **Default: guide, don't do.** Explain everything step by step in simple words (define every new term),
  give exact commands/code to copy, and a "Done when …" check per step. Only edit project files or run
  pipeline commands yourself when he explicitly asks for that specific thing (e.g. "edit Nada's code").
  Reading files and running read-only checks/tests to verify his work is always fine.
- Before giving him code, **test it yourself** (scratch folder or temp dirs), then give it. Say plainly what
  was and was not tested.
- He often asks for a detailed **beginner PDF** of each day's work ("Day N Explained") to share with the
  team: cover page, contents, the full code, line-by-line tables, real numbers computed by running the code,
  tests, step-by-step instructions, what teammates need, glossary. Build with reportlab in a scratch folder
  (not the project venv), render pages to PNG and look at them before sending. Arial lacks ✓/★ (use text).
  No real people's video frames in shared PDFs (use the mock's test pattern).
- Windows + PowerShell. Python 3.12 in `.venv` (managed with `uv`). FFmpeg = gyan.dev full build.

## The project in one paragraph
AI Director auto-edits multi-camera recordings: sync cameras by audio → audio (VAD, diarization, Whisper,
translation, captions, laughter) → perception (YOLO/MediaPipe features) → AI brain (VLM scene mode) →
scorer + switcher → render program.mp4 → highlights → evaluation, plus an Ollama tool-calling Editor Agent
and a FastAPI web app. **Modules never call each other: they read/write files in one session folder**
`data/sessions/sNN/` whose names/formats are a contract (Architecture PDF §4, `ai_director/common/schemas.py`).
Every stage: `python -m ai_director.<module>.run data/sessions/s01`; it writes its "done file" LAST.

Team: Ahmed Salama (lead: ingest, director, render, pipeline, eval) · Sara Walid (perception, highlights) ·
Nada Ali (audio, captions) — Ahmed has now taken over her audio work · Ahmed Sameh (web app) ·
Eslam ElKharbotly (AI brain, Editor Agent). Repo: github.com/ahmedsa12/FramePilot.

## Repo map (what exists)
- `ai_director/common/` io.py (read/write JSON, `run()` for FFmpeg), paths.py (file names, ROOT/MOCK),
  schemas.py (Pydantic contracts), check.py (`python -m ai_director.common.check <session>`).
- `ai_director/ingest/` probe, sync (audio cross-correlation), proxy (synced 720p + 640px + audio.wav), run.
- `ai_director/director/` scorer.py (weights from configs), switcher.py (5 rules; time diffs are ROUNDED —
  fixes a float bug in the guide), run.py (decide/make_cuts/make_timeline → scores.parquet, timeline.json,
  cuts.json last), render.py (render_program + add_captions; program.mp4 is the done file), baselines.py.
- `ai_director/audio/` Nada's code, edited (see "Audio" below).
- `eval/` wer.py, bakeoff.py, wer_set.json (placeholder references).
- `configs/default.yaml` (fps, sync, scorer weights, switcher rules, audio models, ollama names), modes.yaml.
- `samples/mock_s00/` fake 60 s session with EVERY contract file (+ `samples/make_mock.py`). **Never write
  outputs into it** — copy it to `data/sessions/s00` to try stages.
- `tests/` — `.venv\Scripts\python.exe -m pytest -q` → **27 passed** at handoff (2026-10-01).
- Not in Git: `data/` (videos, sessions), `.venv`, models.

## Data (must be copied to the new PC — not in Git)
From the team Google Drive into `data/sessions/`:
- s01 (Egyptian Arabic podcast, 3 speakers, 602.63 s), s02 (English interview, 2 speakers, 481.47 s),
  s03 (Arabic+English panel, 3 speakers, 602.73 s). Each: `raw/cam1-3.mp4` (iPhone HEVC 1080p remuxed),
  `upload.json`, `session.json`, `video/camN.mp4` + `camN_640.mp4`, `audio.wav` (16 kHz mono, from cam1).
- **cam1 = wide camera = reference camera in all sessions.** Sync offsets (cam1/cam2/cam3):
  s01 0/−0.709/+0.413 · s02 0/−0.384/+0.393 · s03 0/+0.487/+1.268. Confidence ≥3.6×, drift ≤0.037 s.
- Nada's outputs per session (speech.json, diarization.json, transcript.json, captions_*.srt, captions.vtt,
  audio_events.json) were in her Drive folder `audio_outputs/sNN/`. speech.json + diarization.json are good
  (right speaker counts); the transcripts must be regenerated with the new ASR code.
- Sara's features.parquet / speaker_map.json and Eslam's scene.jsonl: **not delivered yet.**

## Status by day (Ahmed's guide)
- Day 1 ✅ repo, contracts, mock, checker · Day 2 ✅ recordings · Day 3 ✅ ingest+sync on s01–s03 (shared on
  Drive) · Day 4 ✅ scorer · Day 5 ✅ switcher + director stage · Day 6 ✅ render, baselines, timeline
  (mock: 6 shots, 85% agreement vs 45.5% random, 10% wide; frame-accurate; real s01 render ≈ 7 min on CPU).
- Audio (Nada's part) — code integrated 2026-10-01, **GPU run + bake-off still to do** (next task).
- Next in the plan: Day 7 `ai_director/pipeline.py` (stages as subprocesses, skip if done file exists;
  STAGES table in Ahmed's guide p.8) · Day 8 `render_clip()` (guide p.8; `make_cuts` already exists) +
  first full run on s01 · Day 9 full runs s02/s03 · Day 10 `eval/director_eval.py` · Day 11 tuning
  (tune on s01+s02, report on s03) · Day 12 freeze · Days 13–14 A/B viewer test.

## Audio (current work) — what was changed in Nada's code and why
Diagnosis: recordings are noisy far-field phone audio (voices only ~10–12 dB above background, rumble
<200 Hz); Whisper large-v3-turbo is weak on Egyptian → wrong/MSA words in s01, invented text in s03
("ترجمة نانسي قنقر", "اشتركوا في القناة"). English s02 was fine with the same audio.
- `configs/default.yaml → audio:` `asr_models: {ar, en}` (Whisper per session language), `clean_audio`,
  `asr_filter` = highpass+afftdn+loudnorm with **afftdn's 25 ms delay compensated** (atrim/apad; measured
  0 ms shift, same length on s01–s03). audio.wav is never changed; Whisper reads `tmp/audio_asr.wav`.
- `audio/asr.py`: hint words built from the SESSION (neutral Egyptian phrases for Arabic only + Arabic
  title + optional `keywords` + speaker names — never assume "podcast"); passed as faster-whisper
  `hotwords` (applies to every window; `initial_prompt` only affects the first window when
  condition_on_previous_text=False — checked in faster-whisper 1.2.1 source); `hallucination_silence_threshold
  =2.0`; known-hallucination filter; `split_by_speaker()` gives every word its speaker and splits segments at
  speaker changes; auto device. `transcribe()` is shared with the bake-off.
- `audio/run.py`: auto device; translation failure only warns. `audio/translate.py`: uses Eslam's
  `brain/llm_client.chat_json` if present, else a built-in Ollama stand-in.
- `eval/bakeoff.py`: `python -m eval.bakeoff <session> <start> <end> <ref.txt> <model ids…>` → WER/CER,
  invented-sentence count, seconds, for raw / clean / clean+hints.
- Tested on CPU with whisper `small`: works end to end, contract OK. **Not yet tested with large models.**
- Candidate "moeshawky/faster-whisper-small-egyptian-arabic" gave output IDENTICAL to plain `small` →
  suspect; don't use. Other candidates: `large-v3`, Arabic/Egyptian fine-tunes from Hugging Face (convert
  with `ct2-transformers-converter --model <id> --output_dir data/models/whisper-eg --quantization float16`).
- Do NOT commit Nada's stand-ins (`common/io.py`, `brain/llm_client.py`) — the repo has the real ones.

## Next task on the GPU PC (guide Ahmed through it)
1. Setup: `git pull`; `uv venv`; activate; install PyTorch with CUDA first
   (`uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128`), then
   `uv pip install -r requirements.txt`; check `python -c "import torch; print(torch.cuda.is_available())"`.
   FFmpeg (`winget install Gyan.FFmpeg`), Ollama + `ollama pull qwen3:8b`. `HF_TOKEN` env var with the two
   pyannote model pages accepted. Copy `data/sessions/s01-s03` from Drive (+ Nada's speech/diarization).
2. In each session delete only transcript.json, captions_ar.srt, captions_en.srt, captions.vtt,
   audio_events.json (keep speech.json, diarization.json) → `python -m ai_director.audio.run data/sessions/s01`.
3. Bake-off: Ahmed hand-corrects minutes 0–5 of s01 into `eval/ref_s01.txt`, then
   `python -m eval.bakeoff data/sessions/s01 0 300 eval/ref_s01.txt large-v3-turbo large-v3 [egyptian model]`.
   Winner → `configs/default.yaml audio.asr_models.ar`; if raw beats clean → `clean_audio: false`.
   Also check word timing in the captions (±0.3 s) and no invented sentences in s03.
4. Fill `eval/wer_set.json` (team task: 15 min Arabic, 10 min English) → `python eval/wer.py`.
5. Then continue with Day 7 (pipeline.py), in the same guide-and-PDF style.

## Conventions
- Match the existing style (short comments, `common/io.py` helpers, `run()` for FFmpeg with `cwd=session`
  and relative paths). Rounded floats in JSON. Done file written last. Add tests in `tests/` for new code.
- Commit messages like `ahmed: <what>`; only commit/push when Ahmed asks. `data/` is never committed.
- GPU budget: the team uses Lightning AI free plan (≈15 credits/month); keep GPU runs short and test on
  1-minute clips first.
