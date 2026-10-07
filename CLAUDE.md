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
- `ai_director/audio/` Nada's code, taken over by Ahmed: vad.py (Silero; reads audio with soundfile, so no
  torchaudio/torchcodec needed) · asr.py (**Gemini 3.5 Transcribe**: text +
  word times + speakers → transcript.json + diarization.json) · speakers.py (roles → speakers.json) · gemini.py
  (API keys) · voices.py (same voice across pieces) · translate.py · subtitles.py · events.py · run.py. pyannote/diarize.py was removed.
- `ai_director/perception/` (Sara's part, Ahmed built it 2026-10-06) · `ai_director/pipeline.py` (Day 7; an OPTIONAL stage
  that fails is only a warning) · `director/render.py render_clip()` (Day 8).
- `ai_director/brain/` (Eslam's AI Brain, added + fixed by Ahmed 2026-10-07, **NOT run/tested yet: no GPU on the
  laptop; tests/test_brain.py written, run them on the GPU PC**). For now `ollama.vision_model: moondream` (testing;
  planned qwen3-vl:4b) and `brain.english_text: true`: Arabic sessions send the English `translation` of the
  transcript (scene.ensure_english() runs audio/translate.py + captions again if translations are missing).
  Fixes vs Eslam's files: keep_alive/think were inside options; append_jsonl didn't exist; model from configs;
  ValidationError → neutral line; tolerant resume; run.py had a hidden s01 default. translate.py: text model from
  configs, think=False, unload() at the end.
- `eval/` wer.py, wer_set.json (placeholder references). The old Whisper bake-off (bakeoff.py) was deleted
  2026-10-05; `audio/convert_model.py` is unused (never committed; Ahmed may delete it).
- `configs/default.yaml` (fps, sync, scorer weights, switcher rules, audio models, ollama names), modes.yaml.
- `samples/mock_s00/` fake 60 s session with EVERY contract file (+ `samples/make_mock.py`). **Never write
  outputs into it** — copy it to `data/sessions/s00` to try stages.
