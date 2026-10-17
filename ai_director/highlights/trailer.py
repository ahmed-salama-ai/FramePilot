from pathlib import Path

import yaml
from pydantic import BaseModel

from ..common.io import h264, quality, read_json, run, session_from_argv, write_json
from ..common.paths import CONFIGS
from ..common.schemas import Trailer
from ..director.brand import ass_colour, load_brand, logo_overlay
from ..director.render import has_audio, render_clip
from ..ingest.probe import probe
from .interest import CFG as HCFG

CFG = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8")).get("trailer") or {}
END_WORDS = {"ar": "الحلقة كاملة", "en": "Full episode"}
ENDS = (".", "?", "!", "؟", "…")

PROMPT = """You cut a short TRAILER (a teaser) for a talk-show episode, like the ones posted before an episode comes out.
Below is the transcript, one numbered line per sentence: [n] start-end seconds, speaker: what was said (| English).
Choose {lo}-{hi} moments. A moment = one line or a few lines in a row (first and last line number), {plo}-{phi} seconds
long; all moments together {slo}-{shi} seconds. Each moment must make sense on its own (never half a sentence, never
"and then he...") and make people curious: a strong opinion, a surprising fact, a funny line, a big question. Don't
give away the ending. Take them from different parts of the episode. Put them in the order that works best for a
trailer: a hook first, the strongest or funniest last.
Also give the episode a short catchy name (2-6 words) in Egyptian Arabic (title_ar) and in English (title_en).
Episode: {title}.

Transcript:
{lines}
"""


class _Moment(BaseModel):
    first: int
    last: int


class Answer(BaseModel):
    moments: list[_Moment]
    title_ar: str
    title_en: str


def numbered(rows, language):
    return "\n".join(f"[{n}] {r['start']:.1f}-{r['end']:.1f} {r['speaker']}: {r['text']}"
                     + (f" | {r['translation']}" if language == "ar" and r.get("translation") else "")
                     for n, r in enumerate(rows))


def ends_sentence(row):
    return row["text"].strip().endswith(ENDS)


def fit(rows, i, j, lo, hi):
    """Lines i..j made trailer-length: lines dropped from the end while too long, the next line added while too
    short (and it still fits); then, if it stops in the middle of a sentence, the nearest sentence end that still
    fits (a transcript line ends after 5 s or 42 letters, often mid-sentence). (start, end) or None."""
    while j > i and rows[j]["end"] - rows[i]["start"] > hi:
        j -= 1
    while rows[j]["end"] - rows[i]["start"] < lo and j + 1 < len(rows) and rows[j + 1]["end"] - rows[i]["start"] <= hi:
        j += 1
    if not ends_sentence(rows[j]):
        ok = [k for k in range(i, len(rows)) if rows[k]["end"] - rows[i]["start"] <= hi + 0.5
              and rows[k]["end"] - rows[i]["start"] >= lo - 0.5 and ends_sentence(rows[k])]
        if ok:
            j = min(ok, key=lambda k: abs(k - j))
    a, b = rows[i]["start"], rows[j]["end"]
    return (round(a, 2), round(b, 2)) if lo - 0.5 <= b - a <= hi + 0.5 else None


def pick(rows, pairs):
    """The model's (first, last) pairs -> moments in its order: valid lines, trailer-length, not overlapping each other,
    together at most trailer.seconds[1] s, at most trailer.moments[1] of them."""
    (plo, phi), (_, shi), (_, mhi) = CFG["piece"], CFG["seconds"], CFG["moments"]
    out, total = [], 0.0
    for i, j in pairs:
        if not (0 <= i <= j < len(rows)) or len(out) >= mhi:
            continue
        m = fit(rows, i, j, plo, phi)
        if not m or any(m[0] < b and a < m[1] for a, b in out) or total + m[1] - m[0] > shi:
            continue
        out.append(m)
        total += m[1] - m[0]
    return out


def strongest(s, rows, taken=()):
    """Without a model (or too few good moments): the strongest seconds of the interest curve (at least 30 s apart),
    each grown to whole lines -> moments in time order, added to `taken` up to the trailer's length."""
    from scipy.signal import find_peaks
    from .interest import interest_curve
    (plo, phi), (_, shi), (_, mhi) = CFG["piece"], CFG["seconds"], CFG["moments"]
    ev = interest_curve(s)
    peaks, _ = find_peaks(ev.interest.values, distance=HCFG["peak_distance"])
    out, total = list(taken), sum(b - a for a, b in taken)
    for p in sorted(peaks, key=lambda p: -ev.interest[p]):
        t = float(ev.t[p])
        i = max((k for k, r in enumerate(rows) if r["start"] <= t), default=0)
        m = fit(rows, i, i, plo, phi)
        if m and not any(m[0] < b and a < m[1] for a, b in out) and total + m[1] - m[0] <= shi:
            out.append(m)
            total += m[1] - m[0]
        if len(out) >= mhi or total >= (CFG["seconds"][0] + shi) / 2:
            break
    return out[:len(taken)] + sorted(out[len(taken):])


