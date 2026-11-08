# tests/test_styles.py — Task 2: the editing styles (configs/styles.yaml) and their checks (director/styles.py).
import json
import shutil
from pathlib import Path

import pytest
import yaml

from ai_director.common.config import job_config
from ai_director.common.io import read_json, write_json
from ai_director.common.paths import CONFIGS, MOCK
from ai_director.common.schemas import Upload
from ai_director.director.run import decide
from ai_director.director.styles import StyleError, load_styles, public_styles, resolve

GOLDEN = Path(__file__).parent / "golden" / "balanced_cuts_mock.json"
DEFAULTS = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def s(tmp_path):
    """The mock session's data files (no videos) in a temporary folder."""
    out = tmp_path / "s00"
    out.mkdir()
    for f in MOCK.iterdir():
        if f.is_file() and f.suffix in (".json", ".jsonl", ".parquet"):
            shutil.copy2(f, out / f.name)
    return out


def save_style(s, style):
    write_json(s / "upload.json", {**read_json(s / "upload.json"), "style": style})


# ---------- the presets in the file ----------

def test_every_style_in_the_file_is_valid():
    for pid, p in load_styles()["presets"].items():
        style = resolve(pid, {} if p.get("custom") else None)
        assert style["preset"] == pid and set(style["config"]) == {"switcher", "split", "scorer", "zoom", "pauses"}
        assert p["name"]["en"] and p["name"]["ar"] and p["description"]["en"] and p["description"]["ar"]


def test_normal_levels_are_todays_settings():
    levels = load_styles()["levels"]
    assert levels["sensitivity"]["normal"] == {k: DEFAULTS["switcher"][k] for k in ("margin", "hold")}
    assert levels["split"]["normal"] == {k: DEFAULTS["split"][k] for k in levels["split"]["normal"]}


def test_balanced_style_gives_todays_edit(s):
    save_style(s, resolve("balanced"))
    assert job_config(s) == DEFAULTS                                       # the same settings as before Task 2 ...
    assert decide(s)[0] == json.loads(GOLDEN.read_text(encoding="utf-8"))   # ... and the same edit


def test_more_lively_styles_cut_more(s):
    shots = {}
    for pid in ("calm", "balanced", "lively"):
        save_style(s, resolve(pid))
        shots[pid] = len(decide(s)[0])
    assert shots["calm"] <= shots["balanced"] <= shots["lively"] and shots["calm"] < shots["lively"]


# ---------- custom and the checks ----------

def test_custom_starts_from_balanced():
    style = resolve("custom", {"min_shot": 3.0, "weights": {"speaker": 4.0}})
    balanced = resolve("balanced")["choices"]
    assert style["choices"] == {**balanced, "min_shot": 3.0, "weights": {**balanced["weights"], "speaker": 4.0}}
    assert style["config"]["switcher"]["min_shot"] == 3.0


def test_a_named_style_always_uses_its_own_values():
    assert resolve("calm", {"min_shot": 1.0})["choices"] == resolve("calm")["choices"]


def test_unknown_style_is_rejected():
    with pytest.raises(StyleError) as e:
        resolve("cinematic")
    assert "cinematic" in e.value.en and e.value.ar


@pytest.mark.parametrize("choices, words", [
    ({"min_shot": 0.5}, "Shortest shot"),
    ({"min_shot": 7}, "Shortest shot"),
    ({"min_shot": "abc"}, "Shortest shot"),
    ({"max_shot": 70}, "Longest shot"),
    ({"min_shot": 5.0, "max_shot": 6.0}, "at least 2 seconds longer"),
    ({"sensitivity": "extreme"}, "sensitivity"),
    ({"split": "always"}, "Split screen"),
    ({"zooms_per_minute": 9}, "Zooms per minute"),
    ({"zooms_per_minute": 1.5}, "Zooms per minute"),
    ({"min_turn": -1}, "short replies"),
    ({"weights": {"speaker": 9}}, "Camera weights"),
    ({"reactions": "maybe"}, "Reaction shots"),
    ({"weights": {"beauty": 1}}, "Unknown setting"),
    ({"colour": "red"}, "Unknown setting"),
])
def test_invalid_custom_values_are_rejected_clearly(choices, words):
    with pytest.raises(StyleError) as e:
        resolve("custom", choices)
    assert words in e.value.en and e.value.ar


def test_no_zooms_turns_the_punch_in_off():
    assert resolve("custom", {"zooms_per_minute": 0})["config"]["zoom"]["enabled"] is False


# ---------- ignore short replies (switcher.min_turn) ----------

