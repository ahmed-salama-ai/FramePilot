"""Create samples/mock_s00/: a fake 60-second, 3-camera session in the exact file contract (Architecture §4).

Run from the repo root:   python samples/make_mock.py
Needs: FFmpeg + requirements-cpu.txt. Deterministic (fixed seed): re-running gives the same data.

The story (a tiny podcast): SPEAKER_00 = host (camera 2), SPEAKER_01 = guest (camera 3), camera 1 = wide.
Host opens → guest gives CV tips → host asks about salaries → everyone laughs (33–38 s) → guest answers → host closes.
Every file agrees with this story, so each stage can be tested against the others.

raw/ holds "unsynced" camera files with KNOWN offsets (see OFFSETS): use them to test ingest/sync.py.
The audio is shaped noise (loud while people talk, a sharp clap at 0.5 s) so cross-correlation has a clear peak.
"""
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_director.common.io import run, write_json, write_jsonl  # noqa: E402

OUT = ROOT / "samples" / "mock_s00"
TMP = OUT / "_tmp"
DUR, STEP, FPS, SR = 60.0, 0.1, 30, 48000
CAMS = [1, 2, 3]
ROLES = {1: "wide", 2: "closeup", 3: "closeup"}
PATTERNS = {1: "testsrc", 2: "testsrc", 3: "testsrc"}      # simple pattern = tiny files
TINT = {1: "", 2: ",hue=h=120", 3: ",hue=h=240"}           # a different colour per camera
OFFSETS = {1: 0.0, 2: 1.84, 3: -0.52}       # what sync must find (ref = cam 1); > 0 = started earlier
TAIL = {1: 0.3, 2: 0.0, 3: 0.6}             # raw files stop at slightly different times
HEAD = 3.0                                  # master audio starts 3 s before synced t = 0
NAMES = {"SPEAKER_00": "Host", "SPEAKER_01": "Guest"}
SPEAKER_MAP = {"SPEAKER_00": 2, "SPEAKER_01": 3}
LAUGH = (33.0, 38.0)
CLAP = 0.5

# (start, end, speaker, Arabic text, English translation) — one subtitle each (all ≤ 6 s)
SEGMENTS = [
    (1.0, 5.5, "SPEAKER_00", "أهلاً بيكم في حلقة جديدة من البودكاست", "Welcome to a new episode of the podcast"),
    (5.8, 11.8, "SPEAKER_00", "النهارده هنتكلم عن أول شغلانة والمرتبات", "Today we talk about the first job and salaries"),
    (12.5, 17.5, "SPEAKER_01", "أول حاجة السي في لازم يبقى صفحة واحدة بس", "First, your CV should be one page only"),
    (17.8, 22.4, "SPEAKER_01", "وركز على المشاريع اللي عملتها بإيدك", "And focus on the projects you built yourself"),
    (22.6, 27.0, "SPEAKER_01", "الشركات بتحب تشوف شغل حقيقي", "Companies like to see real work"),
    (27.5, 33.0, "SPEAKER_00", "طب والمرتبات؟ الناس دايماً بتسأل عن المرتب", "And salaries? People always ask about the salary"),
    (38.0, 43.5, "SPEAKER_01", "بصراحة المرتب في أول سنة مش أهم حاجة", "Honestly, the first-year salary is not the most important thing"),
    (43.8, 48.0, "SPEAKER_01", "الأهم إنك تتعلم من ناس شاطرة", "What matters is learning from skilled people"),
    (48.2, 52.0, "SPEAKER_01", "وبعد سنتين المرتب هيفرق معاك جداً", "After two years the salary changes a lot"),
    (52.5, 56.0, "SPEAKER_00", "كلام جميل جداً، شكراً ليك", "Great words, thank you"),
    (56.3, 59.5, "SPEAKER_00", "ونشوفكم في الحلقة الجاية", "See you in the next episode"),
]

# the AI edit (what the switcher should roughly produce) and the human edit (labels.csv)
CUTS = [(0.0, 3.0, 1), (3.0, 12.8, 2), (12.8, 27.6, 3), (27.6, 33.2, 2), (33.2, 38.3, 1),
        (38.3, 52.7, 3), (52.7, 60.0, 2)]
