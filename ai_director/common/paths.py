from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "configs"
SESSIONS = ROOT / "data" / "sessions"
MOCK = ROOT / "samples" / "mock_s00"

UPLOAD = "upload.json"              # file from web
SESSION = "session.json"            # ingest
AUDIO = "audio.wav"                 # audio file
SPEECH = "speech.json"              # audio
DIARIZATION = "diarization.json"    # diarization
TRANSCRIPT = "transcript.json"      # transcript
SPEAKERS = "speakers.json"          # who is each speaker
CAPTIONS_AR = "captions_ar.srt"     # ar captions
CAPTIONS_EN = "captions_en.srt"     # en captions
CAPTIONS_VTT = "captions.vtt"       # captions
AUDIO_EVENTS = "audio_events.json"  # done file of the audio stage
FEATURES = "features.parquet"       # perception
SPEAKER_MAP = "speaker_map.json"    # done file of the perception stage
SCENE = "scene.jsonl"               # AI brain
SCORES = "scores.parquet"           # director
CUTS = "cuts.json"
TIMELINE = "timeline.json" 
PROGRAM_NOCAPS = "program_nocaps.mp4"  # render
PROGRAM = "program.mp4"             # final video with captions
HIGHLIGHTS = "highlights.json"      # highlights
CLIPS = "clips.json"                # editor agent
SEARCH_INDEX = "search_index.npy"   # agent search cache
LABELS = "labels.csv"               # labelling tool
HIGHLIGHT_LABELS = "highlight_labels.csv"
METRICS = "metrics.json"            # evaluation
BRAND = "brand.json"                # brand kit files in brand/
PUBLISH = "publish.json"            # chapters, summary, social posts 
VERSIONS = "versions.json"          # every version of the whole video
EXPORT = "export"                   # Premiere / DaVinci packages


def raw(cam): return f"raw/cam{cam}.mp4"
def video(cam): return f"video/cam{cam}.mp4"
