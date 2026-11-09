import re
import unicodedata
from pathlib import Path

import yaml

from ai_director.audio.bleep import HARAKAT, LETTER_MAP, normalize
from ai_director.common.paths import CONFIGS

MODES = ("off", "conservative", "standard")
GROUPS = {"hesitation": "conservative", "discourse": "standard", "never": "kept"}
CONDITIONS = {"stretched", "phrase_start", "phrase_end", "not_phrase_end", "not_turn_start", "not_after", "not_before",
              "no_pause_needed"}
PHRASE_END = re.compile(r"[.!?؟،,؛;:…]$")
DOUBLE = re.compile(r"(.)\1")


def config_path(session_dir=None):
    if session_dir:
        local = Path(session_dir) / "fillers.yaml"
        if local.exists():
            return local
    return CONFIGS / "fillers.yaml"


def load_fillers(session_dir=None):
    """The filler list in force for a session (its own fillers.yaml, else configs/fillers.yaml), checked."""
    path = config_path(session_dir)
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rule = {"max_seconds": 0.5, "pause": 0.15, "phrase_start": True, "keep_questions": True, **(cfg.get("rule") or {})}
    for group in GROUPS:
        for e in cfg.get(group) or []:
            if not isinstance(e, dict) or not e.get("words") or not all(isinstance(w, str) for w in e["words"]):
                raise ValueError(f"{path.name}: every {group} entry needs a list of words ({e!r})")
            unknown = set(e.get("only") or {}) - CONDITIONS
            if unknown:
                raise ValueError(f"{path.name}: unknown condition {', '.join(sorted(unknown))} in {e.get('id')}")
    return {**cfg, "rule": rule}


def plain(raw):
    """A written word without diacritics, tatweel or punctuation, letters folded, repeats KEPT (for `stretched`)."""
    s = unicodedata.normalize("NFC", str(raw or "")).translate(HARAKAT).replace("ـ", "").translate(LETTER_MAP)
    return re.sub(r"[^\w]+", "", s.casefold(), flags=re.UNICODE)


def squash(s):
    return re.sub(r"(.)\1+", r"\1", s)


def key(word, stretched):
    """Matching key: normalize(); a stretched entry also folds every repeat (هممم, همم -> هم)."""
    k = normalize(word)
    return squash(k) if stretched else k


def compile_entries(cfg):
    """[(group, entry, only, [phrase keys])], longest phrases first so 'يعني ايه' wins over 'يعني'."""
    out = []
    for group in GROUPS:
        for e in cfg.get(group) or []:
            only = e.get("only") or {}
            st = bool(only.get("stretched"))
            for phrase in e["words"]:
                keys = [key(w, st) for w in phrase.split()]
                if all(keys):
                    out.append((group, e, only, keys))
    return sorted(out, key=lambda x: -len(x[3]))


def tokens(rows):
    """The transcript's words in order, with where each phrase and speaker turn starts."""
    toks = []
    for r, row in enumerate(rows):
        words = [w for w in row.get("words") or [] if str(w.get("w", "")).strip()]
        for j, w in enumerate(words):
            raw = str(w["w"])
            toks.append({"w": raw, "start": float(w["start"]), "end": float(w["end"]), "row": row.get("id", r),
                         "speaker": row.get("speaker"), "first": j == 0, "last": j == len(words) - 1,
                         "norm": normalize(raw), "squash": squash(normalize(raw)),
                         "stretched": bool(DOUBLE.search(plain(raw))), "stop": bool(PHRASE_END.search(raw))})
    return toks


def _match(toks, i, entries):
    for group, e, only, keys in entries:
        n = len(keys)
        if i + n > len(toks):
            continue
        st = bool(only.get("stretched"))
        part = toks[i:i + n]
        if all((t["squash"] if st else t["norm"]) == k for t, k in zip(part, keys)) and \
                (not st or all(t["stretched"] for t in part)):
            return group, e, only, n
    return None


