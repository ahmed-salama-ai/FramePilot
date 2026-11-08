import shutil
import subprocess

import numpy as np
import pytest

FFMPEG = shutil.which("ffmpeg")

from ai_director.audio.bleep import (
    bleep_enabled, load_phrases, mask_text, match_tokens, match_transcript,
    mix_bleeps, normalize, pad_spans, session_phrases, soundtrack, write_bleeped_audio,
)
from ai_director.audio.subtitles import caption_items, write_all_captions
from ai_director.common.io import write_json
from ai_director.common.paths import CONFIGS
from ai_director.common.schemas import Session, Upload
from ai_director.director.render import write_ass

sf = pytest.importorskip("soundfile")

PHRASES = load_phrases(CONFIGS / "profanity.txt")


def words(*pairs):
    """('token', start, end) -> transcript word dicts."""
    return [{"w": w, "start": a, "end": b} for w, a, b in pairs]


def test_wordlist_is_plain_text_and_editable():
    text = (CONFIGS / "profanity.txt").read_text(encoding="utf-8")
    assert "damn" in text and "غبي" in text and "أهبل" in text
    phrases = load_phrases(CONFIGS / "profanity.txt")
    assert ["idiot"] in phrases and ["قليل", "الادب"] in phrases


def test_arabic_spelling_variants_normalize_together():
    assert normalize("أهبل") == normalize("اهبل") == normalize("أُهْبِل")
    assert normalize("اللذينة") == normalize("اللذينه")
    assert normalize("الأدب") == normalize("الادب")
    assert normalize("إبن") == normalize("ابن") == normalize("آبن")
    assert normalize("غبييي") == normalize("غبي")
    assert normalize("DAMN!") == normalize("damn")


def test_match_uses_word_timestamps():
    tokens = words(("hello", 1.0, 1.4), ("idiot", 1.4, 1.9), ("there", 1.9, 2.3))
    hits = match_tokens(tokens, PHRASES)
    assert len(hits) == 1
    assert hits[0]["start"] == 1.4 and hits[0]["end"] == 1.9 and hits[0]["text"] == "idiot"
    rows = [{"id": 7, "words": tokens}]
    assert match_transcript(rows, PHRASES)[0]["id"] == 7


def test_multiword_phrase_uses_first_and_last_times():
    tokens = words(("يا", 2.0, 2.2), ("ابن", 2.2, 2.5), ("اللذينة", 2.5, 3.0), ("إيه", 3.0, 3.2))
    hits = match_tokens(tokens, PHRASES)
    assert len(hits) == 1
    assert hits[0]["start"] == 2.0 and hits[0]["end"] == 3.0 and hits[0]["n"] == 3


def test_false_positives_are_not_matched():
    english = words(("the", 0, 0.2), ("class", 0.2, 0.6), ("assessment", 0.6, 1.2), ("passed", 1.2, 1.5))
    arabic = words(("في", 0, 0.2), ("عكس", 0.2, 0.6), ("الاتجاه", 0.6, 1.1))
    assert match_tokens(english, PHRASES) == []
    assert match_tokens(arabic, PHRASES) == []
    assert mask_text("the class assessment passed", PHRASES) == "the class assessment passed"


# Each entry is spelled differently from configs/profanity.txt and must still be found through the real
# matcher (word timings) and masked in captions.
ARABIC_SPELLING_VARIANTS = [
    ("أهبل", "alef with hamza above"),
    ("ٱهبل", "alef wasla"),
    ("إبن اللذينة", "alef with hamza below, ta marbuta"),
    ("آبن اللذينه", "alef madda, ha for ta marbuta"),
    ("غَبِيّ", "diacritics and shadda"),
    ("قَلِيلُ الأَدَب", "diacritics across a phrase"),
    ("قليل الإدب", "wrong hamza inside a phrase"),
    ("تافة", "ta marbuta written for a final ha"),
    ("غبى", "alef maqsura for a final ya"),
    ("غـبـي", "tatweel"),
    ("حمـار", "tatweel in a longer word"),
    ("غبيييي", "stretched final letter"),
    ("سخيييف", "stretched middle letter"),
    ("يا ابن اللذينة", "three-word phrase"),
]


