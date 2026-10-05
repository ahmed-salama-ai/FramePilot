# tests/test_contracts.py — the mock session must always follow the file contract.  Run: pytest -q
from ai_director.common.check import check_session
from ai_director.common.io import read_json
from ai_director.common.paths import MOCK

EVERY_FILE = ["upload.json", "session.json", "audio.wav", "speech.json", "diarization.json", "transcript.json",
              "speakers.json", "captions_ar.srt", "captions_en.srt", "captions.vtt", "audio_events.json",
              "features.parquet",
              "speaker_map.json", "scene.jsonl", "scores.parquet", "cuts.json", "timeline.json",
              "program_nocaps.mp4", "program.mp4", "highlights.json", "clips.json", "labels.csv",
              "highlight_labels.csv", "metrics.json"]


def test_mock_has_every_file():
    assert [f for f in EVERY_FILE if not (MOCK / f).exists()] == []


def test_mock_follows_contract():
    assert check_session(MOCK) == []


def test_mock_raw_and_synced_videos():
    for c in read_json(MOCK / "session.json")["cameras"]:
        for f in (f"raw/cam{c['id']}.mp4", f"video/cam{c['id']}.mp4", f"video/cam{c['id']}_640.mp4"):
            assert (MOCK / f).exists(), f
