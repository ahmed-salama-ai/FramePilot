# tests/test_speakers.py — speakers.json (who is each speaker), WITHOUT calling Google
import shutil

from pydantic import TypeAdapter

from ai_director.audio.speakers import _Answer, _Speaker, run_speakers, speakers_prompt, transcript_text
from ai_director.common import schemas as S
from ai_director.common.io import read_json
from ai_director.common.paths import MOCK


def session(tmp_path):
    for f in ("session.json", "upload.json", "transcript.json"):
        shutil.copy(MOCK / f, tmp_path)
    return tmp_path


def test_prompt_has_labels_names_and_transcript(tmp_path):
    p = speakers_prompt(session(tmp_path), read_json(MOCK / "transcript.json"))
    assert "SPEAKER_00, SPEAKER_01" in p and "SPEAKER_00 = Host" in p
    assert "[00:01] SPEAKER_00: أهلاً بيكم في حلقة جديدة من البودكاست" in p


def test_long_transcript_is_shortened():
    rows = [{"start": i, "speaker": "SPEAKER_00", "text": "كلام " * 20} for i in range(1000)]
    assert len(transcript_text(rows, max_chars=5000)) <= 5000


def test_run_speakers(tmp_path):
    s = session(tmp_path)
    answer = _Answer(speakers=[
        _Speaker(speaker="SPEAKER_00", role="Host", name="", description="Runs the show."),
        _Speaker(speaker="SPEAKER_09", role="guest", name="x", description="not in the transcript")])
    run_speakers(s, ask=lambda prompt, model: answer)
    got = read_json(s / "speakers.json")
    TypeAdapter(list[S.SpeakerInfo]).validate_python(got)
    assert got == [
        {"speaker": "SPEAKER_00", "role": "host", "name": "Host", "description": "Runs the show."},  # name from upload
        {"speaker": "SPEAKER_01", "role": "other", "name": "Guest", "description": ""}]          # missing -> other