# Listed base words with an attached start or a feminine/plural ending.
ARABIC_WORD_FORMS = [
    ("الغبي", "definite article"),
    ("والغبي", "and + article"),
    ("بالغبي", "with + article"),
    ("للغبي", "to + article"),
    ("ياغبي", "ya written joined"),
    ("وحمار", "and"),
    ("غبية", "feminine ta marbuta"),
    ("الغبية", "article + feminine"),
    ("فاشلين", "plural -een"),
    ("غبيات", "plural -aat"),
    ("يا فاشلة", "feminine inside a phrase"),
    ("قليلة الأدب", "feminine first word of a phrase"),
    ("وابن اللذينة", "and + phrase"),
]

# Egyptian sound changes are listed as their own lines in configs/profanity.txt.
EGYPTIAN_LISTED_SPELLINGS = [
    ("أليل الأدب", "qaf said as hamza"),
    ("ابن اللزينة", "thal said as zay"),
    ("يا ابن اللزينة", "thal said as zay, three words"),
]


@pytest.mark.parametrize("variant", [v for v, _ in ARABIC_SPELLING_VARIANTS + ARABIC_WORD_FORMS
                                     + EGYPTIAN_LISTED_SPELLINGS],
                         ids=[why for _, why in ARABIC_SPELLING_VARIANTS + ARABIC_WORD_FORMS
                              + EGYPTIAN_LISTED_SPELLINGS])
def test_arabic_spelling_variant_is_bleeped_and_masked(variant):
    parts = variant.split()
    spoken = words(("قال", 0.0, 0.4), *[(w, 0.5 + i * 0.5, 0.9 + i * 0.5) for i, w in enumerate(parts)],
                   ("امبارح", 3.0, 3.6))
    hits = match_tokens(spoken, PHRASES)
    assert len(hits) == 1
    assert hits[0]["start"] == 0.5 and hits[0]["end"] == 0.9 + (len(parts) - 1) * 0.5
    assert hits[0]["n"] == len(parts)
    masked = mask_text(f"قال {variant} امبارح", PHRASES).split()
    assert masked[0] == "قال" and masked[-1] == "امبارح"
    assert all(set(w) == {"*"} for w in masked[1:-1])


def test_arabic_spelling_variants_cover_the_brief():
    assert len(ARABIC_SPELLING_VARIANTS) >= 10


@pytest.mark.parametrize("sentence", [
    # parts of listed phrases on their own, and ordinary words that look like listed ones
    "يا ابني الأدب العربي فيه قليل من الفشل لكن صوته رخيم وفي تفاهم",
    # names and words that start with ال / و / ب / يا or end with ين / ات / ه but are not listed words
    "ياسر وياسمين في الحمام والرخام عليه غبار بيتين عربيات وقليل حمارنا سخافة بالأدب الابن ابنه بابا",
], ids=["phrase parts and look-alikes", "attached starts and endings on normal words"])
def test_arabic_everyday_words_near_the_list_are_not_bleeped(sentence):
    spoken = words(*[(w, i * 0.4, i * 0.4 + 0.35) for i, w in enumerate(sentence.split())])
    assert match_tokens(spoken, PHRASES) == []
    assert mask_text(sentence, PHRASES) == sentence


def test_pad_spans_adds_margin():
    padded = pad_spans([{"start": 1.0, "end": 1.2}], pad=0.07, duration=10)
    assert padded == [(0.93, 1.27)]


def test_schemas_default_bleep_off():
    up = Upload(name="x", language="ar", wide_cam=1)
    sess = Session(id="s00", duration=1, language="ar", reference_cam=1,
                   cameras=[{"id": 1, "role": "wide", "offset": 0}])
    assert up.bleep_profanity is False and sess.bleep_profanity is False


