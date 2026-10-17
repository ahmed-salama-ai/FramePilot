from pathlib import Path

from ai_director.common.io import read_json, run, session_from_argv
from ai_director.director.versions import get_version, video_time


def chapters_for(session_dir, version, lang, length):
    """The publish kit's chapters in this version's time ((start, end, title), first at 0), [] if none."""
    s = Path(session_dir)
    p = read_json(s / "publish.json") if (s / "publish.json").exists() else {}
    marks = []
    for k, c in enumerate(p.get("chapters") or []):
        t = 0.0 if k == 0 else video_time(version, c["start"])
        if not marks or t > marks[-1][0] + 1:
            marks.append((t, c.get(f"title_{lang}") or c.get("title_en") or ""))
    return [(a, b, title) for (a, title), b in zip(marks, [m[0] for m in marks[1:]] + [length])]


def ffmetadata(title, chapters):
    """FFmpeg's metadata file: the title + one [CHAPTER] per chapter (times in ms)."""
    esc = lambda x: "".join("\\" + ch if ch in "=;#\\\n" else ch for ch in x)
    lines = [";FFMETADATA1", f"title={esc(title)}"]
    for a, b, name in chapters:
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(a * 1000)}", f"END={int(b * 1000)}", f"title={esc(name)}"]
    return "\n".join(lines) + "\n"


def make_podcast(session_dir, vid="v1", lang=None):
    """export/<session>_<version>_podcast.mp3 (made again only when the video, the chapters or the cover changed).
    lang = the chapter titles' language (default: the session's). Returns its path."""
    from ai_director.ingest.probe import probe
    s = Path(session_dir)
    v = get_version(s, vid)
    meta = read_json(s / "session.json")
    lang = lang or meta["language"]
    src = next((v[k] for k in ("program", "clean", "nocaps") if v.get(k) and (s / v[k]).exists()), None)
    if src is None:
        raise ValueError(f"{vid} has no video yet")
    out = s / "export" / f"{s.name}_{vid}_podcast_{lang}.mp3"
    cover = next((p for p in (s / "thumbnails").glob(f"thumb_1_{lang}.jpg")), None) if (s / "thumbnails").exists() else None
    inputs = [s / src] + [x for x in (s / "publish.json", cover) if x and x.exists()]
    if out.exists() and all(out.stat().st_mtime >= x.stat().st_mtime for x in inputs):
        return out
    out.parent.mkdir(exist_ok=True)
    up = read_json(s / "upload.json") if (s / "upload.json").exists() else {}
    title = up.get("name") or s.name
    length = probe(s / src)["duration"]
    meta_file = s / "tmp" / "podcast_meta.txt"
    meta_file.parent.mkdir(exist_ok=True)
    meta_file.write_text(ffmetadata(title, chapters_for(s, v, lang, length)), encoding="utf-8")
    cmd = ["ffmpeg", "-y", "-i", src, "-i", "tmp/podcast_meta.txt"]
    maps = ["-map", "0:a", "-map_metadata", "1", "-map_chapters", "1"]
    if cover:
        cmd += ["-i", str(cover.relative_to(s).as_posix())]
        maps += ["-map", "2:v", "-c:v", "mjpeg", "-disposition:v", "attached_pic", "-metadata:s:v", "title=Cover"]
    run(cmd + maps + ["-c:a", "libmp3lame", "-b:a", "160k", "-ar", "44100", "-id3v2_version", "3",
                      "-metadata", "genre=Podcast", f"export/{out.name}"], cwd=s)
    meta_file.unlink(missing_ok=True)
    return out


if __name__ == "__main__":
    import sys
    print("written:", make_podcast(session_from_argv(), sys.argv[2] if len(sys.argv) > 2 else "v1"))
