# audio/subtitles.py  (Days 6-7) - short chunks from word times, SRT / VTT, burn-in
import os
from pathlib import Path
from ..common.io import h264, quality, read_json, run

FONT = "Arial" if os.name == "nt" else "Noto Naskh Arabic"  # Linux/Colab: apt install fonts-noto-core
# Right-to-left captions need BOTH: Encoding=-1 (libass then finds each line's direction from its first letter;
# without it EVERY line is laid out left-to-right, which jumbles Arabic) and RLM, an invisible right-to-left mark
# in front of every Arabic line, so a line that starts with a Latin word or a speaker name is right-to-left too.
RLM = "\u200f"
FORCE_STYLE = (f"FontName={FONT},FontSize=15,PrimaryColour=&H00FFFFFF,BorderStyle=3,"
               "OutlineColour=&H80000000,Outline=1,Shadow=0,MarginV=30,Encoding=-1")


def ts(t, sep=","):
    ms = int(round(max(t, 0) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d}{sep}{ms:03d}"


def chunks(seg, max_chars=42, max_dur=5.0):
    out, cur = [], []
    for w in seg["words"]:
        if cur and (len(" ".join(x["w"] for x in cur + [w])) > max_chars
                    or w["end"] - cur[0]["start"] > max_dur):
            out.append(cur)
            cur = []
        cur.append(w)
    return out + [cur] if cur else out


def pieces(session_dir, langs, max_chars, max_dur):
    """Every caption-sized piece of the transcript: start, end (as spoken), speaker, and its Arabic / English text.
    Edited by Ahmed Salama (2026-10-08): a row that fits in ONE caption gets its whole translation (rows are made
    caption-sized in asr.py)."""
    meta = read_json(session_dir / "session.json")
    out = []
    for seg in read_json(session_dir / "transcript.json"):
        parts = chunks(seg, max_chars, max_dur)
        tr = seg.get("translation", "").split()
        for k, p in enumerate(parts):
            orig = " ".join(w["w"] for w in p)
            if len(parts) == 1:                                       # the usual case: the whole translation
                trans = " ".join(tr)
            else:                                                     # an old long row: share it out by words
                trans = " ".join(tr[len(tr) * k // len(parts): len(tr) * (k + 1) // len(parts)])
            ar, en = (orig, trans) if meta["language"] == "ar" else (trans, orig)
            out.append({"start": p[0]["start"], "end": p[-1]["end"], "speaker": seg["speaker"],
                        "ar": ar if "ar" in langs else "", "en": en if "en" in langs else ""})
    return sorted(out, key=lambda x: x["start"])


def fits(g, x, short, gap, max_chars, longest):
    """Can piece x join caption g? One of them is tiny, they are close, max 2 people, and it stays readable."""
    tiny = x["end"] - x["start"] < short or g["end"] - g["start"] < short
    close = x["start"] - g["end"] <= gap and x["end"] - g["start"] <= longest
    old = g["text"].get(x["speaker"], {"ar": [], "en": []})
    readable = all(len(" ".join(old[l] + [x[l]])) <= max_chars for l in ("ar", "en"))
    return tiny and close and readable and len({*g["who"], x["speaker"]}) <= 2


def join_tiny(items, short=1.0, gap=0.5, max_chars=42, longest=5.0):
    """Quick back-and-forth ("لا لا" / "ده" / "لا" / "فاضيين." in s01's argument, 0.1-0.2 s each) -> ONE caption.
    A piece joins the caption before it when one of them is shorter than `short` s, they are at most `gap` s apart
    (or overlap), at most 2 people talk in it, and it stays short enough to read."""
    groups = []
    for x in items:
        g = groups[-1] if groups else None
        if g and fits(g, x, short, gap, max_chars, longest):
            g["end"] = max(g["end"], x["end"])
        else:
            g = {"start": x["start"], "end": x["end"], "who": [], "text": {}}
            groups.append(g)
        if x["speaker"] not in g["text"]:
            g["who"].append(x["speaker"])
            g["text"][x["speaker"]] = {"ar": [], "en": []}
        for l in ("ar", "en"):
            if x[l]:
                g["text"][x["speaker"]][l].append(x[l])
    return groups


def absorb_flashes(groups, gap=0.5, min_show=0.7):
    """A short caption that the next one would push off the screen in under `min_show` s ("ليه؟" right before a long
    sentence) joins that next caption (a long line simply wraps), so nothing flashes by too fast to read."""
    out = []
    for k, g in enumerate(groups):
        nxt = groups[k + 1] if k + 1 < len(groups) else None
        if nxt and min(max(g["end"], g["start"] + 1.0), nxt["start"]) - g["start"] < min_show \
                and nxt["start"] - g["end"] <= gap and len({*g["who"], *nxt["who"]}) <= 2:
            for who in reversed(g["who"]):
                if who not in nxt["text"]:
                    nxt["who"].insert(0, who)
                    nxt["text"][who] = {"ar": [], "en": []}
                for l in ("ar", "en"):
                    nxt["text"][who][l][:0] = g["text"][who][l]
            nxt["start"] = g["start"]
            continue
        out.append(g)
    return out


def caption_items(session_dir, langs="ar+en", max_chars=42, max_dur=5.0):
    """The captions: tiny neighbouring pieces joined (two people -> "- " dialogue lines), every Arabic line starts with
    RLM (right-to-left even when it starts with a Latin word or a speaker name), and NEVER two captions at once:
    a caption shows for at least 1 s only if the next one hasn't started yet. (Before 2026-10-08 every piece was
    stretched to 1 s, the stretched pieces overlapped and libass stacked them: up to 5 captions at once in s01.)"""
    session_dir = Path(session_dir)
    meta = read_json(session_dir / "session.json")
    up = read_json(session_dir / "upload.json") if (session_dir / "upload.json").exists() else {}
    names = meta.get("speaker_names") or up.get("speaker_names") or {}
    items = []
    for g in absorb_flashes(join_tiny(pieces(session_dir, langs, max_chars, max_dur), max_chars=max_chars)):
        lines = []
        for l in ("ar", "en"):
            for who in g["who"]:
                x = " ".join(g["text"][who][l])
                if not x:
                    continue
                if l == ("ar" if "ar" in langs else "en") and who in names:   # the name on the first language only
                    x = f"{names[who]}: {x}"
                if len(g["who"]) > 1:
                    x = "- " + x
                lines.append(RLM + x if l == "ar" else x)
        if lines:
            items.append({"start": g["start"], "end": max(g["end"], g["start"] + 1.0), "text": "\n".join(lines)})
    for a, b in zip(items, items[1:]):                                 # end before the next caption starts
        a["end"] = max(min(a["end"], b["start"]), a["start"] + 0.01)
    return items


def write_srt(items, path, shift=0.0):
    Path(path).write_text(
        "\n".join(f"{i}\n{ts(x['start'] - shift)} --> {ts(x['end'] - shift)}\n{x['text']}\n"
                  for i, x in enumerate(items, 1)), encoding="utf-8")


def write_vtt(items, path):
    Path(path).write_text(
        "WEBVTT\n\n" + "\n".join(f"{ts(x['start'], '.')} --> {ts(x['end'], '.')}\n{x['text']}\n"
                                for x in items), encoding="utf-8")


def write_all_captions(session_dir):
    session_dir = Path(session_dir)
    write_srt(caption_items(session_dir, "ar"), session_dir / "captions_ar.srt")
    write_srt(caption_items(session_dir, "en"), session_dir / "captions_en.srt")
    write_vtt(caption_items(session_dir, "ar+en"), session_dir / "captions.vtt")


def write_clip_srt(session_dir, start, end, langs, path):  # used by render_clip (Ahmed Salama)
    items = [x for x in caption_items(session_dir, langs) if x["end"] > start and x["start"] < end]
    for x in items:
        x["start"], x["end"] = max(x["start"], start), min(x["end"], end)
    write_srt(items, path, shift=start)


def burn_captions(session_dir, inp="program_nocaps.mp4", out="program.mp4", langs="ar+en"):
    session_dir = Path(session_dir)
    (session_dir / "tmp").mkdir(exist_ok=True)
    write_srt(caption_items(session_dir, langs), session_dir / "tmp/program.srt")
    run(["ffmpeg", "-y", "-i", inp,
         "-vf", f"subtitles=tmp/program.srt:force_style='{FORCE_STYLE}'",
         *h264(quality("program")), "-c:a", "copy", out],
        cwd=session_dir)