def default_ask(prompt):
    """Gemini (highlights.title_model); the local model only if Gemini can't be used."""
    if HCFG.get("title_model"):
        try:
            from ..audio.gemini import ask_json
            return ask_json(HCFG["title_model"], prompt, Answer)
        except Exception as e:
            print(f"  Gemini trailer failed ({type(e).__name__}: {str(e)[:120]}) -> the local model")
    from ..brain.llm_client import chat_json
    model = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["ollama"]["text_model"]
    return chat_json(model, prompt, Answer, think=False)


def choose(s, ask=None):
    """(moments [(start, end)], title_ar, title_en)."""
    meta = read_json(s / "session.json")
    up = read_json(s / "upload.json") if (s / "upload.json").exists() else {}
    rows = [r for r in read_json(s / "transcript.json") if r["end"] > r["start"] and r.get("speaker")]
    (mlo, mhi), (plo, phi), (slo, shi) = CFG["moments"], CFG["piece"], CFG["seconds"]
    moments, ta, te = [], "", ""
    try:
        a = (ask or default_ask)(PROMPT.format(lo=mlo, hi=mhi, plo=plo, phi=phi, slo=slo, shi=shi,
                                               title=up.get("name") or meta["id"],
                                               lines=numbered(rows, meta["language"])))
        moments, ta, te = pick(rows, [(m.first, m.last) for m in a.moments]), a.title_ar.strip(), a.title_en.strip()
    except Exception as e:                                         # no model / bad answer: the interest curve
        print(f"  WARNING: the model could not choose the trailer ({type(e).__name__}: {str(e)[:120]})")
    if len(moments) < mlo or sum(b - a for a, b in moments) < slo * 0.75:
        moments = strongest(s, rows, moments)
    name = up.get("name") or meta["id"]
    return moments, ta or name, te or name


def card_ass(path, w, h, lang, title, brand):
    """The end card's text: "Full episode" small, the episode's name big, in the brand's colours."""
    from ..audio.subtitles import FONT, RLM
    c = brand["captions"]
    rtl = RLM if lang == "ar" else ""
    big, small = round(h * (0.095 if w > h else 0.05)), round(h * (0.055 if w > h else 0.032))
    esc = lambda x: x.replace("{", "(").replace("}", ")").replace("\\", "/")                  # noqa: E731
    Path(path).write_text("\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "ScaledBorderAndShadow: yes",
        "WrapStyle: 0", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Card,{FONT},{big},{ass_colour(c['text_color'])},&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,"
        f"1,0,0,5,{w // 12},{w // 12},0,-1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,0:00:00.00,0:01:00.00,Card,,0,0,0,,{{\\fs{small}\\1c{ass_colour(c['word_color'])}}}"
        f"{rtl}{END_WORDS[lang]}\\N{{\\r}}{rtl}{esc(title)}", ""]), encoding="utf-8-sig")