HUMAN = [(0.0, 4.0, 1), (4.0, 12.6, 2), (12.6, 27.8, 3), (27.8, 33.5, 2), (33.5, 38.2, 3),
         (38.2, 45.0, 3), (45.0, 47.0, 1), (47.0, 52.6, 3), (52.6, 60.0, 2)]
HIGHLIGHTS = [
    {"id": "h1", "start": 27.5, "end": 48.0, "title_ar": "سؤال المرتبات", "title_en": "The salary question",
     "hook": "Why everyone laughed at the salary question"},
    {"id": "h2", "start": 12.5, "end": 27.0, "title_ar": "أخطاء السي في", "title_en": "CV mistakes to avoid",
     "hook": "One page, real projects: the CV rule"},
]
CLIPS = [{"id": "c1", "start": 38.0, "end": 52.0, "format": "9:16", "title": "Salary advice from the guest",
          "file": "clips/c1.mp4"}]
# scene.jsonl: t → (scene, event, energy, raw_mode, highlight)
SCENES = {0: ("host introduces the episode", "talking", 0.3, "conversation", False),
          5: ("host talks about the topic", "talking", 0.3, "conversation", False),
          10: ("host hands over to the guest", "talking", 0.4, "conversation", False),
          15: ("guest gives CV advice", "talking", 0.4, "conversation", False),
          20: ("guest gives CV advice", "talking", 0.4, "conversation", False),
          25: ("guest talks about real projects", "talking", 0.5, "conversation", True),
          30: ("host asks about salaries", "talking", 0.6, "conversation", True),
          35: ("everyone is laughing", "laughter", 0.9, "reaction", True),
          40: ("guest answers, still smiling", "talking", 0.6, "conversation", True),
          45: ("guest explains learning first", "talking", 0.5, "conversation", False),
          50: ("guest finishes the answer", "talking", 0.4, "conversation", False),
          55: ("host thanks the guest", "talking", 0.3, "conversation", False)}


def ts(t, sep=","):
    ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def turns():
    """Merge consecutive segments of the same speaker → diarization turns."""
    out = []
    for a, b, spk, *_ in SEGMENTS:
        if out and out[-1]["speaker"] == spk and a - out[-1]["end"] < 1.0:
            out[-1]["end"] = b
        else:
            out.append({"start": a, "end": b, "speaker": spk})
    return out


def speaker_at(t):
    return next((d["speaker"] for d in turns() if d["start"] <= t < d["end"]), None)


def cam_at(spans, t):
    return next(c for a, b, c in spans if a <= t < b or b == DUR and t >= a)


def mode_at(t, scene_rows):
    return [r["mode"] for r in scene_rows if r["t"] <= t][-1]


def find_font():
    for p in ["C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/System/Library/Fonts/Supplemental/Arial.ttf"]:
        if Path(p).exists():
            return Path(p)
    return None


# ---------------------------------------------------------------- audio (master track)
def make_master_audio():
    """Shaped white noise on a 'master' timeline that starts HEAD s before synced t = 0."""
    rng = np.random.default_rng(42)
    n = int((HEAD + DUR + 2.0) * SR)
    t = np.arange(n) / SR - HEAD                       # synced time of every sample
    env = np.full(n, 0.02)
    for a, b, *_ in SEGMENTS:
        env[(t >= a) & (t < b)] = 0.25
    env[(t >= LAUGH[0]) & (t < LAUGH[1])] = 0.45
    env[(t >= CLAP) & (t < CLAP + 0.03)] = 0.95        # the clap
    x = rng.standard_normal(n) * env
    sf.write(TMP / "master.wav", np.clip(x, -1, 1).astype("float32"), SR)


# ---------------------------------------------------------------- videos
def source(cam, size, font):
    """lavfi test pattern for one camera, with a 'CAM n' label when a font is available."""
    text = (f",drawtext=fontfile=font.ttf:text='CAM {cam}':fontsize=h/10:fontcolor=white"
            f":box=1:boxcolor=black@0.6:boxborderw=12:x=30:y=30") if font else ""
    return f"{PATTERNS[cam]}=size={size}:rate={FPS}{TINT[cam]}{text}"