- `tests/` — `.venv\Scripts\python.exe -m pytest -q` → **35 passed** (2026-10-05).
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
- Audio — **decided 2026-10-05: Gemini 3.5 Transcribe** (see "Audio" below); first real run on s01–s03 still to do.
- Next in the plan: Day 7 `ai_director/pipeline.py` (stages as subprocesses, skip if done file exists;
  STAGES table in Ahmed's guide p.8) · Day 8 `render_clip()` (guide p.8; `make_cuts` already exists) +
  first full run on s01 · Day 9 full runs s02/s03 · Day 10 `eval/director_eval.py` · Day 11 tuning
  (tune on s01+s02, report on s03) · Day 12 freeze · Days 13–14 A/B viewer test.

## Audio — DECIDED (2026-10-05): Gemini 3.5 Transcribe, no Whisper, no pyannote
- After the Colab bake-offs (notebooks parts 1–8) Ahmed chose **`gemini-3.5-transcribe`** (Google cloud) for
  speech-to-text AND diarization. One request (Interactions API, `client.interactions.create`, audio uploaded with
  the Files API, `transcription_config: {language_codes: [ar-EG], mode: {type: verbatim, diarization_mode: speaker,
  timestamp_granularities: [word]}}`) returns `word_info` items (text, start_offset "1.23s", end_offset, speaker
  "spk_1"). Original audio.wav, **no filter**. **Default `chunk_seconds: 0` = the FULL session in one request** (Ahmed, 2026-10-05;
  max 30 min; keys only take over when one is busy). Optional pieces mode (`chunk_seconds:
  60`), each cut in the speech.json silence nearest the minute mark (±`cut_search_seconds` 10, else quietest 50 ms),
  shared between ALL keys in parallel (ThreadPoolExecutor, one worker per key, piece k starts at key k % n).
  Gemini labels speakers per piece, so `voices.py` joins them: WavLM x-vector (`microsoft/wavlm-base-plus-sv`) per
  (piece, speaker), Hungarian one-to-one match to known voices, new voice if cosine < `same_voice` 0.75 and fewer
  than num_speakers. **The real WavLM model path is untested** (tests use fake fingerprints).
  custom_vocabulary cannot be combined with diarization/word times (so no hint words now). Free tier unknown.
- `asr.py` → transcript.json (rows split at speaker change / pause >1 s / 15 s) + diarization.json (built from the
  word speakers, SPEAKER_00… by first appearance); raw answer cached in `tmp/gemini_asr_000.json` (re-run = free).
- `speakers.py` → **new contract file `speakers.json`** [{speaker, role (host/co-host/guest/interviewer/
  interviewee/moderator/panelist/presenter/audience/other), name, description}] from `gemini-3.1-flash-lite`
  reading the transcript (schemas.SpeakerInfo, paths.SPEAKERS, check.py, mock). Tell the team (contract change).
- Secrets in **`.env`** (repo root, git-ignored; template `.env.example`), read by `common/env.load_env()`
  (a Windows env var wins): HF_TOKEN and ANY number of keys GEMINI_API_KEY, GEMINI_API_KEY_2, … (`key_names()`).
  `gemini.with_keys()` rotates on 429/busy, drops a key on a daily limit. Silero VAD still makes speech.json.
- Notebook results that led here: part 6 approach 2 (Gemini 3.1 text + pyannote) s01 0–29.4 s WER .273 / CER
  .175, 99.1% speaker agreement; part 8 `gemini35_transcribe_session.ipynb` = Gemini 3.5 alone vs + pyannote.

### History: the Whisper work (replaced, kept for the report)
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
- **Chosen Arabic model (Ahmed, 2026-10-03): `maryamas222/whisper-large-v3-egyptian-lora-v4`** — a PEFT LoRA
  adapter on openai/whisper-large-v3 (~72 h Egyptian, card reports 36.9% WER on its own test set, Egyptian
  only, ~85% male training speakers). faster-whisper cannot load a LoRA, so it is merged + converted ONCE:
  `python -m ai_director.audio.convert_model maryamas222/whisper-large-v3-egyptian-lora-v4 data/models/whisper-eg-v4`
  (`ai_director/audio/convert_model.py`; needs transformers + peft + accelerate + torch; saves
  preprocessor_config.json via WhisperFeatureExtractor because transformers 5 no longer writes it from the
  processor — without it faster-whisper would use 80 instead of 128 mel bands). Config:
  `asr_models: {ar: data/models/whisper-eg-v4, en: large-v3-turbo}`; `asr.model_path()` resolves data/... from
  the repo root and errors clearly if not converted. Mechanics tested on CPU with whisper-tiny + a dummy LoRA;
  the real large-v3 merge (≈3 GB download, ~7 GB RAM) has NOT been run yet. Still confirm it in the bake-off
  (compare with large-v3-turbo and large-v3).
- Candidate "moeshawky/faster-whisper-small-egyptian-arabic" gave output IDENTICAL to plain `small` → suspect.
- **Colab notebooks (`notebooks/`)**, all share the pipeline's exact settings and RESULTS folder on Drive:
  `egyptian_asr_colab.ipynb` (part 1: turbo, large-v3, turbo-dialectal, small-egy-codeswitch → MGB-3 WER:
  39.6 / 41.6 / 39.1 / 54.9 %), `egyptian_asr_lora.ipynb` (part 2: 3 LoRAs merged+converted + mohammedaly22
  turbo code-switch 40.2 %; needs `pip uninstall torchao` on Colab; appends to results_lora.csv),
  `egyptian_asr_final.ipynb` (part 3, the deciding test: ALL 8 local models + Gemini 3.1 Flash Lite
  (`gemini-3.1-flash-lite`), Groq whisper-large-v3/-turbo, optional Deepgram/ElevenLabs/OpenAI, on s01 0–29.4 s vs
  Ahmed's hand-typed text (embedded in the notebook; also `eval/ref_s01_0-29.4.txt`, 44 words — his "first minute"
  text really ends at 29.4 s); variants raw/clean/clean+hints/clean+chunks (~10 s pieces cut at the quietest 50 ms);
  WER, CER + an LLM "meaning" judge 0–10 (Gemini, else Groq llama-3.3-70b)). API keys only via Colab Secrets
  (GEMINI_API_KEY, GROQ_API_KEY, …) — never in cells or Git (a Deepgram key was pasted in chat on 2026-10-04: revoke).
  google-genai 2.x: keep the Client object (an inline `genai.Client(...).models...` is closed before the request).
  Part 3 result (s01 30 s, 44 words): Gemini 3.1 Flash Lite WER .295 (but invented a name), Deepgram Nova-3
  .295 with chunks (raw = only one with the names right), local best mohammedaly22 / maryamas222 LoRA / large-v3
  ≈ .50; dev-ahmedhany LoRA broken (multi-language garbage); filter helps large-v3-based models, hurts others.
  `egyptian_asr_datasets.ipynb` (part 4, the decider): those 5 finalists on ~10 min of real Egyptian datasets with
  ground truth (Casablanca-Egypt test 4 min, MGB-3 3 min, Egyptian-ASR-Test-YouTube 3 min; streamed in Colab only,
  no sessions, no noise, no training) → WER/CER, per-clip LLM judge (5 results anonymised A–E per clip, Gemini judge
  else Groq), gender split, side-by-side viewer.html. Ahmed's rule: never download datasets on his laptop (test
  with fake rows). Pandas gotcha: use df["clip"], not df.clip (a method).
  **Part 4 result (2026-10-04, 65 clips / 10.7 min, corpus WER | CER | judge meaning):** Gemini 3.1 Flash Lite
  .278 | .135 | 8.9 *without* one runaway clip (it wrote 5,399 words for 54: "أه أه أه…" → WER 3.5 with it; strict
  judge winner on 36/65 clips); Deepgram Nova-3 ar-EG .356 | .181 | 7.5 (3 empty outputs on clips < 4 s);
  large-v3 .430; maryamas222 LoRA .441 (better on women 0.385 vs men 0.452); mohammedaly22 .459 (fastest, most
  bad clips). Gemini also judged its own outputs (names hidden) — WER agrees it is best. Gemini needs a max
  output length / runaway guard and gives no word timings (Qwen3-ForcedAligner does NOT support Arabic).
  `egyptian_asr_qwen.ipynb` (part 5, not run yet; Ahmed asked not to test locally): Qwen3-8B is text-only, so it
  tests Qwen3-ASR-1.7B/0.6B-hf + oddadmix/qwen3-asr-0.6b-arabic-dialectal (transformers
  `Qwen3ASRForConditionalGeneration`, `proc.decode(..., return_format="transcription_only")`, fp16 on T4), and
  Qwen3-8B (Ollama) as a corrector of Deepgram / large-v3 / LoRA transcripts; same 65 clips (checked against
  part 4's clips.csv), one fresh judge round over all models, WER without runaway clips, viewer_all.html.
  Confidence is not comparable across models; s01/s03 WER needs the reference text.
- Do NOT commit Nada's stand-ins (`common/io.py`, `brain/llm_client.py`) — the repo has the real ones.

## Next task (guide Ahmed through it)
1. Setup on any PC (no GPU needed for audio any more): `git pull`; `uv pip install -r requirements.txt`
   (adds google-genai + transformers; faster-whisper/pyannote removed). Keys + HF token go in `.env` (repo root,
   git-ignored): GEMINI_API_KEY, GEMINI_API_KEY_2, … as many as he has. Never in code, chat or Git.
2. Per session: delete transcript.json, diarization.json, speakers.json, captions_*.srt, captions.vtt,
   audio_events.json, tmp/gemini_asr_*.json (keep speech.json) → `python -m ai_director.audio.run data/sessions/s01`
   → `python -m ai_director.common.check data/sessions/s01`. Listen to a few turns: speakers + word times (±0.3 s).
3. Tell the team: diarization.json now comes from Gemini; new file speakers.json; no HF_TOKEN needed.
4. Fill `eval/wer_set.json` (team task: 15 min Arabic, 10 min English) → `python eval/wer.py`.
5. Then continue with Day 7 (pipeline.py), in the same guide-and-PDF style.

## Conventions
- Match the existing style (short comments, `common/io.py` helpers, `run()` for FFmpeg with `cwd=session`
  and relative paths). Rounded floats in JSON. Done file written last. Add tests in `tests/` for new code.
- Commit messages like `ahmed: <what>`; only commit/push when Ahmed asks. `data/` is never committed.
- GPU budget: the team uses Lightning AI free plan (≈15 credits/month); keep GPU runs short and test on
  1-minute clips first.
