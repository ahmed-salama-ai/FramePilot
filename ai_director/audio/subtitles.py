# audio/subtitles.py  (Days 6-7) - short chunks from word times, SRT / VTT, burn-in
import os
from pathlib import Path
from ..common.io import h264, read_json, run

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


def caption_items(session_dir, langs="ar+en", max_chars=42, max_dur=5.0):
    """Edited by Ahmed Salama (2026-10-08): a row that fits in ONE caption gets its whole translation (rows are
    made caption-sized in asr.py); every Arabic line starts with RLM so it is laid out right-to-left even when it
    starts with a Latin word or a speaker name."""
    session_dir = Path(session_dir)
    meta = read_json(session_dir / "session.json")
    up = read_json(session_dir / "upload.json") if (session_dir / "upload.json").exists() else {}
    names = meta.get("speaker_names") or up.get("speaker_names") or {}
    items = []
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
            lines = [[lang, x] for lang, x, on in (("ar", ar, "ar" in langs), ("en", en, "en" in langs)) if on and x]
            if k == 0 and lines and seg["speaker"] in names:
                lines[0][1] = f"{names[seg['speaker']]}: {lines[0][1]}"
            items.append({"start": p[0]["start"],
                          "end": max(p[-1]["end"], p[0]["start"] + 1.0),
                          "text": "\n".join(RLM + x if lang == "ar" else x for lang, x in lines)})
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
         *h264(20), "-c:a", "copy", out],
        cwd=session_dir)
