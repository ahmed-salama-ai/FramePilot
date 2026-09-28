# tests/test_sync.py — sync must find the offsets planted in the mock session
from ai_director.common.io import read_json
from ai_director.common.paths import MOCK
from ai_director.ingest.sync import audio_offset, extract_audio


def test_sync_finds_mock_offsets(tmp_path):
    cams = read_json(MOCK / "session.json")["cameras"]
    for c in cams:
        extract_audio(MOCK / f"raw/cam{c['id']}.mp4", tmp_path / f"cam{c['id']}.wav")
    for c in cams:
        found = audio_offset(tmp_path / "cam1.wav", tmp_path / f"cam{c['id']}.wav")
        assert abs(found - c["offset"]) < 0.01, (c["id"], found)