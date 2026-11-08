"""Editing styles (Task 2): the named styles in configs/styles.yaml -> the settings of ONE job.

resolve(preset, choices) checks a style and returns what the upload saves with the job (upload.json -> style):
    {"preset": "calm", "choices": {every choice}, "config": {"switcher": .., "split": .., "scorer": .., "zoom": ..}}
job_config() (common/config.py) puts `config` over default.yaml for that job. `config` holds the full values, so a
job can be made again the same way even after the styles are retuned. A named style always uses the values in the
file; only "custom" takes the user's own values (a value not given = Balanced's).
"""
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ai_director.common.config import merged
from ai_director.common.paths import CONFIGS

# The limits of every choice: checked here, and sent to the upload page so it can check them before sending.
LIMITS = {"min_shot": [1.0, 6.0], "max_shot": [5.0, 60.0], "zooms_per_minute": [0, 4], "min_turn": [0.0, 3.0],
          "weights": [0.0, 5.0], "gap": 2.0}          # gap: the longest shot is at least this much longer than the shortest
SPLIT_KEYS = ("enabled", "turn_max", "min_turns", "min_seconds", "laugh")


def _between(name):
    return Field(ge=LIMITS[name][0], le=LIMITS[name][1])


class Weights(BaseModel):                     # how much each signal counts when choosing a camera (scorer.weights)
    model_config = ConfigDict(extra="forbid")
    speaker: float = _between("weights")
    frontal: float = _between("weights")
    quality: float = _between("weights")
    gesture: float = _between("weights")
    shake: float = _between("weights")


class Choices(BaseModel):                     # one style's choices (configs/styles.yaml explains each one)
    model_config = ConfigDict(extra="forbid")
    min_shot: float = _between("min_shot")
    max_shot: float = _between("max_shot")
    sensitivity: Literal["low", "normal", "high"]
    split: Literal["off", "rarely", "normal", "often"]
    zooms_per_minute: int = _between("zooms_per_minute")
    min_turn: float = _between("min_turn")
    reactions: bool
    weights: Weights

    @model_validator(mode="after")
    def longest_after_shortest(self):
        if self.max_shot < self.min_shot + LIMITS["gap"]:
            raise ValueError("max_shot too close to min_shot")
        return self


class StyleError(ValueError):
    """A style that cannot be used. str(e) / e.en = the message for the user in English, e.ar = in Arabic."""

    def __init__(self, en, ar):
        super().__init__(en)
        self.en, self.ar = en, ar


def _messages():
    g = lambda x: f"{x:g}"                                                            # noqa: E731  4.0 -> "4"
    lo = {k: g(v[0]) for k, v in LIMITS.items() if k != "gap"}
    hi = {k: g(v[1]) for k, v in LIMITS.items() if k != "gap"}
    gap = g(LIMITS["gap"])
    return {
        "min_shot": (f"Shortest shot must be between {lo['min_shot']} and {hi['min_shot']} seconds.",
                     f"أقصر لقطة يجب أن تكون بين {lo['min_shot']} و{hi['min_shot']} ثوانٍ."),
        "max_shot": (f"Longest shot must be between {lo['max_shot']} and {hi['max_shot']} seconds.",
                     f"أطول لقطة يجب أن تكون بين {lo['max_shot']} و{hi['max_shot']} ثانية."),
        "gap": (f"The longest shot must be at least {gap} seconds longer than the shortest shot.",
                f"يجب أن تزيد أطول لقطة عن أقصر لقطة بمقدار {gap} ثانية على الأقل."),
        "sensitivity": ("Switching sensitivity must be low, normal or high.",
                        "حساسية التبديل يجب أن تكون منخفضة أو عادية أو عالية."),
        "split": ("Split screen must be off, rarely, normal or often.",
                  "الشاشة المقسومة يجب أن تكون: مغلقة أو نادرًا أو عادية أو كثيرًا."),
        "zooms_per_minute": (f"Zooms per minute must be a whole number from {lo['zooms_per_minute']} to "
                             f"{hi['zooms_per_minute']}.",
                             f"عدد التقريبات في الدقيقة يجب أن يكون رقمًا صحيحًا من {lo['zooms_per_minute']} إلى "
                             f"{hi['zooms_per_minute']}."),
        "min_turn": (f"Ignore short replies must be between {lo['min_turn']} and {hi['min_turn']} seconds.",
                     f"تجاهل الردود القصيرة يجب أن يكون بين {lo['min_turn']} و{hi['min_turn']} ثوانٍ."),
        "weights": (f"Camera weights must be between {lo['weights']} and {hi['weights']}.",
                    f"أوزان اختيار الكاميرا يجب أن تكون بين {lo['weights']} و{hi['weights']}."),
        "reactions": ("Reaction shots must be on or off.", "لقطات رد الفعل يجب أن تكون مفعّلة أو متوقفة."),
    }


