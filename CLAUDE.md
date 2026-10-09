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
- `ai_director/ingest/` probe, sync (audio cross-correlation), proxy (synced 1080p video/camN.mp4 + audio.wav; no 640px copies since 2026-10-09), run.
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
  laptop; tests/test_brain.py written, run them on the GPU PC**). Since 2026-10-08 back to `ollama.vision_model:
  qwen3-vl:4b` with `brain.english_text: false` (the original transcript). english_text: true = send the English
  `translation` (for English-only models like moondream; scene.ensure_english() translates first if missing).
- 2026-10-08 fixes: (1) `common/io.h264(q)` + `decode_on_gpu()`: NVENC (`h264_nvenc`, `-cq`) when FFmpeg can use an
  NVIDIA GPU (config `video.encoder: auto`), else libx264; ALWAYS `-pix_fmt yuv420p` — the iPhones record 10-bit HLG
  HDR and our outputs were H.264 "High 10", which browsers can't play. Used in ingest/proxy, render, render_clip,
  burn_captions. NVENC path untested (laptop has no NVIDIA GPU). (2) Captions: libass lays out every line LTR unless
  the style has `Encoding=-1` (added to FORCE_STYLE, measured) + an RLM (U+200F) in front of every Arabic line (for
  lines starting with a Latin word / speaker name). (3) Rows: `audio.segment_max_seconds: 5`, `segment_max_chars: 42`
  + split after . ? ! ؟ → one transcript row = one caption, so each caption gets its row's whole translation
  (old long rows: translation shared out by words). Existing sessions: rebuild rows from the cached Gemini answer.
  (4) translate.py: answer schema `{lines: [{n, text}]}` (no "1." in the text, rows matched by number), leading
  numbers stripped, wrong-language/missing answers asked again one by one, else "". Tests: 59 passed, 3 skipped.
- GPU PC setup: torch 2.14.1 has only `cu126` and `cu130` Windows wheels (no cu128).
  Fixes vs Eslam's files: keep_alive/think were inside options; append_jsonl didn't exist; model from configs;
  ValidationError → neutral line; tolerant resume; run.py had a hidden s01 default. translate.py: text model from
  configs, think=False, unload() at the end.