def make_videos(font):
    starts = {c: o - min(OFFSETS.values()) for c, o in OFFSETS.items()}   # all ≥ 0, like proxy.py
    for c in CAMS:
        # raw/camN.mp4: 640×360, this camera started starts[c] s before synced t = 0
        raw_len = starts[c] + DUR + TAIL[c]
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", source(c, "640x360", font),
             "-ss", f"{HEAD - starts[c]:.3f}", "-i", "master.wav", "-t", f"{raw_len:.3f}",
             "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "34",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "1", "-b:a", "32k", f"../raw/cam{c}.mp4"], cwd=TMP)
        # video/camN.mp4: synced 720p with audio (render) → video/camN_640.mp4: 640px, no audio (perception)
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", source(c, "1280x720", font),
             "-ss", f"{HEAD:.3f}", "-i", "master.wav", "-t", f"{DUR:.3f}",
             "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "32",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "1", "-b:a", "32k", f"../video/cam{c}.mp4"], cwd=TMP)
        run(["ffmpeg", "-y", "-i", f"video/cam{c}.mp4", "-vf", "scale=640:-2", "-an",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "34", f"video/cam{c}_640.mp4"], cwd=OUT)
    run(["ffmpeg", "-y", "-ss", f"{HEAD:.3f}", "-i", "_tmp/master.wav", "-t", f"{DUR:.3f}",
         "-ac", "1", "-ar", "16000", "audio.wav"], cwd=OUT)


def make_program():
    parts = [f"[{c - 1}:v]trim={a}:{b},setpts=PTS-STARTPTS[v{k}]" for k, (a, b, c) in enumerate(CUTS)]
    parts.append("".join(f"[v{k}]" for k in range(len(CUTS))) + f"concat=n={len(CUTS)}:v=1:a=0[v]")
    run(["ffmpeg", "-y", *sum((["-i", f"video/cam{c}.mp4"] for c in CAMS), []),
         "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "0:a",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "32", "-c:a", "aac", "-ac", "1", "-b:a", "32k",
         "program_nocaps.mp4"], cwd=OUT)
    style = "FontName=Arial,FontSize=15,BorderStyle=3,OutlineColour=&H80000000,Outline=1,Shadow=0,MarginV=20"
    run(["ffmpeg", "-y", "-i", "program_nocaps.mp4", "-vf", f"subtitles=_tmp/program.srt:force_style='{style}'",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "32", "-c:a", "copy", "program.mp4"], cwd=OUT)


def cut_clip(a, b, out, fmt):
    vf = ["crop=404:720:438:0,scale=720:1280"] if fmt == "9:16" else []
    run(["ffmpeg", "-y", "-ss", f"{a:.2f}", "-i", "program_nocaps.mp4", "-t", f"{b - a:.2f}",
         *(["-vf", vf[0]] if vf else []), "-c:v", "libx264", "-preset", "veryfast", "-crf", "32",
         "-c:a", "aac", "-ac", "1", "-b:a", "32k", out], cwd=OUT)


