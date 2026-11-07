"""Put FFmpeg on PATH before any test runs (WinGet installs often miss the current terminal)."""
from ai_director.common.io import ensure_ffmpeg_on_path

ensure_ffmpeg_on_path()
