from pathlib import Path

import yaml

from ai_director.common.io import read_json
from ai_director.common.paths import CONFIGS
from ai_director.director.cards import ROLE_LABELS

RULES = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["switcher"]
LAUGH = 0.25

TEXT = {
    "speaker": ("{a} is talking ({p}% of the talk in this shot): the close-up follows the speaker",
                "المتكلم: {a} ({p}% من الكلام في اللقطة)، والكاميرا القريبة تتبع من يتكلم"),
    "laugh_reaction": ("Reaction shot: laughter while {a} talks", "لقطة رد فعل: ضحك أثناء كلام {a}"),
    "reaction": ("Reaction shot: {b} listening to {a}", "لقطة رد فعل: {b} أثناء كلام {a}"),
    "close_quiet": ("Quiet moment: {b} on screen", "لحظة هدوء: {b} على الشاشة"),
    "variety_close": ("Variety: {a}'s close-up was on for {n} s, so the director shows {b}",
                      "تنويع: لقطة {a} استمرت {n} ث، فالمخرج يعرض {b}"),
    "split_fast": ("Split screen: fast back-and-forth between {a} and {b}", "شاشة مقسومة: حوار سريع بين {a} و{b}"),
    "split_reaction": ("Split screen: {b} reacting while {a} talks", "شاشة مقسومة: رد فعل {b} أثناء كلام {a}"),
    "wide_open": ("Opening: the wide shot shows everyone", "البداية: اللقطة الواسعة تعرض الجميع"),
    "wide_quiet": ("Quiet moment: the wide shot shows everyone", "لحظة هدوء: اللقطة الواسعة تعرض الجميع"),
    "wide_many": ("Several people talk: the wide shot shows them all", "أكثر من شخص يتكلم: اللقطة الواسعة تعرض الجميع"),
    "wide_demo": ("Demo: the wide shot shows what is being shown", "عرض عملي: اللقطة الواسعة تُظهر ما يُعرض"),
    "wide_laugh": ("Laughter: the wide shot shows everyone reacting", "ضحك: اللقطة الواسعة تعرض تفاعل الجميع"),
    "wide_variety": ("Variety: the close-up was on for {n} s", "تنويع: اللقطة القريبة استمرت {n} ث"),
    "wide_nocam": ("{a} has no close-up camera: the wide shot shows them", "لا توجد كاميرا قريبة على {a}: اللقطة الواسعة"),
    "wide_safe": ("No close-up has a clearly better picture: the safe wide shot",
                  "لا توجد لقطة قريبة أوضح: اللقطة الواسعة الآمنة"),
    "other": ("Best picture at this moment (camera {c})", "أفضل صورة في هذه اللحظة (كاميرا {c})"),
}
ZOOM = {"laughter": (" + a slow push in (laughter)", " + تقريب بطيء (ضحك)"),
        "strong": (" + a slow push in (a strong moment)", " + تقريب بطيء (لحظة قوية)")}


def read(s, name, default):
    return read_json(s / name) if (s / name).exists() else default


def labels(s, lang):
    """{SPEAKER_00: name} in one language: the name if known, else the role, else "speaker N"."""
    out = {}
    for x in read(s, "speakers.json", []):
        role = ROLE_LABELS[lang].get(x.get("role", ""), "")
        out[x["speaker"]] = (x.get("name") or "").strip() or role or x["speaker"]
    return out


def talk_in(diar, a, b):
    """{speaker: seconds talked between a and b}."""
    talk = {}
    for d in diar:
        o = min(b, d["end"]) - max(a, d["start"])
        if o > 0:
            talk[d["speaker"]] = talk.get(d["speaker"], 0.0) + o
    return talk


def mode_in(scene, a, b):
    """The AI Brain's most common mode between a and b ("conversation" when unknown)."""
    modes = [x["mode"] for x in scene if a - 5 < x["t"] < b]
    return max(set(modes), key=modes.count) if modes else "conversation"


