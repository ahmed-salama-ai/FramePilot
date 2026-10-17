import sys
from pathlib import Path

import pandas as pd
from pydantic import TypeAdapter, ValidationError

from ai_director.common import schemas as S
from ai_director.common.io import read_json, read_jsonl

JSON_FILES = {
    "upload.json": (S.Upload, "web app"),
    "session.json": (S.Session, "ingest"),
    "speech.json": (list[S.Span], "audio"),
    "diarization.json": (list[S.DiarSegment], "audio"),
    "transcript.json": (list[S.TranscriptSegment], "audio"),
    "speakers.json": (list[S.SpeakerInfo], "audio"),
    "audio_events.json": (list[S.AudioEvent], "audio"),
    "speaker_map.json": (dict[str, int], "perception"),
    "cuts.json": (list[S.Cut], "director"),
    "timeline.json": (S.Timeline, "director"),
    "highlights.json": (list[S.Highlight], "highlights"),
    "clips.json": (list[S.Clip], "agent"),
    "metrics.json": (S.Metrics, "evaluation"),
    "brand.json": (S.Brand, "web app"),
    "publish.json": (S.Publish, "highlights"),
    "versions.json": (list[S.Version], "render / agent"),
}


def check_session(s: Path) -> list[str]:
    """Return list of problems"""
    s, problems = Path(s), []
    bad = lambda f, msg: problems.append(f"{f}: {msg}")

    for name, (schema, owner) in JSON_FILES.items():
        if (s / name).exists():
            try:
                TypeAdapter(schema).validate_python(read_json(s / name))
            except (ValidationError, ValueError) as e:
                bad(name, f"({owner}) {str(e).splitlines()[0]} … {str(e).splitlines()[1:3]}")
    if (s / "scene.jsonl").exists():
        try:
            TypeAdapter(list[S.SceneLine]).validate_python(read_jsonl(s / "scene.jsonl"))
        except (ValidationError, ValueError) as e:
            bad("scene.jsonl", f"(brain) {str(e).splitlines()[0]}")

    if not (s / "session.json").exists():
        return problems
    meta = read_json(s / "session.json")
    dur, cams = meta["duration"], [c["id"] for c in meta["cameras"]]
    rows = round(dur * 10)                          # one row every 0.1 s

    for c in cams:
        if not (s / f"video/cam{c}.mp4").exists():
            bad(f"video/cam{c}.mp4", "missing (ingest)")

    if (s / "features.parquet").exists():
        f = pd.read_parquet(s / "features.parquet")
        missing = set(S.FEATURE_COLUMNS) - set(f.columns)
        if missing:
            bad("features.parquet", f"missing columns {sorted(missing)}")
        elif f[S.FEATURE_COLUMNS].isna().any().any():
            bad("features.parquet", "has NaN values")
        for c in cams:
            n = int((f.cam == c).sum()) if "cam" in f else 0
            if abs(n - rows) > 2:
                bad("features.parquet", f"cam {c} has {n} rows, expected ~{rows} (duration × 10)")

    if (s / "cuts.json").exists():
        cuts = read_json(s / "cuts.json")
        if cuts and (cuts[0]["start"] != 0 or abs(cuts[-1]["end"] - dur) > 0.2):
            bad("cuts.json", f"must cover 0 → {dur} s")
        if any(abs(a["end"] - b["start"]) > 1e-6 for a, b in zip(cuts, cuts[1:])):
            bad("cuts.json", "gaps or overlaps between cuts")
        if any(c["cam"] not in cams for c in cuts):
            bad("cuts.json", "uses a camera that is not in session.json")

    if (s / "timeline.json").exists():
        tl = read_json(s / "timeline.json")
        n = len(tl["t"])
        if any(len(v) != n for v in [tl["on_air"], tl["mode"], *tl["scores"].values()]):
            bad("timeline.json", "all lists must have the same length as t")

    if (s / "labels.csv").exists():
        lab = pd.read_csv(s / "labels.csv")
        if list(lab.columns) != ["t", "cam"] or abs(len(lab) - rows) > 2:
            bad("labels.csv", f"needs columns t,cam and ~{rows} rows (has {len(lab)})")

    for name in ("highlights.json", "clips.json"):
        if (s / name).exists():
            for item in read_json(s / name):
                files = item.get("files", {}).values() if name == "highlights.json" else [item.get("file")]
                for f in files:
                    if not (s / f).exists():
                        bad(name, f"{item['id']}: file {f} is missing")
    return problems


if __name__ == "__main__":
    s = Path(sys.argv[1])
    problems = check_session(s)
    print("\n".join(f"{p}" for p in problems) or f"{s}: every file present follows the contract")
    sys.exit(1 if problems else 0)