# ---------------------------------------------------------------- data files
def make_json_files():
    write_json(OUT / "upload.json", {"name": "Mock podcast", "language": "ar", "wide_cam": 1,
                                     "num_speakers": 2, "speaker_names": NAMES})
    write_json(OUT / "session.json", {
        "id": "s00", "fps": FPS, "duration": DUR, "language": "ar", "reference_cam": 1,
        "cameras": [{"id": c, "role": ROLES[c], "offset": OFFSETS[c]} for c in CAMS],
        "num_speakers": 2, "speaker_names": NAMES})

    write_json(OUT / "speech.json", [{"start": round(a - 0.1, 2), "end": round(b + 0.1, 2)}
                                     for a, b, *_ in SEGMENTS])
    write_json(OUT / "diarization.json", turns())

    transcript = []
    for i, (a, b, spk, ar, en) in enumerate(SEGMENTS):
        words, step = ar.split(), (b - a) / len(ar.split())
        transcript.append({"id": i, "start": a, "end": b, "speaker": spk, "text": ar, "translation": en,
                           "words": [{"w": w, "start": round(a + k * step, 2), "end": round(a + (k + 1) * step, 2)}
                                     for k, w in enumerate(words)]})
    write_json(OUT / "transcript.json", transcript)
    write_json(OUT / "speakers.json", [
        {"speaker": "SPEAKER_00", "role": "host", "name": NAMES["SPEAKER_00"],
         "description": "Opens and closes the episode and asks about CVs and salaries."},
        {"speaker": "SPEAKER_01", "role": "guest", "name": NAMES["SPEAKER_01"],
         "description": "Gives advice on CVs, first jobs and salaries."}])

    def srt(lines_of):
        return "\n".join(f"{i}\n{ts(a)} --> {ts(b)}\n{lines_of(spk, ar, en)}\n"
                         for i, (a, b, spk, ar, en) in enumerate(SEGMENTS, 1))
    both = lambda spk, ar, en: f"{NAMES[spk]}: {ar}\n{en}"
    (OUT / "captions_ar.srt").write_text(srt(lambda spk, ar, en: f"{NAMES[spk]}: {ar}"), encoding="utf-8")
    (OUT / "captions_en.srt").write_text(srt(lambda spk, ar, en: f"{NAMES[spk]}: {en}"), encoding="utf-8")
    (TMP / "program.srt").write_text(srt(both), encoding="utf-8")
    (OUT / "captions.vtt").write_text("WEBVTT\n\n" + "\n".join(
        f"{ts(a, '.')} --> {ts(b, '.')}\n{both(spk, ar, en)}\n" for a, b, spk, ar, en in SEGMENTS), encoding="utf-8")

    events = []
    for s in range(int(DUR)):
        talking = any(a <= s + 0.5 < b for a, b, *_ in SEGMENTS)
        laughing = LAUGH[0] <= s + 0.5 < LAUGH[1]
        events.append({"t": s, "loudness_db": -14.5 if laughing else -21.0 if talking else -38.0,
                       "laugh": 0.91 if laughing else 0.02})
    write_json(OUT / "audio_events.json", events)

    write_json(OUT / "speaker_map.json", SPEAKER_MAP)

    # scene.jsonl with the same smoothing rule as brain/modes.py
    rows, cur, prev = [], "conversation", None
    for t, (scene, event, energy, raw, hl) in sorted(SCENES.items()):
        if raw == prev: cur = raw
        if event == "laughter": cur = "reaction"
        rows.append({"t": float(t), "scene": scene, "event": event, "energy": energy,
                     "mode": cur, "raw_mode": raw, "highlight": hl})
        prev = raw
    write_jsonl(OUT / "scene.jsonl", rows)
    return rows