def explain(session_dir, cuts, removed=None):
    """[{start, end, cam, split, code, en, ar}] for every shot of the cut list (removed = the version's cut pauses:
    the punch-ins were chosen on the cut list fitted to them)."""
    s = Path(session_dir)
    if not cuts:
        return []
    meta = read_json(s / "session.json")
    roles = {c["id"]: c["role"] for c in meta["cameras"]}
    diar = read(s, "diarization.json", [])
    spk_cam = read(s, "speaker_map.json", {})
    laugh = {e["t"]: e.get("laugh", 0.0) for e in read(s, "audio_events.json", [])}
    scene = []
    if (s / "scene.jsonl").exists():
        import json
        scene = [json.loads(x) for x in (s / "scene.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    names = {lang: labels(s, lang) for lang in ("en", "ar")}
    splits = []
    if any(c.get("split") for c in cuts):
        try:
            from ai_director.director.split import split_moments
            splits = split_moments(s)
        except Exception:
            splits = []
    try:
        from ai_director.director.pauses import fit_cuts
        from ai_director.director.zoom import zoom_plan
        zooms = zoom_plan(s, fit_cuts(cuts, removed) if removed else cuts)
    except Exception:
        zooms = {}
    out = []
    for i, c in enumerate(cuts):
        a, b, cam = c["start"], c["end"], c["cam"]
        talk = talk_in(diar, a, b)
        total = sum(talk.values())
        top = max(talk, key=talk.get) if talk else None
        on_cam = lambda k: [p for p in spk_cam if spk_cam[p] == k]                          # noqa: E731
        laughing = max((laugh.get(t, 0.0) for t in range(int(a), int(b) + 1)), default=0.0) >= LAUGH
        prev = cuts[i - 1] if i else None
        long_prev = prev and prev["end"] - prev["start"] >= RULES["max_shot"] - 0.5
        args = {"a": top, "b": None, "p": round(100 * talk[top] / total) if top else 0, "c": cam,
                "n": round(prev["end"] - prev["start"]) if prev else 0}
        if c.get("split"):
            m = max(splits, key=lambda m: min(b, m["end"]) - max(a, m["start"]), default=None)
            side = [max(on_cam(k), key=lambda p: talk.get(p, 0), default=None) for k in c["split"]]
            talker = max((p for p in side if p), key=lambda p: talk.get(p, 0), default=top)
            other = next((p for p in side if p and p != talker), None)
            code = "split_reaction" if m and m.get("why") == "reaction" else "split_fast"
            args.update(a=talker, b=other)
        elif roles.get(cam) == "closeup":
            mine = [p for p in on_cam(cam)]
            if top in mine:
                code = "speaker"
            else:
                args["b"] = max(mine, key=lambda p: talk.get(p, 0), default=None)
                if top is None or total < 0.3 * (b - a):
                    code = "close_quiet" if args["b"] else "other"
                elif laughing:
                    code = "laugh_reaction"
                elif long_prev and prev["cam"] == spk_cam.get(top):
                    code = "variety_close"
                else:
                    code = "reaction" if args["b"] else "other"
        else:                                                                  # the wide camera
            mode = mode_in(scene, a, b)
            many = [p for p in talk if talk[p] >= 0.25 * total] if total else []
            if i == 0:
                code = "wide_open"
            elif mode == "demo":
                code = "wide_demo"
            elif laughing or mode == "reaction":
                code = "wide_laugh"
            elif total < 0.3 * (b - a):
                code = "wide_quiet"
            elif len(many) >= 2:
                code = "wide_many"
            elif long_prev:
                code = "wide_variety"
            elif top and top not in spk_cam:
                code = "wide_nocam"
            else:
                code = "wide_safe"
        item = {"start": a, "end": b, "cam": cam, "split": c.get("split"), "code": code}
        for k, lang in ((0, "en"), (1, "ar")):
            nm = lambda p: names[lang].get(p, p or "?")                         # noqa: E731
            text = TEXT[code][k].format(**{**args, "a": nm(args["a"]), "b": nm(args["b"])})
            if i in zooms:
                text += ZOOM[zooms[i]["why"]][k]
            item[lang] = text
        out.append(item)
    return out
