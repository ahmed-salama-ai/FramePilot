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


class SpeakerInfo(BaseModel):                 # speakers.json item: who is each speaker
    speaker: str                              # SPEAKER_00 (the same labels as transcript / diarization)
    role: str                                 # host, co-host, guest, interviewer, interviewee, moderator, ... other
    name: str = ""                            # if it is said in the recording (or given in upload.json)
    description: str = ""                     # one sentence: what this person does in the conversation


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
    cam: int                                  # the camera on air (a split shot: the camera of the person talking most)
    split: list[int] | None = None            # split screen (2026-10-09): [left camera, right camera], side by side
    split_x: list[float] | None = None        # ... where each person's face is (0..1): each half is cut around it


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
    focus_speaker: str | None = None          # the person the clip shows (SPEAKER_xx), None = the AI edit
    captions: Literal["ar", "en", "ar+en", "none"] | None = None   # caption languages in the video (None = older clip)


class EditScores(BaseModel):                  # metrics.json -> director -> ai / random / wide / human
    agreement: float | None = None            # share of time with the same camera as the human (needs labels.csv)
    speaker_coverage: float | None = None     # share of speaking time with the speaker's close-up on air
    short_cuts: int                           # shots shorter than 1 s (flicker)
    avg_shot: float                           # seconds per shot
    shots: int | None = None


class Metrics(BaseModel):                     # metrics.json (evaluation): None = not measured yet
    director: dict[str, EditScores] | None = None
    captions: dict[str, dict[str, float]] | None = None    # {"ar": {"wer": .., "cer": .., "words": ..}}
    highlights: dict[str, float] | None = None             # {"precision_at_3": .., "labels": ..}
    agent: dict[str, float] | None = None                  # {"success_rate": .., "avg_steps": .., ...}
    viewer_test: dict[str, float | None] | None = None     # {"prefer_ai": .., "answers": .., "pair1": ..}
    processing_seconds: dict[str, float] = {}              # {"Ingest + Sync": 41.2, ...}
