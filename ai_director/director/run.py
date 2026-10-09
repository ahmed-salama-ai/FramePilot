#   python -m ai_director.director.run data/sessions/s01
import yaml

from ai_director.common.io import read_json, session_from_argv, write_json
from ai_director.common.paths import CONFIGS
from ai_director.director.scorer import score
from ai_director.director.split import add_splits, split_moments
from ai_director.director.switcher import Switcher

RULES = yaml.safe_load((CONFIGS / "default.yaml").read_text(encoding="utf-8"))["switcher"]
STEP = 0.1


def speaker_cam_at(times, diar, spk_map):
    """For every time: the camera of the person talking (None = nobody, or not in a close-up)."""
    out = [None] * len(times)
    for seg in diar:
        cam = spk_map.get(seg["speaker"])
        for i, t in enumerate(times):
            if seg["start"] <= t < seg["end"]:
                out[i] = cam
    return out                      # simple version; fine for 10-minute videos


def to_segments(on_air, step=STEP):
    """[(t, cam), ...] every 0.1 s -> cut list [{start, end, cam}]."""
    cuts = []
    for t, cam in on_air:
        if cuts and cuts[-1]["cam"] == cam:
            cuts[-1]["end"] = round(t + step, 2)
        else:
            cuts.append({"start": round(t, 2), "end": round(t + step, 2), "cam": cam})
    return cuts


def decide(s, boost=None, force_mode=None):
    """Run the scorer and the switcher. Returns (cuts, scores)."""
    cams = read_json(s / "session.json")["cameras"]
    wide = next(c["id"] for c in cams if c["role"] == "wide")
    sc = score(s, boost=boost, force_mode=force_mode)
    table = sc.pivot(index="t", columns="cam", values="score")       # rows = times, columns = cameras
    times = list(table.index)
    diar = read_json(s / "diarization.json") if (s / "diarization.json").exists() else []
    spk_map = read_json(s / "speaker_map.json") if (s / "speaker_map.json").exists() else {}
    speakers = speaker_cam_at(times, diar, spk_map)

    sw = Switcher({**RULES, "wide_cam": wide}, start_cam=wide)      # always start on the wide shot
    on_air = []
    for (t, row), spk in zip(table.iterrows(), speakers):
        scores = {int(cam): float(v) for cam, v in row.items()}
        on_air.append((t, sw.step(t, scores, spk)))
    return add_splits(to_segments(on_air), split_moments(s), RULES["min_shot"]), sc   # split screen (2026-10-09)


def make_cuts(s, boost=None, force_mode=None, out="cuts.json"):
    """Used by the Editor Agent (Day 8): a new cut list with a boost or a fixed mode."""
    cuts, _ = decide(s, boost, force_mode)
    write_json(s / out, cuts)
    return cuts


def on_air_at(cuts, t):
    """The camera on air at time t (the last shot also covers the very end)."""
    return next(c["cam"] for c in cuts if c["start"] <= t < c["end"] or c is cuts[-1])


def make_timeline(sc, cuts):
    """1 value per second for the website chart: average score per camera, camera on air, mode."""
    sec = sc.assign(s=sc.t.astype(int))                              # 12.7 s -> second 12
    avg = sec.groupby(["s", "cam"]).score.mean().unstack()           # rows = seconds, columns = cameras
    modes = sec.groupby("s")["mode"].first()                         # the mode at the start of each second
    return {"t": [float(s) for s in avg.index],
            "scores": {str(cam): [round(float(v), 3) for v in avg[cam]] for cam in avg.columns},
            "on_air": [on_air_at(cuts, float(s)) for s in avg.index],
            "mode": [modes[s] for s in avg.index]}

if __name__ == "__main__":
    s = session_from_argv()
    cuts, sc = decide(s)
    sc.to_parquet(s / "scores.parquet", index=False)
    write_json(s / "timeline.json", make_timeline(sc, cuts))         # for Ahmed Sameh's chart
    write_json(s / "cuts.json", cuts)                                # written LAST: the "done" file
    shots = [c["end"] - c["start"] for c in cuts]
    splits = [c for c in cuts if c.get("split")]
    print(f"{len(cuts)} shots, average {sum(shots) / len(shots):.1f} s, shortest {min(shots):.1f} s; "
          f"{len(splits)} split screens, {sum(c['end'] - c['start'] for c in splits):.0f} s")
    for c in cuts:
        print(f"  {c['start']:6.1f} -> {c['end']:6.1f}  " +
              (f"split cam {c['split'][0]} | cam {c['split'][1]}" if c.get("split") else f"cam {c['cam']}"))