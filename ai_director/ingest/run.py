# ai_director/ingest/run.py — stage 1: raw/ videos -> synced copies + audio.wav + session.json
#   python -m ai_director.ingest.run data/sessions/s01
from ai_director.common.io import read_json, session_from_argv, write_json
from ai_director.ingest.probe import probe
from ai_director.ingest.proxy import make_copies
from ai_director.ingest.sync import audio_offset, extract_audio


def main(s):
    up = read_json(s / "upload.json")
    cams = sorted(int(p.stem[3:]) for p in (s / "raw").glob("cam*.mp4"))   # [1, 2, 3]
    ref = up["wide_cam"]          # reference camera = the wide one (all phones had good audio)

    (s / "tmp").mkdir(exist_ok=True)
    for c in cams:
        extract_audio(s / f"raw/cam{c}.mp4", s / f"tmp/cam{c}.wav")
    offsets = {c: round(audio_offset(s / f"tmp/cam{ref}.wav", s / f"tmp/cam{c}.wav"), 3) for c in cams}
    print("offsets:", offsets)

    durations = {c: probe(s / f"raw/cam{c}.mp4")["duration"] for c in cams}
    starts, length = make_copies(s, offsets, durations, ref)

    write_json(s / "session.json", {          # written LAST: it is this stage's "done" file
        "id": s.name, "fps": 30, "duration": round(length, 2), "language": up["language"],
        "reference_cam": ref,
        "cameras": [{"id": c, "role": "wide" if c == up["wide_cam"] else "closeup", "offset": offsets[c]}
                    for c in cams],
        "num_speakers": up.get("num_speakers"), "speaker_names": up.get("speaker_names", {})})
    print("done:", s / "session.json")


if __name__ == "__main__":
    main(session_from_argv())