def _error(e: ValidationError):
    """pydantic's errors -> one StyleError with a readable message per wrong choice."""
    msgs, out = _messages(), []
    for err in e.errors():
        loc = [str(x) for x in err["loc"]]
        if err["type"] == "extra_forbidden":
            name = ".".join(loc)
            m = (f"Unknown setting: {name}.", f"إعداد غير معروف: {name}.")
        elif not loc:
            m = msgs["gap"]
        else:
            m = msgs.get(loc[0], (f"Invalid value for {loc[0]}.", f"قيمة غير صالحة: {loc[0]}."))
        if m not in out:
            out.append(m)
    return StyleError(" ".join(en for en, _ in out), " ".join(ar for _, ar in out))


def load_styles():
    return yaml.safe_load((CONFIGS / "styles.yaml").read_text(encoding="utf-8"))


def balanced_choices(defaults):
    """Balanced = default.yaml as it is, written as choices."""
    sw, zoom = defaults["switcher"], defaults.get("zoom") or {}
    return {"min_shot": sw["min_shot"], "max_shot": sw["max_shot"], "sensitivity": "normal",
            "split": "normal" if defaults["split"]["enabled"] else "off",
            "zooms_per_minute": zoom.get("per_minute", 0) if zoom.get("enabled") else 0,
            "min_turn": sw.get("min_turn", 0.0), "reactions": bool(sw.get("reactions", False)),
            "weights": dict(defaults["scorer"]["weights"])}


def to_config(c, levels, defaults):
    """Checked choices -> the settings they change (sections of default.yaml)."""
    split = {k: defaults["split"][k] for k in SPLIT_KEYS}
    split.update(levels["split"][c.split])
    return {"switcher": {"min_shot": c.min_shot, "max_shot": c.max_shot, "min_turn": c.min_turn,
                         "reactions": c.reactions, **levels["sensitivity"][c.sensitivity]},
            "split": split,
            "scorer": {"weights": c.weights.model_dump()},
            "zoom": {"enabled": c.zooms_per_minute > 0,              # 0 = no punch-ins (per_minute 0 would still give 1)
                     "per_minute": c.zooms_per_minute or (defaults.get("zoom") or {}).get("per_minute", 2)}}


def resolve(preset, choices=None, remove_pauses=False):
    """The style saved with a job: {"preset", "choices", "remove_pauses", "config"}. remove_pauses = the "Remove long
    pauses" box next to the style (any style; not a preset choice). Raises StyleError (English + Arabic message)."""
    if not isinstance(remove_pauses, bool):
        raise StyleError("Remove long pauses must be on or off.", "حذف فترات الصمت الطويلة يجب أن يكون مفعّلًا أو متوقفًا.")
    styles = load_styles()
    defaults = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))
    p = styles["presets"].get(preset) if isinstance(preset, str) else None
    if p is None:
        raise StyleError(f"Unknown editing style: {preset}.", f"نمط مونتاج غير معروف: {preset}.")
    picked = (choices or {}) if p.get("custom") else (p.get("choices") or {})
    if not isinstance(picked, dict):
        raise StyleError("The style's values must be sent as named values.", "يجب إرسال قيم النمط بأسمائها.")
    if picked.get("split") is False:
        picked = {**picked, "split": "off"}                       # YAML reads a bare off as false
    try:
        c = Choices.model_validate(merged(balanced_choices(defaults), picked))
    except ValidationError as e:
        raise _error(e) from None
    pauses = {k: (defaults.get("pauses") or {}).get(k, v) for k, v in
              (("min_pause", 1.5), ("keep", 0.4), ("jump_cuts", False))}
    return {"preset": preset, "choices": c.model_dump(), "remove_pauses": remove_pauses,
            "config": {**to_config(c, styles["levels"], defaults), "pauses": {"cut": remove_pauses, **pauses}}}


def public_styles():
    """What the upload page needs: every style (names, descriptions, values), the default one and the limits."""
    styles = load_styles()
    presets = [{"id": pid, "name": p["name"], "description": p["description"], "custom": bool(p.get("custom")),
                "choices": resolve(pid, {} if p.get("custom") else None)["choices"]}
               for pid, p in styles["presets"].items()]
    pauses = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8")).get("pauses") or {}
    return {"default": styles.get("default", "balanced"), "presets": presets, "limits": LIMITS,
            "levels": {k: list(v) for k, v in styles["levels"].items()},
            "pauses": {"min_pause": pauses.get("min_pause", 1.5), "keep": pauses.get("keep", 0.4)}}   # box text
