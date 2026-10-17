import zipfile
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

from ai_director.common.io import read_json, session_from_argv
from ai_director.director.pauses import fit_cuts, keep_parts, out_time
from ai_director.director.versions import get_version, version_captions
from ai_director.ingest.probe import probe

FPS = 30

README = """FramePilot edit {name} - open it in Premiere Pro or DaVinci Resolve

Premiere Pro:     File > Import... > {name}.xml  (a new sequence appears in the Project panel)
DaVinci Resolve:  File > Import > Timeline... > {name}.xml  (tick "Automatically import source clips")
Older tools:      {name}.edl (CMX3600, reels CAM1, CAM2, ...)

The edit uses the synced camera files of this session:
{files}
If the program says "media offline" (other PC, moved folder), relink to these files.
Captions: import captions_ar.srt / captions_en.srt as a caption / subtitle track.
Split screen: V1 has the person talking, V2 (switched off) the other camera, and a marker says where.
Not included: name cards, logo, intro and outro (they are only in program.mp4).
"""


def frames(t):
    return int(round(t * FPS))


def timecode(f):
    return f"{f // (3600 * FPS):02d}:{f // (60 * FPS) % 60:02d}:{f // FPS % 60:02d}:{f % FPS:02d}"


def path_url(path):
    """file://localhost/D%3a/... the way Premiere writes paths (Resolve reads it too)."""
    return "file://localhost/" + quote(Path(path).resolve().as_posix(), safe="/")


def rate():
    return f"<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>"


class Files:
    """Each camera file is described once then only referred to."""

    def __init__(self, s):
        self.s, self.done, self.info = s, set(), {}

    def length(self, cam):
        if cam not in self.info:
            self.info[cam] = probe(self.s / f"video/cam{cam}.mp4")
        return frames(self.info[cam]["duration"])

    def xml(self, cam):
        if cam in self.done:
            return f'<file id="file-{cam}"/>'
        self.done.add(cam)
        i = self.info[cam] if cam in self.info else probe(self.s / f"video/cam{cam}.mp4")
        return (f'<file id="file-{cam}"><name>cam{cam}.mp4</name>'
                f"<pathurl>{escape(path_url(self.s / f'video/cam{cam}.mp4'))}</pathurl>{rate()}"
                f"<duration>{self.length(cam)}</duration>"
                f"<timecode>{rate()}<string>00:00:00:00</string><frame>0</frame><displayformat>NDF</displayformat>"
                f"</timecode><media><video><samplecharacteristics>{rate()}<width>{i['width']}</width>"
                f"<height>{i['height']}</height><pixelaspectratio>square</pixelaspectratio></samplecharacteristics>"
                f"</video><audio><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate>"
                f"</samplecharacteristics><channelcount>2</channelcount></audio></media></file>")


def clipitem(n, files, cam, a, b, enabled=True, audio_track=None, src=None):
    """One clip on the timeline from frame a to b; src = (in, out) frames in the camera file (default: the same)."""
    track = (f"<sourcetrack><mediatype>audio</mediatype><trackindex>{audio_track}</trackindex></sourcetrack>"
             if audio_track else "")
    i, o = src or (a, b)
    return (f'<clipitem id="clipitem-{n}"><name>cam{cam}.mp4</name><enabled>{"TRUE" if enabled else "FALSE"}'
            f"</enabled><duration>{files.length(cam)}</duration>{rate()}<start>{a}</start><end>{b}</end>"
            f"<in>{i}</in><out>{o}</out>{files.xml(cam)}{track}</clipitem>")


def pieces(cuts, removed):
    """The cut list as timeline pieces"""
    if not removed:
        return [(c, c["start"], c["end"], c["start"], c["end"]) for c in cuts]
    return [(c, a, b, out_time(a, removed), out_time(a, removed) + b - a)
            for c in fit_cuts(cuts, removed) for a, b in keep_parts(c["start"], c["end"], removed)]


