import json

from ai_director.audio.subtitles import caption_items
from ai_director.director.render import write_ass


def caption_session(tmp_path):
    session = tmp_path / "session.json"
    session.write_text(json.dumps({"language": "ar", "speaker_names": {}}), encoding="utf-8")
    (tmp_path / "transcript.json").write_text(json.dumps([{
        "id": 0,
        "start": 0.1,
        "end": 1.35,
        "speaker": "SPEAKER_00",
        "text": "أنا بحب Computer Vision 3 جدًا",
        "translation": "I love Computer Vision 3 very much",
        "words": [
            {"w": "أنا", "start": 0.1, "end": 0.4},
            {"w": "بحب", "start": 0.55, "end": 0.85},
            {"w": "Computer", "start": 0.9, "end": 1.1},
            {"w": "Vision", "start": 1.15, "end": 1.3},
            {"w": "3", "start": 1.31, "end": 1.35},
        ],
    }], ensure_ascii=False), encoding="utf-8")
    (tmp_path / "brand.json").write_text(json.dumps({
        "captions": {
            "text_color": "#FFFFFF",
            "word_color": "#4A3DFF",
            "animation_style": "default",
        },
    }), encoding="utf-8")
    return tmp_path


def render_caption(session, tmp_path, style, *, vertical=False, langs="ar"):
    brand = json.loads((session / "brand.json").read_text(encoding="utf-8"))
    brand["captions"]["animation_style"] = style
    (session / "brand.json").write_text(json.dumps(brand), encoding="utf-8")
    output = tmp_path / f"{style}_{'916' if vertical else '169'}.ass"
    write_ass(session, output, langs=langs, vertical=vertical, words=False)
    return output.read_text(encoding="utf-8-sig")


def test_write_ass_pop_scales_only_the_spoken_word(tmp_path):
    session = caption_session(tmp_path)

    text = render_caption(session, tmp_path, "pop")

    assert r"\fscx100\fscy100\t(0,180,\fscx115\fscy115)" in text
    assert "Computer" in text
    assert "Vision" in text
    assert "PlayResX: 384" in text


def test_write_ass_karaoke_uses_cumulative_word_timing(tmp_path):
    session = caption_session(tmp_path)

    text = render_caption(session, tmp_path, "karaoke", langs="ar+en")

    assert "&HFF3D4A&" in text
    assert "أنا" in text
    assert "بحب" in text
    assert "Computer" in text
    assert "Vision" in text
    assert "3" in text
    assert "I love Computer Vision 3 very much" in text

    # Verify cumulative timing: earlier spoken words remain filled in the word colour
    # as each successive word is spoken.
    dialogues = [line for line in text.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogues) >= 5

    # At step 2 ("Computer" active), preceding spoken words "أنا بحب" stay highlighted
    assert r"{\1c&HFF3D4A&}أنا بحب {\r}" in dialogues[2]
    assert r"Computer" in dialogues[2]

    # At step 3 ("Vision" active), "أنا بحب Computer" stays highlighted
    assert r"{\1c&HFF3D4A&}أنا بحب Computer {\r}" in dialogues[3]
    assert r"Vision" in dialogues[3]


def test_write_ass_default_keeps_original_caption_text_and_no_animation(tmp_path):
    session = caption_session(tmp_path)
    expected = caption_items(session, "ar")[0]["text"]

    text = render_caption(session, tmp_path, "default")

    dialogue = next(line for line in text.splitlines() if line.startswith("Dialogue: 0,"))
    assert dialogue.endswith(",, " + expected) or dialogue.endswith(",," + expected)
    assert r"\kf" not in text
    assert r"\fscx" not in text


def test_write_ass_karaoke_preserves_vertical_play_resolution(tmp_path):
    session = caption_session(tmp_path)
    transcript = json.loads((session / "transcript.json").read_text(encoding="utf-8"))
    transcript[0]["translation"] = "the root cause, which is the admission system, so that the admission for"
    (session / "transcript.json").write_text(json.dumps(transcript, ensure_ascii=False), encoding="utf-8")

    text = render_caption(session, tmp_path, "karaoke", vertical=True, langs="ar+en")

    assert "PlayResX: 384" in text
    assert "PlayResY: 288" in text
    assert "&HFF3D4A&" in text
    assert "أنا" in text
    assert "the root cause" in text


def test_write_ass_karaoke_keeps_filled_words_during_long_pause(tmp_path):
    session = caption_session(tmp_path)
    transcript = json.loads((session / "transcript.json").read_text(encoding="utf-8"))
    # Introduce a 1.65s pause between word 1 ("بحب") and word 2 ("Computer")
    transcript[0]["words"][2]["start"] = 2.5
    transcript[0]["words"][2]["end"] = 2.8
    transcript[0]["words"][3]["start"] = 2.9
    transcript[0]["words"][3]["end"] = 3.2
    transcript[0]["words"][4]["start"] = 3.3
    transcript[0]["words"][4]["end"] = 3.4
    transcript[0]["end"] = 3.6
    (session / "transcript.json").write_text(json.dumps(transcript, ensure_ascii=False), encoding="utf-8")

    text = render_caption(session, tmp_path, "karaoke", langs="ar")

    dialogues = [line for line in text.splitlines() if line.startswith("Dialogue:")]
    # Event starting at 0.55 extends all the way to 2.50 across the pause
    pause_event = next(line for line in dialogues if "0:00:00.55" in line and "0:00:02.50" in line)
    assert "&HFF3D4A&" in pause_event
    assert "بحب" in pause_event
