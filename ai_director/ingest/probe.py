import json

from ai_director.common.io import run


def probe(path):
    out = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    info = json.loads(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    return {"width": v["width"], "height": v["height"], "duration": float(info["format"]["duration"])}