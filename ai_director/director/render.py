# ai_director/director/render.py — stage 6: cut list -> the edited video (program.mp4)
#   python -m ai_director.director.render data/sessions/s01
import shutil

from ai_director.common.io import read_json, run, session_from_argv


def render_program(session_dir, cuts, out="program_nocaps.mp4"):
    """Cut every shot out of its camera, join the shots, add ONE continuous audio track."""
    ref = read_json(session_dir / "session.json")["reference_cam"]
    tmp = session_dir / "tmp"
    tmp.mkdir(exist_ok=True)
    names = []
    for i, c in enumerate(cuts):                       # 1. one small video file per shot
        name = f"seg{i:04d}.mp4"
        run(["ffmpeg", "-y", "-ss", f"{c['start']:.3f}", "-i", f"video/cam{c['cam']}.mp4",
             "-t", f"{c['end'] - c['start']:.3f}", "-an", "-r", "30",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", f"tmp/{name}"], cwd=session_dir)
        names.append(f"file '{name}'")
    (tmp / "list.txt").write_text("\n".join(names), encoding="utf-8")
    # 2. join the shots (no re-encoding) + 3. the sound of the reference camera for the whole video
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "tmp/list.txt",
         "-i", f"video/cam{ref}.mp4", "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-shortest", out], cwd=session_dir)
    for i in range(len(cuts)):                         # 4. clean up the shot files
        (tmp / f"seg{i:04d}.mp4").unlink()
    return session_dir / out


def add_captions(session_dir, inp="program_nocaps.mp4", out="program.mp4"):
    """Burn Nada's captions if her code and transcript exist; otherwise copy the video (until Day 7)."""
    try:
        from ai_director.audio.subtitles import burn_captions      # Nada, ready on Day 7
    except ImportError:
        burn_captions = None
    if burn_captions and (session_dir / "transcript.json").exists():
        burn_captions(session_dir, inp, out)
    else:
        shutil.copyfile(session_dir / inp, session_dir / out)


if __name__ == "__main__":
    s = session_from_argv()
    render_program(s, read_json(s / "cuts.json"))
    add_captions(s)                                    # writes program.mp4 LAST: the "done" file
    print("done:", s / "program.mp4")