def fcp_xml(s, cuts, name, removed=None):
    """Final Cut Pro 7 XML of cut list"""
    s = Path(s)
    meta = read_json(s / "session.json")
    ref = meta["reference_cam"]
    files = Files(s)
    size = probe(s / f"video/cam{ref}.mp4")
    total = frames(out_time(cuts[-1]["end"], removed))
    v1, v2, markers, n = [], [], [], 0
    for c, sa, sb, ra, rb in pieces(cuts, removed):
        a, b = frames(ra), frames(rb)
        src = (frames(sa), frames(sa) + b - a)
        if b <= a:
            continue
        n += 1
        v1.append(clipitem(n, files, c["cam"], a, b, src=src))
        if c.get("split"):
            other = next((x for x in c["split"] if x != c["cam"]), c["split"][-1])
            n += 1
            v2.append(clipitem(n, files, other, a, b, enabled=False, src=src))
            markers.append(f"<marker><name>Split screen</name><comment>FramePilot showed cam{c['split'][0]} (left) "
                           f"and cam{c['split'][1]} (right) side by side here; V2 has the other camera</comment>"
                           f"<in>{a}</in><out>{b}</out></marker>")
    parts = keep_parts(0.0, cuts[-1]["end"], removed) if removed else [(0.0, cuts[-1]["end"])]
    audio = []
    for k in (1, 2):
        for a, b in parts:
            ra = frames(out_time(a, removed))
            n += 1
            audio.append(clipitem(n, files, ref, ra, ra + frames(b) - frames(a), audio_track=k,
                                  src=(frames(a), frames(b))))
    half = len(audio) // 2
    track = lambda items: f"<track>{''.join(items)}<enabled>TRUE</enabled><locked>FALSE</locked></track>"
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">'
            f'<sequence id="sequence-1"><name>{escape(name)}</name><duration>{total}</duration>{rate()}'
            f"<timecode>{rate()}<string>00:00:00:00</string><frame>0</frame><displayformat>NDF</displayformat>"
            f"</timecode><media><video><format><samplecharacteristics>{rate()}<width>{size['width']}</width>"
            f"<height>{size['height']}</height><anamorphic>FALSE</anamorphic><pixelaspectratio>square"
            f"</pixelaspectratio><fielddominance>none</fielddominance></samplecharacteristics></format>"
            f"{track(v1)}{track(v2) if v2 else ''}</video><audio><numOutputChannels>2</numOutputChannels>"
            f"<format><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics>"
            f"</format>{track(audio[:half])}{track(audio[half:])}</audio></media>{''.join(markers)}</sequence></xmeml>\n")


def edl(s, cuts, name, removed=None):
    """CMX3600 EDL"""
    ref = read_json(Path(s) / "session.json")["reference_cam"]
    lines, k = [f"TITLE: {name}", "FCM: NON-DROP FRAME", ""], 0
    for c, sa, sb, ra, rb in pieces(cuts, removed):
        a, b = frames(ra), frames(rb)
        i = frames(sa)
        if b <= a:
            continue
        k += 1
        lines += [f"{k:03d}  CAM{c['cam']:<5}V     C        {timecode(i)} {timecode(i + b - a)} {timecode(a)} "
                  f"{timecode(b)}", f"* FROM CLIP NAME: cam{c['cam']}.mp4"]
        if c.get("split"):
            lines.append(f"* SPLIT SCREEN: CAM{c['split'][0]} LEFT, CAM{c['split'][1]} RIGHT")
        lines.append("")
    for a, b in keep_parts(0.0, cuts[-1]["end"], removed) if removed else [(0.0, cuts[-1]["end"])]:
        k += 1
        i, o, r = frames(a), frames(b), frames(out_time(a, removed))
        lines += [f"{k:03d}  CAM{ref:<5}AA    C        {timecode(i)} {timecode(o)} {timecode(r)} {timecode(r + o - i)}",
                  f"* FROM CLIP NAME: cam{ref}.mp4", ""]
    return "\n".join(lines)


def export_package(session_dir, vid="v1"):
    """export/<session>_<version>_premiere_davinci.zip (XML + EDL + captions + README). Returns its path."""
    s = Path(session_dir)
    v = get_version(s, vid)
    cuts = read_json(s / v["cuts"])
    name = f"{s.name}_{vid}"
    out = s / "export" / f"{name}_premiere_davinci.zip"
    out.parent.mkdir(exist_ok=True)
    cams = sorted({c["cam"] for c in cuts} | {x for c in cuts for x in c.get("split") or []} |
                  {read_json(s / "session.json")["reference_cam"]})
    removed = v.get("removed") or []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{name}.xml", fcp_xml(s, cuts, f"FramePilot {name}", removed))
        z.writestr(f"{name}.edl", edl(s, cuts, f"FramePilot {name}", removed))
        if (s / "transcript.json").exists():                    #timed like this timeline
            for lang in ("ar", "en"):
                z.writestr(f"captions_{lang}.srt", version_captions(s, {**v, "intro": 0.0}, lang))
        z.writestr("README.txt", README.format(name=name, files="\n".join(
            f"  {(s / f'video/cam{c}.mp4').resolve()}" for c in cams)))
    return out


if __name__ == "__main__":
    import sys
    s = session_from_argv()
    print("written:", export_package(s, sys.argv[2] if len(sys.argv) > 2 else "v1"))