def join(s, parts, out, lang, title, brand):
    """parts (clip files) -> out: fades through black, the end card, the brand outro, the brand music under it."""
    w, h = (probe(s / parts[0])[k] for k in ("width", "height"))
    fade, card = CFG.get("fade", 0.25), CFG.get("end_card", 3.0)
    lens = [probe(s / p)["duration"] for p in parts]
    inputs, graph, order = [], [], []
    for k, (p, d) in enumerate(zip(parts, lens)):
        inputs += ["-i", p]
        graph.append(f"[{k}:v]scale={w}:{h},setsar=1,fps=30,format=yuv420p,fade=t=in:st=0:d={fade},"
                     f"fade=t=out:st={d - fade:.3f}:d={fade}[v{k}]")
        graph.append(f"[{k}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,afade=t=in:d={fade},"
                     f"afade=t=out:st={d - fade:.3f}:d={fade}[a{k}]")
        order.append(k)
    n = len(parts)
    ass = s / "tmp" / f"{Path(out).stem}_card.ass"
    card_ass(ass, w, h, lang, title, brand)
    inputs += ["-f", "lavfi", "-t", f"{card}", "-i", f"color=c={brand['captions']['box_color'].replace('#', '0x')}"
               f":s={w}x{h}:r=30", "-f", "lavfi", "-t", f"{card}", "-i", "anullsrc=r=48000:cl=stereo"]
    graph.append(f"[{n}:v]subtitles=tmp/{ass.name},setsar=1,format=yuv420p,fade=t=in:st=0:d={fade}[vc]")
    graph.append(f"[{n + 1}:a]aformat=sample_fmts=fltp:channel_layouts=stereo[ac]")
    order.append("c")
    k = n + 2
    if brand["logo"]:                                               # the logo on the card too
        inputs += ["-i", brand["logo"]]
        scale, over = logo_overlay(brand, k, w if w > h else round(w * 16 / 9), "vcl")   # the clips' logo size
        graph[-2] = graph[-2].replace("[vc]", "[vc0]")
        graph.append(scale + "[vc0][logo]" + over.replace("[vcl]", "[vc]"))
        k += 1
    total = sum(lens) + card
    if brand["outro"]:
        inputs += ["-i", brand["outro"]]
        graph.append(f"[{k}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
                     f"setsar=1,fps=30,format=yuv420p[vo]")
        od = probe(s / brand["outro"])["duration"]
        graph.append(f"[{k}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[ao]" if
                     has_audio(s / brand["outro"]) else f"anullsrc=r=48000:cl=stereo,atrim=duration={od:.3f}[ao]")
        order.append("o")
        total += od
        k += 1
    graph.append("".join(f"[v{x}][a{x}]" for x in order) + f"concat=n={len(order)}:v=1:a=1[v][talk]")
    if brand.get("music"):                                          # quiet music, pushed down while people talk
        inputs += ["-stream_loop", "-1", "-i", brand["music"]]
        graph.append(f"[{k}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                     f"volume={CFG.get('music_volume', 0.2)},atrim=duration={total:.3f},"
                     f"afade=t=out:st={max(total - 1.5, 0):.3f}:d=1.5[mus]")
        graph.append("[talk]asplit=2[talk1][key];[mus][key]sidechaincompress=threshold=0.03:ratio=8:attack=20:"
                     "release=400[duck];[talk1][duck]amix=inputs=2:normalize=0:duration=first[a]")
    else:
        graph.append("[talk]anull[a]")
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
         *h264(quality("clips")), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out], cwd=s)
    ass.unlink(missing_ok=True)


def render_trailer(s, moments, title_ar, title_en):
    """Both trailer files from the moments. Returns {"16:9": path, "9:16": path} (paths inside the session)."""
    import pandas as pd
    from .clips import vertical_source
    s = Path(s)
    meta = read_json(s / "session.json")
    lang = meta["language"]
    brand = load_brand(s)
    cuts = read_json(s / "cuts.json")
    feats = pd.read_parquet(s / "features.parquet") if (s / "features.parquet").exists() else pd.DataFrame(
        columns=["t", "cam", "face_area", "face_x"])
    (s / "trailer").mkdir(exist_ok=True)
    files = {}
    for fmt, tag in (("16:9", "169"), ("9:16", "916")):
        parts = []
        for k, (a, b) in enumerate(moments):
            part = f"tmp/trailer_{k}_{tag}.mp4"
            if fmt == "16:9":
                render_clip(s, a, b, part, fmt="16:9")
            else:
                source, crop_x = vertical_source(s, a, b, cuts, feats)
                render_clip(s, a, b, part, fmt="9:16", source=source, crop_x=crop_x)
            parts.append(part)
        out = f"trailer/trailer_{tag}.mp4"
        join(s, parts, out, lang, title_ar if lang == "ar" else title_en, brand)
        for p in parts:
            (s / p).unlink(missing_ok=True)
        files[fmt] = out
    return files


def make_trailer(s, ask=None, again=True):
    """trailer.json + both files. again=False and a trailer.json exists: the same moments made again (after a caption
    edit or a new brand kit; no model request)."""
    s = Path(s)
    if not again and (s / "trailer.json").exists():
        t = read_json(s / "trailer.json")
        moments, ta, te = [(m["start"], m["end"]) for m in t["moments"]], t["title_ar"], t["title_en"]
    else:
        moments, ta, te = choose(s, ask)
    if not moments:
        raise ValueError("no moments for a trailer (no transcript lines that fit)")
    rows = read_json(s / "transcript.json")
    said = lambda a, b: " ".join(r["text"] for r in rows if a <= r["start"] and r["end"] <= b)       # noqa: E731
    files = render_trailer(s, moments, ta, te)
    out = {"title_ar": ta, "title_en": te, "files": files,
           "moments": [{"start": a, "end": b, "text": said(a, b)[:300]} for a, b in moments]}
    Trailer.model_validate(out)                                         # follows the contract
    write_json(s / "trailer.json", out)
    return out


if __name__ == "__main__":
    t = make_trailer(session_from_argv())
    print(f"trailer: {len(t['moments'])} moments, {sum(m['end'] - m['start'] for m in t['moments']):.1f} s "
          f"+ end card -> {t['files']}")
