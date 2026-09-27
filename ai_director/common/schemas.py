# ai_director/common/schemas.py — the file contracts as Pydantic models (Architecture §4).
# Use them to check a file:  Session.model_validate(read_json(s / "session.json"))
from typing import Literal

from pydantic import BaseModel, Field

Mode = Literal["conversation", "reaction", "wide_energy", "demo"]

FEATURE_COLUMNS = ["t", "cam", "num_people", "face_area", "face_x", "frontalness", "mouth_motion",
                   "speaker_prob", "sharpness", "exposure_ok", "shake", "gesture_score"]


class Upload(BaseModel):                      # upload.json (web app → ingest)
    name: str
    language: Literal["ar", "en"]
    wide_cam: int
    num_speakers: int | None = None
    speaker_names: dict[str, str] = {}        # {"SPEAKER_00": "Ahmed"}


class Camera(BaseModel):
    id: int
    role: Literal["wide", "closeup"]
    offset: float                             # seconds, vs the reference camera


class Session(BaseModel):                     # session.json (ingest)
    id: str
    fps: int = 30
    duration: float
    language: Literal["ar", "en"]
    reference_cam: int
    cameras: list[Camera]
    num_speakers: int | None = None
    speaker_names: dict[str, str] = {}


class Span(BaseModel):                        # speech.json item
    start: float
    end: float


class DiarSegment(Span):                      # diarization.json item
    speaker: str


class Word(BaseModel):
    w: str
    start: float
    end: float


class TranscriptSegment(BaseModel):           # transcript.json item
    id: int
    start: float
    end: float
    speaker: str | None
    text: str
    translation: str = ""
    words: list[Word]


class AudioEvent(BaseModel):                  # audio_events.json item (one per second)
    t: int
    loudness_db: float
    laugh: float = Field(ge=0, le=1)


class SceneLine(BaseModel):                   # scene.jsonl line (every 5 s)
    t: float
    scene: str
    event: Literal["talking", "laughter", "demo", "standing", "silence", "other"]
    energy: float = Field(ge=0, le=1)
    mode: Mode
    raw_mode: Mode | None = None
    highlight: bool


class Cut(BaseModel):                         # cuts.json item
    start: float
    end: float
    cam: int


class Timeline(BaseModel):                    # timeline.json (1 value per second)
    t: list[float]
    scores: dict[str, list[float]]            # {"1": [...], "2": [...]}
    on_air: list[int]
    mode: list[Mode]


class Highlight(BaseModel):                   # highlights.json item
    id: str
    start: float
    end: float
    title_ar: str
    title_en: str
    hook: str
    files: dict[Literal["16:9", "9:16"], str]


class Clip(BaseModel):                        # clips.json item (Editor Agent)
    id: str
    start: float
    end: float
    format: Literal["16:9", "9:16"]
    title: str = ""
    file: str