- `ai_director/agent/` (Eslam's Editor Agent: agent.py loop, tools.py 6 tools, prompts.py, search.py bge-m3 ~30 s
  pieces). **2026-10-08 (Ahmed asked; uncommitted until he says):** qwen3:8b (think=False, temp 0) copied the search
  result's times (~28 s) for "1-2 minutes" and a prompt-only fix did NOT help (tested), so the CODE now reads the
  request: new `agent/asks.py` → `language()` (by words; Franco = ar), `asked_length()` ("1-2 minutes" → (60,120),
  دقيقة/دقيقتين/دقيقة ونص/نص دقيقة, "1.20"/"1:20 minutes" and "1 minute 20 seconds"/"دقيقة و20 ثانية" = 80 s; "1.5" =
  90 s), `asked_captions()` (en/ar/ar+en/none from words near caption/subtitle/ترجمة), `title_problem()`. make_clip has
  a new `seconds` arg (B): the code sets end = start + length (LLM's seconds used only inside the typed range, or when
  a length word exists the code can't read; invented seconds ignored), then sentence edges (≈ +0–5 s). Captions:
  typed > LLM (only if a caption word) > default **English request → ar+en, Arabic → ar**. Bad titles (Chinese
  letters, wrong language, copied from the transcript) → error, the LLM rewrites (max 2), then the first words said.
  Wrong-language / Chinese answer → asked once more, then CJK stripped. typed_times() skips "1:20 minutes" (a length).
  **Contract change: clips.json items have `captions`** (schemas.Clip, optional, None = older clip; mock c1 = "none")
  → tell the team (Ahmed Sameh's web app). agent_eval --no-render: 14/15 → 15/15, lengths right, 0 wrong-language
  replies (before 2/15). Not yet: a real render of the new code on s01.
  **Who to show + how much (2026-10-08, Ahmed approved):** `asks.read_focus()` = ONE small qwen3:8b JSON question
  (FocusWish: person, level not_asked/only/mostly/more, share if typed) before the agent loop (chat(read=...); the
  real reader only with the real LLM, tests pass a fake). Tested: 23/24 + 9/10 new sentences (miss: a person who is
  only the topic gets shown). It MUST use the agent's num_ctx (other options = Ollama reloads the model, 4 s per
  switch; measured). Told to qwen in the rules (`prompts.focus_line`); nobody asked → the agent's own focus_speaker is
  dropped; agent forgot the id → `Job.person(role/name)`. Level → % of the clip on that camera
  (`agent.focus_share` only 100 / mostly 75 / more 60): 100 = that close-up only; less = `tools.boosted_shots()`: the
  director's decide() with that camera boosted, trying `agent.boosts` 1.2…3.0 until the share is reached (else the
  closest + a note). The SAME boost gives different shares per clip (s01/s02 ×2 = 59–82%) and tops out at ~65–85%
  (15 s variety rule + wide), so the LLM picks the level and the code finds the boost. `render_clip(source=[shots])`
  cuts every shot from its own camera in ONE FFmpeg run (9:16: crop_x = {cam: face_x}). Real s01 test: "mostly the
  guest, 1.20 minutes" → 82.4 s, ×1.8, guest 75% / hosts 17% / wide 8%, 16 shots, rendered in 3–4 s, frames checked.
  agent_eval --no-render 15/15, 12.6 s per request (+0.9 s for the reader).
  Open agent items (told Ahmed, not done): "اعمل ريل…وركز على الضيف" (one reel) makes 3 clips (already in the first
  baseline, #5) and the answer sometimes lists clips that were never made (search moments) → idea: the code writes
  the clip list in the reply, the LLM one friendly line, and clips = 1 unless the user asks for more;
  follow-ups ("make it vertical/longer") have no list_clips rule and "longer/أطول" isn't a length; no Ollama timeout
  (Client default None); agent_eval doesn't check length/language/captions/focus share; replies say SPEAKER_01 not
  "Islam (the guest)" and use MSA; two web requests at once can reuse a clip id; "minute 5 / الدقيقة 5" times;
  "rendered" label in test mode; restyle_video still uses a fixed ×1.4 (could use the same level → share search);
  s03 speaker_map.json puts all 4 speakers on camera 3 (check Sara's perception output).
- **Perception / director / brain / voices fixes (2026-10-08, Ahmed approved; tested in scratch first on s01–s03):**
  True speaker→camera maps checked on frames: s01 {00:2, 01:3, 02:2, 03:3 (=the guest)}, s02 {00:2, 01:3, 02:2 (=Salma)},
  s03 {00:3 man in black, 01:2 standing presenter/host, 02:2 the woman (speakers.json wrongly names her "Ahmed"),
  03: unknown 3 s}. Cameras: s01 cam2 = host (woman) + man in grey (SPEAKER_02); s03 cam2 = presenter + woman.
  (1) perception reads `video/camN.mp4` (720p): faces on the 720p frame (the separately compressed 640 px copy lost
  faces), pose + quality on a 640 px copy in memory. (2) `people.py` = yolo11s-pose (`data/models/yolo11s-pose.pt`):
  gesture = wrist movement relative to the person's own box/height (walking ≠ gesture). (3) `speaker.speaker_map` =
  "lift": camera whose mouth moves MORE THAN USUAL while that speaker talks (face-found rows); old rule gave all s03
  speakers to cam3 (8 % of speech right) → lift 100 % on s01–s03. (4) `add_transcript_talk`: speaker_prob =
  max(mouth, transcript(diarization+map)); max beat 50/50 average and 70/30. (5) scorer `no_face_size: 0.33`: a person
  whose face isn't found still counts for the speaker term. Scratch result (true map): speaker coverage s01 79.8→86.2 %,
  s02 75.8→88.5 %, s03 46.3→85.4 %; listener-on-screen 17–43 % → 6–10 %; shots ~5–8 s, no cuts < 2 s. Rejected: "every
  face" (listeners' mouths: worse), YOLO11m (YOLO only feeds gesture; removing it changed 1–3 % of s01/s02), standing →
  demo modes (Ahmed: no standing modes). Cost: perception +7–8 % (s01 480→513 s compute on the RTX 4060).
  (6) brain: new PROMPT describing what each mode LOOKS like (demo = shows/points at laptop/screen/object; standing alone
  = conversation) + tiles 640x360 from the 720p videos (`brain.tile`). Old prompt: "conversation" 337/339; a test
  version got 19/20 on s03 moments. (7) voices: `merge_extra_voices` (one-request path in asr.py + `python -m
  ai_director.audio.voices <session>` for existing sessions): more labels than upload num_speakers → smallest label
  joins its closest voice only if WavLM cosine ≥ `audio.merge_voice` 0.95 (same person 0.98; two different men
  0.89–0.93; a 6 s label of the same woman only 0.37 → a lower threshold would join different people). Applied: s01
  SPEAKER_03 → SPEAKER_01; s02/s03 unchanged. The old `same_voice` 0.75 is only used in 1-minute pieces mode.
  "One label = 2 people" could not be detected reliably (voices or cameras) → not done.
  2026-10-08 ~22:28 Ahmed DELETED everything in s01–s03 except raw/ + upload.json (backups too) to run the whole
  pipeline from zero himself (cmd: the 3 pipeline commands chained with &&). Before that: outputs from perception on were DELETED in
  s01–s03 (Ahmed stopped my pipeline run: he runs it himself).
  CORRECTION: "the 640 px copy lost faces" was most likely MediaPipe tracking luck: its face detector is close-range,
  finds a face in only ~10 % of single s03 frames at either size; with tracking (VIDEO mode) the share depends on when
  it first locks on (same 30 s of s03 cam2: 13 % vs 65 %). The lift map + transcript did the real work.
- **Perception: head crops, per-person map, cameras at once (2026-10-09, Ahmed asked; code + tests, real-video test into a
  scratch copy only — Ahmed re-runs from perception on himself).** Ahmed's fresh run (2026-10-08/09) took perception
  1030/768/940 s, AI Brain 1619/1339/2484 s (s01/s02/s03). (1) `run.py`: the cameras run at the same time, each in its own
  process (`perception.workers: 3`); 60 s of s01: one after another 97.7 s, 3 at once 37.0 s, numbers 100 % identical.
  Each frame decoded ONCE by OpenCV at 1080p, shrunk once to 640 px (pose + quality; the old extra 720p shrink cost
  ~9 ms/sample). A GPU-decode FFmpeg pipe was tested and dropped: at full 1080p it was slower (104.6 s; converting +
  piping 6 MB frames costs 8.5 ms vs OpenCV's 3.4 ms). Unreadable video → clear FileNotFoundError (was 0 rows).
  (2) `faces.py`: the landmarker's face detector squeezes the WHOLE frame to 128x128 (read from the .tflite: detector
  128x128, landmarks 256x256), so a panel-distance head became ~12 px. Now `head_box()` (pose nose/eyes/ears × 2.4, else
  the top of the box, min 64 px) → `cut_square()` from the FULL frame (black fill at the edge, never stretched) → 256x256
  → landmarker IMAGE mode, 1 face (no tracking luck); mouth_motion per person (track id). Close-up faces found: s01
  99/99 → 100/100 %, s02 58/96 → 100/100 %, s03 22/91 → 100/100 %. `perception.face_roles: [closeup]`: faces on the
  wide camera (found 88–99 %) made the wide shot win too often (s03 coverage 78.0 → 72.9 %, wide 12 → 21 %), so the wide
  camera keeps NO_FACE (as before: 0 % found). (3) `speaker.person_map()`: the lift per PERSON (camera + track id, ≥ 20
  face samples on and off) → speaker_map.json (same contract {speaker: cam}; speakers it doesn't know → the camera-level
  lift). s03: the woman + SPEAKER_03 → camera 2 (map 87.9 → 100 % of speech; all sessions 100 %); also prints where each
  person sits (s01 cam2: host x 0.80, man in grey x 0.18; s03 cam2: presenter 0.23, woman 0.77). (4)
  `speaker.follow_talker()`: on a camera with two people, while a mapped speaker talks the camera's face numbers are THAT
  person's (was the biggest face = often the listener): camera 2's face is the talker's s01 SPEAKER_02 14 → 99 %, s03
  SPEAKER_02 34 → 93 % → the 9:16 crop (face_x) follows the talker. Full runs (scratch copy, real videos): perception
  313 / 197 / 308 s (was 1030 / 768 / 940 s). Speaker coverage vs Ahmed's run 87.3/89.4/75.2 % → 86.6/88.5/78.2 %.
  (5) scorer.py (Ahmed approved, APPLIED): a found small face (s03 median face_area 0.016 → size 0.11) scored LESS than
  "no face found" (no_face_size 0.33), so finding faces lowered s03 camera 2. Now "someone on camera → size at least
  0.33" (`(face_area / face_full).clip(lower=no_face_size)` where num_people > 0 or a face; nobody → 0). On our footage
  almost every close-up face is < 5 % of the frame, so in practice size = 0.33 for all close-ups (only big faces get
  more). Speaker coverage 87.0 / 92.1 / 85.9 % (Ahmed's run 87.3 / 89.4 / 75.2), listener on screen s02 9.0 → 5.8 %, s03
  12.5 → 3.3 %. Rejected alternative: face_full 0.05 (87.9 / 91.8 / 85.7 %, but tuned on all 3 sessions). The mock
  (make_mock.py line 272) uses the same rule; only mock scores.parquet + timeline.json changed (rebuilt in scratch,
  every other mock file's content identical).
  The 640 copies (`camN_640.mp4`) were REMOVED 2026-10-09 (Ahmed asked; see "640px copies removed" below).
  Split-camera idea (2 virtual close-ups from a 2-person camera, 1.1–1.3× zoom)
  was explained to Ahmed, not built.
- **Captions / laughter / 1080p / translation (2026-10-08, Ahmed approved, code + tests only, not re-run):**
  (1) `subtitles.caption_items`: pieces → `join_tiny` (a piece < 1 s within 0.5 s of its neighbour joins it, max 2
  people → "- " dialogue lines, ≤ 42 chars per speaker line) → `absorb_flashes` (a caption the next one would cut off
  in < 0.7 s joins the next) → every caption ends where the next starts. Result s01–s03: max 1 caption at once (was
  up to 5), max 4 lines (2 people × 2 languages), none shown < 0.7 s. (2) `translate.batch_prompt`: one conversation,
  2 rows before/after as context, Egyptian English-in-Arabic-letters hint (موديل = model…); `translate_one` gets the
  neighbours; `python -m ai_director.audio.translate <session> --again`. Real test: s03 terms partly better ("Yousers"
  → "users"; "اي بي اي" still wrong), s01 idioms unchanged ("فاضيين" = "Empty") — qwen3:8b is the limit (idea: Gemini
  Flash-Lite for translation). (3) events.py `laughter()`: all laughter classes (Laughter, Giggle, Snicker, Belly laugh,
  Chuckle, Baby laughter), 3 s window centred on each second: s01 0.16 → 0.48 (294–296, 359–360 s ≥ 0.25); s02/s03
  ≤ 0.04 (the model hears no laughter there — still waiting for Ahmed's timestamps). (4) brain/modes.py: audio laughter
  ≥ `brain.laugh` 0.25 in the 5 s → "reaction"; the VLM's "laughter" counts only with audio ≥ `brain.laugh_agree` 0.1
  around it; no audio_events.json → VLM alone (old behaviour). (5) 1080p: `ingest.render_height: 1080`,
  `python -m ai_director.ingest.proxy <session>` remakes the synced copies with the same offsets (audio.wav kept:
  tested on a mock copy, same md5); render_clip's 9:16 crop follows the source (1080 → 608 px strip → 1080x1920;
  720 → 404 → 720x1280); perception decodes 1080p (since 2026-10-09: faces from head crops, see above).
  (6) s03 "only Arabic": all 857 words in Arabic letters, English terms
  spelled in Arabic (Gemini told `language_codes: [ar-EG]`). Tested one minute with [ar-EG, en-US] and with [] (auto):
  both WORSE (they drop the English terms; 101 / 91 words vs 103) → kept ar-EG, fixed downstream in the translation.
- **English words in Arabic speech (2026-10-09, Ahmed asked; code + tests, real runs only in scratch).** Gemini 3.5
  Transcribe (ar-EG) DROPS many English words (s03 "اسمه ___ هنستخدمه", "هنضطر نرجع ل ___") and writes others in Arabic
  letters ("ايكورسي"); ar-EG + en-US or auto dropped even more. New `audio/english_words.py` (audio stage step 3/7,
  never blocks the stage; CLI `python -m ai_director.audio.english_words <session>`): Arabic sessions only, rows in
  ~60 s windows (`audio.english_words_window`) + 2 nearby lines of context each side, `gemini-3.5-flash`
  (`audio.english_words_model`, null = off) gets the window's audio + numbered draft lines and returns each line
  corrected. MINIMAL-correction prompt: a first "write what is said" prompt rewrote 12-15 % of the Arabic words and moved
  words to neighbouring lines (s01 3:40); the strict one kept the Arabic (s01 3:00-4:00: only "salary" added). Rows,
  times, speakers unchanged; a changed row gets its words spread evenly over its time and translation "" (translated
  again). `plausible()`: an answer keeping < half of the draft's 3+-letter Arabic words is ignored (slid line). Answers
  cached in tmp/gemini_words_*.json (key: model + prompt), the Transcribe rows in tmp/transcript_asr.json (re-run = same
  result, free). Requests: 180 s timeout; gemini.BUSY now also has "timed out"/"Timeout". Mixed Arabic+English captions
  render in the right order (frames checked, RLM + Encoding=-1). Ahmed confirmed s03 3:00-3:20 says LLM, VLM, Qwen,
  accuracy, GPT. s03: English words 0 → ~150. Tests: tests/test_english_words.py (7).
  OPEN: (1) FREE TIER = 20 gemini-3.5-flash requests per day per key ("GenerateRequestsPerDayPerProjectPerModel-
  FreeTier", limit 20); a session = ~10 windows → 2 keys ≈ 4 sessions/day; key 1 was used up on 2026-10-09 by the tests.
  Ideas: bigger windows (3 min → ~4 requests/session; alignment not tested yet) or gemini-3.5-flash-lite (own quota;
  strict prompt on s03 3:00-4:00: Qwen, GPT, accuracy, users, agent, merge, topic, but missed LLM/VLM, target, models,
  clip). (2) Names at a window edge: s03 3:08 "Qwen" was heard as "Cohere" whenever the audio started at 3:07-3:08 (even
  with 2 context lines); runs starting at 3:00 (after "LLM و VLM") heard Qwen 5/5 → idea: optional `keywords` in
  upload.json (contract change, web app) given to the prompt. Not re-run on s01-s03 yet (s03 9/10 windows done in scratch).
- **Gemini for translation + fallback for English words (2026-10-09, Ahmed asked; tests with a FAKE Gemini only — Ahmed:
  no Gemini requests until he adds keys).** (1) translate.py `Translator`: `audio.translate_model: gemini-3.1-flash-lite`
  first (same batch_prompt, temperature 0.2, 120 s timeout), and when Gemini can't be used (no key / daily limit / no
  internet) qwen3:8b for the REST of the session (unload only if qwen was used). Tested before in scratch on s01 + s03
  (same prompt, qwen's translations from Ahmed's run): Gemini better on 19 of 37 sample lines, qwen on 1, rest equal;
  qwen errors: "البني ادمين" → "admins", "المدارس الفنيه" → "art schools", "اي بي اي" → "AI", "فاضيين" → "Empty";
  0 missing lines, s01 132 s / 26 requests, s03 63 s / 19. (2) english_words: `english_words_fallback:
  gemini-3.1-flash-lite` when 3.5-flash fails (quota); after the first failure the other windows go straight to the
  fallback; saved answers of either model are reused. Free-tier limits measured on Ahmed's keys: gemini-3.5-flash 20
  requests/day PER PROJECT (each of his 2 keys is its own project: ~35 requests before both ran out); 3.1-flash-lite not
  reached after ~35/key. Google: limits are per project, shown on aistudio.google.com/rate-limit.
- **AI Brain findings (2026-10-09, measured, nothing changed yet):** 13.4 / 13.8 / 20.5 s per moment (121 moments) because
  `qwen3-vl:4b` in Ollama IS `qwen3-vl:4b-thinking` (same digest 1343d82ebee3): it reasons 550-2,800 hidden tokens per
  moment (think=False and "/no_think" are ignored; Ollama 0.35.1); reading the picture takes only 0.7 s, the grid 0.2-0.9 s;
  the JSON itself ~40 tokens. Some answers hit the 4096 context. Fix idea: `qwen3-vl:4b-instruct` (3.3 GB, not pulled:
  ask Ahmed) → ~1.5-2 s per moment. ACCURACY (26 moments labelled by eye BEFORE reading the answers, demo answers
  over-sampled): 17/26; conversation 13/13, reaction 1/1, demo 2/11 right — a laptop lying on the table = "demo" (s03),
  and s02 has NO laptop but got "demo" 3x because people TALK about an app (the text drives it). demo mode = wide ×1.3,
  close-ups ×0.9 → s03's 29 demo moments push wide shots. moondream is not installed here (English only, 1.8B).
  A stricter demo prompt ("a laptop lying on the table / talking about an app is NOT demo") on the same 26: 18/26 (fixed
  4 false demos incl. all 3 of s02, made 3 new ones) → not applied. Ideas told Ahmed: demo from code (yolo11s laptop box
  + pose wrist on it / someone standing at it), a yes/no question, a ~60-moment labelled brain test set.
- **Also 2026-10-09:** highlight picks + titles: `highlights.title_model: gemini-3.1-flash-lite` (select.default_ask,
  1 request per session; qwen if Gemini can't be used); shared helper `audio/gemini.ask_json()` (translation uses it
  too). Ahmed: NO `keywords` field. program.mp4 size test (30 s of s01 cam2 / cam1 encoded like render, NVENC p4,
  VMAF vs the camera video): cq 20 (now) 77/56 MB per min, VMAF 98.1/97.6; cq 23 −30 % size, 97.6/97.2; cq 26 −58 %,
  96.3/95.9; cq 28 −70 %, 95.1/94.9; preset p7 = no gain; a face crop looked the same at 20/26/28. Ahmed chose 26:
  NEW `video.quality` in configs {program: 26 (was 20), clips: 21, cameras: 22, proxy: 26} read by `common/io.quality()`
  (render_program, burn_captions → program; render_clip → clips; ingest proxy → cameras/proxy). Tests: 126 passed.
  `qwen3-vl:4b-instruct` test BLOCKED: C: was 100 % full (0 bytes free of 465 GB; Ollama: "There is not enough space on
  the disk"). Freed 4.5 GB (the failed partial download + Claude's own scratch files) → 3.8 GB free; project ≈ 45 GB
  (data 21, Ollama 9, .venv 5, pip cache 4.3, Temp 3.5, HF 2.3). Ahmed then freed space (18 GB free).
- **qwen3-vl:4b-instruct TESTED (2026-10-09, pulled; NOT switched yet — waiting for Ahmed):** 1.0-2.0 s per moment
  (~57 answer tokens, no hidden thinking) vs 13-20 s → AI Brain ≈ 3-4 min per session instead of 22-41. 26 hand-labelled
  moments: current prompt 24/26 (never says demo: 0 false, 2 real missed), stricter demo prompt 24/26 (both real demos
  caught, 2 false). ALL 339 moments of s01-s03: no false demo in s01/s02 with either prompt (thinking model: 3 in s02);
  s03 demo: thinking 45 (≈2/11 right), instruct current prompt 7 (5 right, most real ones missed), instruct stricter
  prompt 20 (checked by eye: 7 clear + 5 likely right, 8 wrong; isolated ones are dropped by smooth_modes). Reactions:
  current prompt 4 (1 right), stricter prompt 1 (the real s01 1:25 laugh). APPLIED (Ahmed approved): `ollama.vision_model:
  qwen3-vl:4b-instruct` + the stricter demo rule in brain/scene.py PROMPT (Eslam's file: tell him). Real stage on a
  scratch copy of s03: 254 s (was 2484 s); raw demo 19, final 11 (7 right: 100-110, 210-215, 395-400 s; wrong 20-25,
  480-485 s). The old `qwen3-vl:4b` (thinking) can be removed from Ollama (`ollama rm qwen3-vl:4b`, 3.3 GB) if Ahmed wants.
- **Editor Agent fixes (2026-10-09, Ahmed asked; tests with a fake LLM; real eval NOT redone yet — the first try ran
  while Ahmed's s03 pipeline (AI Brain) used the GPU: 12/15, 37 s per request because Ollama swapped qwen3:8b and
  qwen3-vl; redo `python -m eval.agent_eval --no-render` when the GPU is free).** (1) The CODE writes the clip list
  under the answer (`agent.clip_lines/final_reply`): title (id): seconds, format, captions, who is shown; the LLM's text
  is cut to its first sentence before any list line / .mp4 / link (`tidy`). Number of clips: `asks.asked_count` ("3
  clips", "two reels", "كليبين" -> n; plural without a number -> up to agent.max_clips; else 1) — "اعمل ريل" made 3
  clips before. (2) Names: `asks.people_labels` (name in the reply's letters, else role "the guest"/"الضيف", numbered
  when two share it "panelist 1", else "speaker N"; "Islam" in an Arabic reply became "الإسلام" → role) +
  `name_people` replaces SPEAKER_xx / drops "(SPEAKER_xx)"; the prompt shows "-> label" per person. (3) Follow-ups:
  the prompt lists earlier clips (`tools.previous_clips`: last 5 clips + highlights); a make_clip that overlaps an
  earlier clip by more than half (`Job.earlier`) is allowed without a search; `asks.length_change` ("longer" x1.5 /
  "shorter" /1.5, at least 10 s; "30 seconds longer", "زود 20 ثانية", "أطول بنص دقيقة" -> +/- that) in clip_length.
  Format read by the code too (`asks.asked_format`: TikTok/reel/Shorts/story/عمودي/ريل -> 9:16, YouTube/16:9/أفقي ->
  16:9; else the earlier clip's format, else 16:9) — "Make a short clip" had become 9:16. (4) `search.ollama_client()`:
  one Ollama client with `agent.timeout: 120` s (chat, focus reader, bge-m3 search); a timeout -> "the AI model took
  longer than 120 seconds" reply. Tests: 7 new in test_agent.py; whole suite 133 passed. The LLM-only length reader was
  tested 2026-10-08 (16/20 vs the code 19-20/20) -> lengths stay code-first (the LLM's seconds only for words the code
  can't read).
  **Real eval after Ahmed's fresh s01-s03 pipeline run (2026-10-09, GPU free, --no-render, results in scratch only):**
  first 11/15: told "1 clip", qwen searched with top_k=1 (took the first hit) and "the user asked for 1 clip" made it
  restyle the video for "خلي الفيديو أحسن". Fixes: search_transcript returns at least 5 moments; prompt line "Clips to
  make for this request: at most 1 clip (none if the request is unclear)" / "exactly N" / "up to 3"; restyle_video
  with no person the user asked for (focus reader) and mode null/conversation (no "conversation/حوار/كلام" in the
  message) -> error "ask ONE short question" (qwen also invented "focus on the guest"; a prompt-only change flipped
  the Arabic case but not the English one). -> **13/15, 13.0 s per request**, 1 clip each, correct code-written lists.
  Still failing (moment choice, the search's top hit is next to the right one): #4 (Franco, private universities:
  picked 64-91 s, also about private universities; expected 3-60) and #14 (s03 subscription/profit: picked 359-387 s
  "60 percent profit", the discussion is 271-353). Both passed before only because 3 clips were made.
  **Grow the moment (Ahmed asked, APPLIED):** `search.topic()`: a found 30 s piece grows over its neighbours whose score is
  at most `agent.topic_drop` 0.03 below it (the better neighbour first), up to `agent.topic_max` 90 s, never into another
  found moment; the moment's text stays the best piece's. Real eval: **15/15**, 12.9 s per request; average clip 34 ->
  40 s; share of clip time inside the expected range 76 -> 71 %, share of the expected range covered 42 -> 47 %. #4 and
  #14 now overlap the right topic but only partly (22 % / 25 % of the clip). Offline sweep (same picks): drop 0 / 0.03 /
  0.05 / 0.10 -> 12/14, 14/14, 14/14, 14/14 right moments, 76 / 76 / 72 / 63 % on topic, clips 33 / 43 / 49 / 63 s
  (tuned on the 15 eval tests: small set). Tests: whole suite 136 passed.
- **Split screen BUILT (2026-10-09, Ahmed chose: turns <= 5 s first (config), + Rule B, 16:9 only, s03 none is OK).**
  `director/split.py` (split_moments, add_splits; Rule A + mouth check, Rule B, both close-ups must show a face, moments
  < 3 s apart joined, a leftover < min_shot next to a split joins it) called at the end of `run.decide()` (so restyles
  and the agent's boosted edits get splits too). Config `split:` (enabled, order [3, 2] = left/right: the cam3 person
  looks right, the cam2 people left, turn_max 5.0, min_turns 3, min_seconds 4, max_gap 2, mouth_check, laugh 0.25,
  react_pad 1, join_gap 3, line 4). YAML gotcha: a key named `on` is read as True -> `enabled`. **Contract change
  (optional fields, tell Ahmed Sameh): cuts.json shot + `split: [left, right]`, `split_x: [face x, face x]`; `cam` =
  the camera of the person talking most** (older readers just see cam). Each half = half-width crop around that
  camera's face WHILE ITS person talks (`face_at`: s01 cam2 man in grey 0.17-0.20, host 0.77-0.82). render_program:
  split shot = 2 inputs, `split_filter()` crop+hstack+dark line, same size -> concat copy works. render_clip shot lists:
  split kept in 16:9, main camera in 9:16. vertical_source: a 9:16 strip of the AI edit over a split -> shot list from
  each main camera. director_eval speaker coverage counts the second half. Scratch copies (real data): s01 12 splits
  138 s (23 %), speaker coverage 91.3 %; s02 6 splits 70 s (15 %), 95.0 %; s03 0; no cut < 2 s; s01 program rendered
  (120 s, 602.6 s, 1920x1080), frames checked (people face each other, right cam2 person, captions readable).
  Ahmed's real sessions NOT re-run (director.run + director.render; highlights again = 1 Gemini request each).
  Mock: 1 split 37-41 s (its laugh) changed 2 test numbers (agent 64 -> 68 %, tuning 0.85/0.258 -> 0.867/0.425);
  mock cuts.json (hand-written) unchanged. tests/test_split.py (9). Whole suite 145 passed.
  **9:16 clips do NOT follow the face** (one crop per camera for the whole clip, at the main talker's face).
  Measured (every 30 s window + highlights): one person per camera -> face outside the strip 0-0.2 % (s02; the s03
  presenter only moves x 0.18-0.30); the losses are on 2-person cameras: the strip stays on the main talker, so the
  OTHER person on that camera is not seen when they talk (s01 h3 190-227 s: man in grey talks 11.5 of 37 s off-strip).
  **Switching strip BUILT (2026-10-09, Ahmed asked):** `highlights/clips.people_x()` = where each person sits on
  their camera (the camera's face_x while THAT person talks, whole session, >= 2 s of faces; s01 cam2 host 0.773, man
  in grey 0.186; s03 cam2 0.234 / 0.761 / 0.778; s02 cam2 0.534 / 0.57 = fit together). `strip_shots()`: on a camera
  whose people are > FIT 0.25 apart (the strip is 0.32 of the width) the 9:16 strip cuts to whoever on that camera
  talks; pieces < switcher.min_shot (2 s) join the one before (a quick "yes" = no flash); nobody there talks -> it
  stays; `keep={cam: x}` = the person the user asked for stays (agent focus). Used by vertical_source (highlights +
  the agent's 9:16; one piece -> (cam, x) as before, more -> (shots, None)), the agent's focus (person's own x) and
  boosted 9:16 shots. render_clip: a shot's own "crop_x" wins over the {cam: x} dict. Real data (every 30 s window +
  highlights): talker on the strip's camera but outside the strip s01 16.8 -> 0.9 %, s03 11.3 -> 0.5 %, s02 0 -> 0;
  0.39 / 0.61 strip cuts per 30 s clip. Rendered s01 h3 + s03 h2 on scratch copies, frames checked (host -> man in
  grey at 214.9 s; man in blue -> the woman at 30.4 s). tests/test_strip.py (5). Whole suite 150 passed.
- **Report:** `reports/2026-10-09_Work_Explained.pdf` (49 pages, all of 8-9 Oct incl. the agent fixes, grow the moment,
  split screen, switching strip, 640px removal, commit plan in part 12). Built by scratch scripts (reportlab in a separate
  venv, charts with matplotlib; code excerpts read live from the project; only the mock's test pattern as video frames).
- **640px copies removed (2026-10-09, Ahmed asked "delete if not used"):** checked every reader first: perception and
  the AI Brain read camN.mp4 since 2026-10-08/09, `paths.proxy()` was never called, the web app guide never mentions
  them (only the old specs for Sara/Eslam do). Changed: ingest/proxy.py makes only camN.mp4 (+ audio.wav), configs
  lost ingest.proxy_width + video.quality.proxy (io.QUALITY too), paths.proxy() gone, check.py no longer requires
  them, debug_video.py reads camN.mp4 and shrinks to 640 px itself (tested on a mock copy), test_brain grid uses
  camN.mp4, make_mock.py stops making them. The 12 files (s01-s03 + mock, 330 MB) were moved to the Windows RECYCLE
  BIN (restorable; empty it to free the space). The mock's 3 files are tracked in Git -> they show as deleted.
  Tell the team: the contract file video/camN_640.mp4 no longer exists.
- **Split screen test (before building):**
  Scratch scripts in the session scratchpad (split/detect.py, sweep.py). Rule A = fast back-and-forth: consecutive speech
  on the same close-up camera = one camera turn; >= 3 alternating cam2/cam3 turns, each <= T s, gaps <= 2 s, >= 4 s long
  (diarization + speaker_map). Labels by Claude from the transcript lines + frames (no audio): 13 real fast exchanges, 11
  not (normal interview Q&A in s02, a 0.3 s interjection, a labelling error). + "mouth filter": drop a moment unless most
  of its turns have the talker's mouth moving more than the other close-up's (mouth agrees with the labels on 91-98 % of
  all cam2/cam3 turns). Results: T 3 s: precision 7/8 = 88 %, recall 54 %, split time s01 6 % / s02 4 %; **T 3.5 s:
  79 % / 85 %, s01 67 s (11 %), s02 44 s (9 %)**; T 5 s: 75 % / 100 %, s01 18 % / s02 13 %. s03: 0 moments at any T
  (3 of its 4 speakers are on cam2). Only 15-33 of s01's 62 (s02: 7-12 of 37) short cam2<->cam3 ping-pong shots fall
  inside a moment (most ping-pong is not fast turn-taking). Rule B (listener reacts: audio laugh >= 0.25 or the brain's
  reaction/laughter while a cam2/cam3 person talks): 4 moments, all s01 (87-90, 294-295, 298-300, 359-361 s), 4/4 right
  by eye (the other close-up person laughs/smiles); s02/s03 none (no laughter found; recall unknown). MUST for building
  it: s01 cam2 has 2 people (host x 0.80, man in grey x 0.18): the half-width crop must centre on the cam2 person IN the
  exchange (per-person face_x), the camera's median face_x showed the host in 3 of 7 moments where the man in grey talks.
- `eval/` wer.py, wer_set.json (placeholder references). The old Whisper bake-off (bakeoff.py) was deleted
  2026-10-05; `audio/convert_model.py` is unused (never committed; Ahmed may delete it).
- `configs/default.yaml` (fps, sync, scorer weights, switcher rules, audio models, ollama names), modes.yaml.
- `samples/mock_s00/` fake 60 s session with EVERY contract file (+ `samples/make_mock.py`). **Never write
  outputs into it** — copy it to `data/sessions/s00` to try stages.
- `tests/` — `.venv\Scripts\python.exe -m pytest -q` → **150 passed** (2026-10-09, after head crops + per-person map + cameras at once + English words + Gemini translation,
  highlight titles, video quality config and the agent fixes).
  On this PC the checker needs `PYTHONIOENCODING=utf-8` in Git Bash (it prints ✓).
- Not in Git: `data/` (videos, sessions), `.venv`, models.

## Data (must be copied to the new PC — not in Git)
From the team Google Drive into `data/sessions/`:
- s01 (Egyptian Arabic podcast, 3 speakers, 602.63 s), s02 (English interview, 2 speakers, 481.47 s),
  s03 (Arabic+English panel, 3 speakers, 602.73 s). Each: `raw/cam1-3.mp4` (iPhone HEVC 1080p remuxed),
  `upload.json`, `session.json`, `video/camN.mp4` (the 640px copies were removed 2026-10-09), `audio.wav` (16 kHz mono, from cam1).
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
