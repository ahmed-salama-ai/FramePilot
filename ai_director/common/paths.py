# ai_director/common/paths.py — file names inside a session folder (Architecture §4).
# These names are a contract: change one only after telling the team.
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]     # repo root
CONFIGS = ROOT / "configs"
SESSIONS = ROOT / "data" / "sessions"
MOCK = ROOT / "samples" / "mock_s00"

UPLOAD = "upload.json"              # W  web app
SESSION = "session.json"            # ①  ingest
AUDIO = "audio.wav"                 # ①
SPEECH = "speech.json"              # ③  audio
DIARIZATION = "diarization.json"    # ③
TRANSCRIPT = "transcript.json"      # ③
SPEAKERS = "speakers.json"          # ③  who is each speaker (host, guest, ...)
CAPTIONS_AR = "captions_ar.srt"     # ③
CAPTIONS_EN = "captions_en.srt"     # ③
CAPTIONS_VTT = "captions.vtt"       # ③
AUDIO_EVENTS = "audio_events.json"  # ③  done file of the audio stage
FEATURES = "features.parquet"       # ②  perception
SPEAKER_MAP = "speaker_map.json"    # ②  done file of the perception stage
SCENE = "scene.jsonl"               # ④  AI brain
SCORES = "scores.parquet"           # ⑤  director
CUTS = "cuts.json"                  # ⑤
TIMELINE = "timeline.json"          # ⑤
PROGRAM_NOCAPS = "program_nocaps.mp4"  # ⑥ render
PROGRAM = "program.mp4"             # ⑥
HIGHLIGHTS = "highlights.json"      # ⑦  highlights
CLIPS = "clips.json"                # ⑨  editor agent
SEARCH_INDEX = "search_index.npy"   # ⑨  the agent's search cache
LABELS = "labels.csv"               # W  labelling tool
HIGHLIGHT_LABELS = "highlight_labels.csv"  # W
METRICS = "metrics.json"            # ⑧  evaluation


def raw(cam): return f"raw/cam{cam}.mp4"
def video(cam): return f"video/cam{cam}.mp4"        # synced 1080p (every stage reads it; no 640px copy since 2026-10-09)
