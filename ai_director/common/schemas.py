from typing import Literal

from pydantic import BaseModel, Field, field_validator

Mode = Literal["conversation", "reaction", "wide_energy", "demo"]

FEATURE_COLUMNS = ["t", "cam", "num_people", "face_area", "face_x", "frontalness", "mouth_motion",
                   "speaker_prob", "sharpness", "exposure_ok", "shake", "gesture_score"]


class Person(BaseModel):                      # upload.json -> people: who is in the video (typed at upload)
    name: str
    role: str = ""                            # host, guest, ... (speakers.py ROLES), "" = not given


class Upload(BaseModel):                      # upload.json (web app → ingest)
    name: str
    language: Literal["ar", "en"]
    wide_cam: int
    num_speakers: int | None = None
    speaker_names: dict[str, str] = {}        # {"SPEAKER_00": "Ahmed"}
    people: list[Person] = []                 # names typed at upload; speakers.py matches them to the
                                              # voices -> speakers.json (name_source "user") -> name cards


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
    name_source: Literal["user", "recording", ""] = ""   # "user" = typed by the user (upload or the
                                              # results page) -> a name card is shown; "recording" = heard: no card


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
    split: list[int] | None = None            # split screen : [left camera, right camera], side by side
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
    parent: str | None = None                 # the clip this one was made from ("make it longer")


class CaptionStyle(BaseModel):                # brand.json -> captions
    text_color: str = "#FFFFFF"               # "#RRGGBB"
    box_color: str = "#000000"                # the box behind the text (or the outline when box is false)
    box: bool = True                          # true = a box behind the text, false = an outline around the letters
    size: Literal["small", "medium", "large"] = "medium"
    word_color: str = "#FFD43B"               # the word being said (word-by-word captions, configs captions)

    @field_validator("text_color", "box_color", "word_color")
    @classmethod
    def hex_colour(cls, v):
        h = v.lstrip("#")
        if not (v.startswith("#") and len(h) == 6 and all(c in "0123456789abcdefABCDEF" for c in h)):
            raise ValueError(f"a colour must look like #RRGGBB, not {v!r}")
        return v.upper()


class Brand(BaseModel):                       # brand.json: the customer's look, + brand/ files
    logo: str | None = None                   # "brand/logo.png" (png with transparency, or jpg)
    logo_corner: Literal["top-left", "top-right", "bottom-left", "bottom-right"] = "top-right"
    logo_size: float = Field(0.12, ge=0.03, le=0.4)   # logo width / video width
    intro: str | None = None                  # "brand/intro.mp4": before the video (program.mp4 only)
    outro: str | None = None                  # "brand/outro.mp4": after it
    captions: CaptionStyle = CaptionStyle()
    clean_voice: bool = False                 # less noise + clearer voices in every video (configs voice)
    music: str | None = None                  # "brand/music.mp3": quiet music under the trailer only


class Chapter(BaseModel):
    start: float
    title_ar: str
    title_en: str


class Post(BaseModel):                        # a social-media post for one highlight
    highlight: str                            # "h1"
    text_ar: str
    text_en: str
    hashtags: list[str] = []


class Publish(BaseModel):                     # publish.json (highlights stage, optional)
    chapters: list[Chapter] = []              # YouTube chapters (first at 0:00; empty = fewer than 3 found)
    summary_ar: str = ""
    summary_en: str = ""
    key_points_ar: list[str] = []
    key_points_en: list[str] = []
    posts: list[Post] = []
    description_ar: str = ""                  # ready to paste: summary + chapters + hashtags
    description_en: str = ""
    article_ar: str = ""                      # a blog article about the episode (Markdown), own request
    article_en: str = ""


class TrailerMoment(BaseModel):               # trailer.json -> moments
    start: float
    end: float
    text: str = ""                            # what is said (for checking)


class Trailer(BaseModel):                     # trailer.json (highlights stage, optional): the teaser
    title_ar: str = ""                        # the episode's name on the end card ("Full episode: ...")
    title_en: str = ""
    moments: list[TrailerMoment]              # in the order they are shown
    files: dict[Literal["16:9", "9:16"], str] = {}


class Version(BaseModel):                     # versions.json item: every version of the whole video
    id: str                                   # "v1" = the pipeline's edit, "v2", "v3", ... = restyles and updates
    made_by: str                              # "pipeline", "agent" (restyle), "update" ("Update video")
    note: str = ""                            # what changed ("show the guest more")
    created: str = ""
    cuts: str                                 # "cuts.json" / "versions/v2/cuts.json" (an update shares its base's)
    nocaps: str                               # the plain edit: no captions, no brand (the caption editor's player)
    program: str                              # the finished video: captions, name cards, logo, intro, outro
    clean: str = ""                           # the same without captions ("" = not made: older versions)
    intro: float = 0.0                        # seconds before the edit starts in program / clean (cold open + intro)
    removed: list[list[float]] = []           # pauses cut out of this edit [[start, end], ...] (edit times)
    cold_open: list[float] | None = None      # [start, end] of the edit shown first (None = none)


class EditScores(BaseModel):                  # metrics.json -> director -> ai / random / wide / human
    agreement: float | None = None            # share of time with the same camera as the human (needs labels.csv)
    speaker_coverage: float | None = None     # share of speaking time with the speaker's close-up on air
    short_cuts: int                           # shots shorter than 1 s (flicker)
    avg_shot: float                           # seconds per shot
    shots: int | None = None


class Metrics(BaseModel):                     # metrics.json (evaluation): None = not measured yet
    director: dict[str, EditScores] | None = None
    highlights: dict[str, float] | None = None             # {"precision_at_3": .., "labels": ..}
    processing_seconds: dict[str, float] = {}              # {"Ingest + Sync": 41.2, ...}