def session_with_swear(tmp_path, on=True, language="ar"):
    rows = [{
        "id": 0, "start": 1.0, "end": 3.0, "speaker": "SPEAKER_00",
        "text": "ده أهبل يا معلم", "translation": "that is damn rude",
        "words": words(("ده", 1.0, 1.4), ("أهبل", 1.4, 2.0), ("يا", 2.0, 2.3), ("معلم", 2.3, 3.0)),
    }]
    write_json(tmp_path / "session.json", {
        "id": "t", "fps": 30, "duration": 5.0, "language": language, "reference_cam": 1,
        "cameras": [{"id": 1, "role": "wide", "offset": 0.0}],
        "bleep_profanity": on,
    })
    write_json(tmp_path / "upload.json", {
        "name": "t", "language": language, "wide_cam": 1, "bleep_profanity": on,
    })
    write_json(tmp_path / "transcript.json", rows)
    return tmp_path


def test_captions_mask_when_on_and_keep_words_when_off(tmp_path):
    s = session_with_swear(tmp_path, on=True)
    write_all_captions(s)
    srt_ar = (s / "captions_ar.srt").read_text(encoding="utf-8")
    srt_en = (s / "captions_en.srt").read_text(encoding="utf-8")
    vtt = (s / "captions.vtt").read_text(encoding="utf-8")
    assert "أهبل" not in srt_ar
    assert "ده **** يا معلم" in srt_ar
    assert "damn" not in srt_en.lower() and "****" in srt_en
    assert "أهبل" not in vtt and "damn" not in vtt.lower()
    items = caption_items(s, "ar")
    spoken = items[0]["lines"][0]["words"]
    assert spoken[1]["w"] == "****" and spoken[1]["start"] == 1.4 and spoken[1]["end"] == 2.0

    s2 = tmp_path / "off"
    s2.mkdir()
    session_with_swear(s2, on=False)
    write_all_captions(s2)
    assert "أهبل" in (s2 / "captions_ar.srt").read_text(encoding="utf-8")
    assert not bleep_enabled(s2)


def test_words_typed_at_upload_are_added_to_the_list(tmp_path):
    s = session_with_swear(tmp_path, on=True)
    write_json(s / "upload.json", {"name": "t", "language": "ar", "wide_cam": 1, "bleep_profanity": True,
                                   "bleep_words": ["مُعَلِّم", "قليل الأدب"]})
    phrases = session_phrases(s)
    assert ["معلم"] in phrases and ["idiot"] in phrases                  # typed words + the standard list
    assert phrases.count(["قليل", "الادب"]) == 1                          # already listed: not twice
    write_all_captions(s)
    assert "ده **** يا ****" in (s / "captions_ar.srt").read_text(encoding="utf-8")   # أهبل + the typed معلم


def test_the_soundtrack_bleeps_the_typed_words_too(tmp_path, monkeypatch):
    s = session_with_swear(tmp_path, on=True)
    write_json(s / "upload.json", {"name": "t", "language": "ar", "wide_cam": 1, "bleep_profanity": True,
                                   "bleep_words": ["معلم"]})
    (s / "audio.wav").write_bytes(b"x")
    mixed = []
    monkeypatch.setattr("ai_director.audio.bleep.media_duration", lambda p: 5.0)
    monkeypatch.setattr("ai_director.audio.bleep.mix_bleeps", lambda src, dst, spans: mixed.append(spans) or dst)
    write_bleeped_audio(s)
    assert mixed == [[(1.33, 2.07), (2.23, 3.07)]]                       # أهبل (the list) and معلم (typed)


def test_typed_words_change_nothing_when_bleeping_is_off(tmp_path):
    s = session_with_swear(tmp_path, on=False)
    write_json(s / "upload.json", {"name": "t", "language": "ar", "wide_cam": 1, "bleep_profanity": False,
                                   "bleep_words": ["معلم"]})
    write_all_captions(s)
    assert "ده أهبل يا معلم" in (s / "captions_ar.srt").read_text(encoding="utf-8")


def test_burned_in_ass_masks_the_same_words(tmp_path):
    s = session_with_swear(tmp_path, on=True)
    path = s / "tmp" / "t.ass"
    path.parent.mkdir(exist_ok=True)
    write_ass(s, path, langs="ar+en")
    text = path.read_text(encoding="utf-8-sig")
    assert "أهبل" not in text and "damn" not in text.lower()
    assert "***" in text