def make_tables(scene_rows):
    rng = np.random.default_rng(7)
    times = np.round(np.arange(0, DUR, STEP), 1)
    feats = []
    for c in CAMS:
        for t in times:
            spk = speaker_at(t)
            on_me = spk is not None and SPEAKER_MAP[spk] == c
            laughing = LAUGH[0] <= t < LAUGH[1]
            close = ROLES[c] == "closeup"
            n = lambda s: rng.normal(0, s)
            feats.append({
                "t": float(t), "cam": c,
                "num_people": 3 if not close else 1,
                "face_area": float(np.clip((0.12 if c == 2 else 0.10) + n(0.01), 0, 1)) if close
                             else float(np.clip(0.006 + n(0.001), 0, 1)),
                "face_x": float(np.clip({1: 0.5, 2: 0.45, 3: 0.56}[c] + n(0.01), 0, 1)),
                "frontalness": float(np.clip((0.85 if close else 0.35) + n(0.05), 0, 1)),
                "mouth_motion": float(np.clip((0.7 if on_me else 0.5 if laughing and close else 0.08) + n(0.08), 0, 1)),
                "speaker_prob": float(np.clip((0.85 if on_me else 0.05) + n(0.05), 0, 1)),
                "sharpness": float(np.clip(0.75 + n(0.05), 0, 1)),
                "exposure_ok": 1.0,
                "shake": float(np.clip((0.6 if c == 3 and 45 <= t < 46 else 0.02) + n(0.01), 0, 1)),
                "gesture_score": float(np.clip((0.8 if laughing else 0.1) + n(0.05), 0, 1)),
            })
    f = pd.DataFrame(feats)
    f["cam"] = f.cam.astype("int64"); f["num_people"] = f.num_people.astype("int64")
    f.to_parquet(OUT / "features.parquet", index=False)

    # scores.parquet: the Architecture §5 formula, so the mock scores match the features
    W = dict(speaker=3.0, frontal=1.0, quality=0.8, gesture=0.5, shake=1.0)
    modes = yaml.safe_load((ROOT / "configs" / "modes.yaml").read_text(encoding="utf-8"))
    base = (W["speaker"] * f.speaker_prob * (f.face_area / 0.15).clip(upper=1) + W["frontal"] * f.frontalness
            + W["quality"] * (0.6 * f.sharpness + 0.4 * f.exposure_ok) + W["gesture"] * f.gesture_score
            - W["shake"] * f.shake).clip(lower=0.01)
    f["mode"] = [mode_at(t, scene_rows) for t in f.t]
    f["score"] = base * [modes[m][ROLES[c]] for m, c in zip(f["mode"], f.cam)]
    f[["t", "cam", "score", "mode"]].to_parquet(OUT / "scores.parquet", index=False)

    write_json(OUT / "cuts.json", [{"start": a, "end": b, "cam": c} for a, b, c in CUTS])
    sec = f.assign(s=f.t.astype(int)).groupby(["s", "cam"]).score.mean().unstack()
    write_json(OUT / "timeline.json", {
        "t": [float(s) for s in sec.index],
        "scores": {str(c): [round(float(v), 3) for v in sec[c]] for c in CAMS},
        "on_air": [cam_at(CUTS, float(s)) for s in sec.index],
        "mode": [mode_at(float(s), scene_rows) for s in sec.index]})

    (OUT / "labels.csv").write_text("t,cam\n" + "\n".join(f"{t:.1f},{cam_at(HUMAN, t)}" for t in times) + "\n")
    (OUT / "highlight_labels.csv").write_text("start,end,reason\n30.0,40.0,laugh\n38.0,52.0,key_point\n")

    ai = np.array([cam_at(CUTS, t) for t in times]); human = np.array([cam_at(HUMAN, t) for t in times])
    shots = [b - a for a, b, _ in CUTS]
    write_json(OUT / "metrics.json", {
        "mock": True,
        "director": {"ai": {"agreement": round(float((ai == human).mean()), 3), "speaker_coverage": 0.86,
                            "short_cuts": int(sum(s < 1.0 for s in shots)), "avg_shot": round(float(np.mean(shots)), 2)},
                     "random": {"agreement": 0.34, "speaker_coverage": 0.35, "short_cuts": 0, "avg_shot": 5.0},
                     "wide": {"agreement": 0.12, "speaker_coverage": 0.0, "short_cuts": 0, "avg_shot": DUR}},
        "captions": {"ar": {"wer": 0.31, "cer": 0.14}, "en": {"wer": 0.12, "cer": 0.06}},
        "highlights": {"precision_at_3": 0.67},
        "agent": {"success_rate": 0.8, "avg_steps": 2.7, "avg_seconds": 21.4},
        "processing_seconds": {"Ingest + Sync": 4, "Audio + Captions": 12, "Perception": 9, "AI Brain": 15,
                               "Switching": 1, "Render": 6, "Highlights": 8, "Evaluation": 1}})


def make_clips():
    for h in HIGHLIGHTS:
        h["files"] = {"16:9": f"highlights/{h['id']}_169.mp4", "9:16": f"highlights/{h['id']}_916.mp4"}
        cut_clip(h["start"], h["end"], h["files"]["16:9"], "16:9")
        cut_clip(h["start"], h["end"], h["files"]["9:16"], "9:16")
    write_json(OUT / "highlights.json", HIGHLIGHTS)
    for c in CLIPS:
        cut_clip(c["start"], c["end"], c["file"], c["format"])
    write_json(OUT / "clips.json", CLIPS)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    for d in ("raw", "video", "highlights", "clips", "_tmp"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    font = find_font()
    if font:
        shutil.copy(font, TMP / "font.ttf")   # relative font path: avoids "C:" escaping problems in filters
    else:
        print("No font found: videos will have no CAM labels")
    make_master_audio()
    scene_rows = make_json_files()
    make_tables(scene_rows)
    make_videos(font)
    make_program()
    make_clips()
    shutil.rmtree(TMP)
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file()) / 1e6
    print(f"Mock session written to {OUT.relative_to(ROOT)} ({size:.1f} MB)")


if __name__ == "__main__":
    main()