def find_candidates(rows, cfg=None):
    """Every listed word in the transcript: where, how long, the pauses around it, and the decision -
    "conservative" (removed in Conservative and Standard), "standard" (removed in Standard only) or "kept" - with
    the reason."""
    cfg = cfg or load_fillers()
    rule, entries, toks = cfg["rule"], compile_entries(cfg), tokens(rows)
    norm = lambda words: {normalize(w) for w in words or []}                  # noqa: E731
    out, i, after_filler = [], 0, -1          # after_filler: index of the word right after the last filler found
    while i < len(toks):
        m = _match(toks, i, entries)
        if not m:
            i += 1
            continue
        group, e, only, n = m
        a, b = toks[i], toks[i + n - 1]
        prev = toks[i - 1] if i > 0 else None
        nxt = toks[i + n] if i + n < len(toks) else None
        gap_before = round(a["start"] - prev["end"], 3) if prev else None
        gap_after = round(nxt["start"] - b["end"], 3) if nxt else None
        phrase_start = prev is None or a["first"] or prev["stop"] or i == after_filler     # "um, so ..." restarts
        phrase_end = nxt is None or b["last"] or b["stop"]
        turn_start = a["first"] and (prev is None or prev["speaker"] != a["speaker"])
        duration = round(b["end"] - a["start"], 3)
        isolated = ((gap_before is None or gap_before >= rule["pause"]) or (gap_after is None or gap_after >= rule["pause"])
                    or (rule["phrase_start"] and phrase_start))
        decision, reason = GROUPS[group], "hesitation sound" if group == "hesitation" else "short and isolated"
        checks = [
            (group == "never", "never removed: usually carries meaning"),
            (rule.get("keep_questions", True) and b["w"].rstrip().endswith(("?", "؟")),
             "a question ('يعني؟' = 'meaning?')"),
            (only.get("phrase_start") and not phrase_start, "not at the start of a phrase"),
            (only.get("phrase_end") and not phrase_end, "not at the end of a phrase"),
            (only.get("not_phrase_end") and phrase_end, "ends the sentence: adds emphasis"),
            (only.get("not_turn_start") and turn_start, "first word of a reply: probably 'yes'"),
            (prev is not None and prev["norm"] in norm(only.get("not_after")), f"after '{prev['w'] if prev else ''}'"),
            (nxt is not None and nxt["norm"] in norm(only.get("not_before")), f"before '{nxt['w'] if nxt else ''}'"),
            (group == "discourse" and duration > rule["max_seconds"] * n, "too long: said on purpose"),
            (group == "discourse" and not isolated and not only.get("no_pause_needed"),
             "inside a phrase, no pause around it"),
        ]
        for failed, why in checks:
            if failed:
                decision, reason = "kept", why
                break
        context = " ".join(t["w"] for t in toks[max(0, i - 4):i]) + " [" + " ".join(t["w"] for t in toks[i:i + n]) + "] " + \
            " ".join(t["w"] for t in toks[i + n:i + n + 4])
        out.append({"start": a["start"], "end": b["end"], "duration": duration, "text": " ".join(t["w"] for t in toks[i:i + n]),
                    "entry": e.get("id") or e["words"][0], "group": group, "decision": decision, "reason": reason,
                    "gap_before": gap_before, "gap_after": gap_after, "phrase_start": phrase_start,
                    "phrase_end": phrase_end, "turn_start": turn_start, "row": a["row"], "context": context.strip(),
                    "i": i, "n": n})
        if group != "never":
            after_filler = i + n
        i += n
    return out


def removed_in(candidates, mode):
    """The candidates a mode removes: off none, conservative the hesitations, standard hesitations + discourse."""
    if mode not in MODES:
        raise ValueError(f"Filler mode must be one of {', '.join(MODES)}.")
    keep = {"off": set(), "conservative": {"conservative"}, "standard": {"conservative", "standard"}}[mode]
    return [c for c in candidates if c["decision"] in keep]