def test_mix_graph_mutes_speech_and_adds_a_sine(tmp_path, monkeypatch):
    cmds = []

    def fake_run(cmd, cwd=None):
        cmds.append([str(c) for c in cmd])
        return ""

    monkeypatch.setattr("ai_director.audio.bleep.run", fake_run)
    monkeypatch.setattr("ai_director.audio.bleep.media_duration", lambda p: 2.0)
    src, dst = tmp_path / "in.wav", tmp_path / "out.wav"
    src.write_bytes(b"x")
    mix_bleeps(src, dst, [(0.5, 0.8)], hz=1000)
    graph = cmds[0][cmds[0].index("-filter_complex") + 1]
    assert "sine=f=1000" in graph
    assert "between(t,0.5000,0.5200)" in graph and "between(t,0.7800,0.8000)" in graph   # 20 ms fades
    assert "volume=eval=frame:volume='max(0,1-(" in graph                                  # speech fades too
    assert graph.count("asetnsamples=n=48") == 2                                            # 1 ms steps


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not on PATH")
def test_ffmpeg_bleep_edges_do_not_click_or_leak(tmp_path):
    # a steady 440 Hz "voice"; the span does not start or end on an ffmpeg audio frame edge
    src, dst = tmp_path / "in.wav", tmp_path / "out.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=3:r=48000",
                    "-ac", "2", src], check=True)
    a, b = 1.013, 1.517
    mix_bleeps(src, dst, [(a, b)], hz=1000)
    y, sr = sf.read(str(dst))
    y = y[:, 0]

    def level(t0, t1, hz):
        x = y[int(t0 * sr):int(t1 * sr)]
        t = np.arange(len(x)) / sr
        return 2 * abs(np.mean(x * np.exp(-2j * np.pi * hz * t)))

    voice, beep = level(0.2, 0.9, 440), level(a + 0.05, b - 0.05, 1000)
    # a click is a jump between two samples bigger than the two clean tones can make together
    clean_jump = 2 * np.pi * (440 * voice + 1000 * beep) / sr
    assert np.abs(np.diff(y)).max() < 1.1 * clean_jump
    # once the 20 ms fade is over, nothing of the voice is left (below -40 dB)
    assert level(a + 0.02, b - 0.02, 440) < voice * 0.01
    # and the voice is back at full level after the span
    assert level(b + 0.02, 2.9, 440) > voice * 0.95


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not on PATH")
def test_ffmpeg_bleep_replaces_the_span(tmp_path):
    src = tmp_path / "in.wav"
    dst = tmp_path / "out.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=2:r=16000",
                    "-ac", "1", src], check=True)
    mix_bleeps(src, dst, [(0.8, 1.2)], hz=1000)
    audio, sr = sf.read(str(dst))
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    def rms(a, b):
        x = audio[int(a * sr):int(b * sr)]
        return float(np.sqrt(np.mean(x ** 2)))

    def peak_hz(a, b):
        x = audio[int(a * sr):int(b * sr)]
        spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        return float(np.fft.rfftfreq(len(x), 1 / sr)[int(np.argmax(spec))])

    assert rms(0.2, 0.5) > 0.05
    assert rms(0.9, 1.1) > 0.05
    assert abs(peak_hz(0.2, 0.5) - 440) < 40
    assert abs(peak_hz(0.9, 1.1) - 1000) < 60


def test_off_skips_mix_and_keeps_camera_audio(tmp_path):
    s = session_with_swear(tmp_path, on=False)
    assert write_bleeped_audio(s) is None
    assert not (s / "audio_bleeped.wav").exists()
    assert soundtrack(s) == "video/cam1.mp4"


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is not on PATH")
def test_on_writes_bleeped_soundtrack(tmp_path):
    s = session_with_swear(tmp_path, on=True)
    (s / "video").mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=3:r=30",
                    "-f", "lavfi", "-i", "sine=f=440:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", s / "video" / "cam1.mp4"], check=True)
    assert write_bleeped_audio(s)
    assert (s / "audio_bleeped.wav").exists()
    assert soundtrack(s) == "audio_bleeped.wav"


def test_ingest_copies_the_flag():
    from ai_director.ingest import run as ingest
    src = ingest.__file__
    text = open(src, encoding="utf-8").read()
    assert "bleep_profanity" in text