def test_short_replies_can_be_ignored(s):
    """SPEAKER_01 (camera 3) says a 1 s "aha" inside SPEAKER_00's (camera 2) first turn."""
    diar = read_json(s / "diarization.json")
    diar[0:1] = [{"start": 1.0, "end": 6.0, "speaker": "SPEAKER_00"},
                 {"start": 6.2, "end": 7.2, "speaker": "SPEAKER_01"},
                 {"start": 7.4, "end": 11.8, "speaker": "SPEAKER_00"}]
    write_json(s / "diarization.json", diar)
    to_cam3 = lambda cuts: [c for c in cuts if c["cam"] == 3 and c["start"] < 12]          # noqa: E731
    save_style(s, resolve("custom", {"split": "off"}))                  # the quick exchange would be a split screen
    assert to_cam3(decide(s)[0])                                         # the switcher follows the "aha"
    save_style(s, resolve("custom", {"split": "off", "min_turn": 1.5}))
    assert not to_cam3(decide(s)[0])                                     # ignored: stays on the speaker


# ---------- reaction shots (switcher.reactions) ----------

def test_reaction_shots_replace_the_wide_flash(s):
    """SPEAKER_01 (camera 3) talks 12.5-27 s; with an 8 s longest shot the director must change shot mid-turn."""
    inside = lambda cuts, cam: [c for c in cuts if 13 < c["start"] < 27 and c["cam"] == cam]   # noqa: E731
    save_style(s, resolve("custom", {"max_shot": 8.0}))
    assert inside(decide(s)[0], 1)                                   # without reactions: the wide shot
    save_style(s, resolve("custom", {"max_shot": 8.0, "reactions": True}))
    cuts = decide(s)[0]
    assert not inside(cuts, 1)                                       # with reactions: no wide shot ...
    assert inside(cuts, 2) and all(c["end"] - c["start"] < 3 for c in inside(cuts, 2))   # ... the host listening


def test_balanced_has_no_reaction_shots():
    assert resolve("balanced")["config"]["switcher"]["reactions"] is False


# ---------- remove long pauses (a checkbox next to the style; pauses.py) ----------

def with_pause(s):
    """The mock with a 3.2 s silence 11.8-15.0 s; the old mock cut list changes camera at 12.8 s (a hidden cut)."""
    for name in ("diarization.json", "speech.json"):
        items = read_json(s / name)
        for x in items:
            if abs(x["start"] - 12.5) < 0.3:
                x["start"] = 15.0
        write_json(s / name, items)
    return read_json(s / "cuts.json")


def test_pauses_stay_by_default():
    style = resolve("balanced")
    assert style["remove_pauses"] is False and style["config"]["pauses"]["cut"] is False


def test_the_box_turns_pause_trimming_on_for_any_style():
    style = resolve("calm", remove_pauses=True)
    assert style["remove_pauses"] is True and style["config"]["pauses"]["cut"] is True
    assert style["choices"] == resolve("calm")["choices"]                       # Calm stays Calm


def test_the_job_trims_pauses_only_when_the_box_is_ticked(s):
    from ai_director.director.pauses import plan_pauses
    cuts = with_pause(s)
    save_style(s, resolve("balanced"))
    assert plan_pauses(s, cuts) == []                                            # not ticked: nothing removed
    save_style(s, resolve("balanced", remove_pauses=True))
    assert plan_pauses(s, cuts) and plan_pauses(s, cuts) == plan_pauses(s, cuts, on=True)


def test_remove_pauses_must_be_on_or_off():
    with pytest.raises(StyleError) as e:
        resolve("balanced", remove_pauses="maybe")
    assert "pauses" in e.value.en and e.value.ar


# ---------- what the upload page gets, and what is saved ----------

def test_the_upload_page_gets_every_style_from_the_file():
    page = public_styles()
    assert page["default"] == "balanced"
    assert [p["id"] for p in page["presets"]] == list(load_styles()["presets"])
    calm = next(p for p in page["presets"] if p["id"] == "calm")
    assert calm["name"]["ar"] and calm["choices"]["min_shot"] == resolve("calm")["choices"]["min_shot"]
    assert page["limits"]["min_shot"] == [1.0, 6.0] and page["limits"]["gap"] == 2.0
    assert page["pauses"] == {"min_pause": DEFAULTS["pauses"]["min_pause"], "keep": DEFAULTS["pauses"]["keep"]}


def test_the_saved_style_passes_the_upload_contract():
    up = Upload.model_validate({"name": "x", "language": "ar", "wide_cam": 1,
                                "style": resolve("calm", remove_pauses=True)})
    assert up.style.preset == "calm" and up.style.config["switcher"]["min_shot"] == 4.0 and up.style.remove_pauses
