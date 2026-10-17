from pathlib import Path

from ai_director.common.io import read_json
from ai_director.common.schemas import Brand

FONT_SIZE = {"small": 13, "medium": 15, "large": 18}
FONT_SIZE_916 = {"small": 8, "medium": 9, "large": 11}


def load_brand(session_dir):
    """brand.json logo / intro / outro """
    s = Path(session_dir)
    b = Brand.model_validate(read_json(s / "brand.json") if (s / "brand.json").exists() else {}).model_dump()
    for key in ("logo", "intro", "outro"):
        if b[key] and not (s / b[key]).is_file():
            b[key] = None
    return b


def ass_colour(hex_rgb, alpha=0):
    h = hex_rgb.lstrip("#")
    if len(h) != 6 or any(c not in "0123456789abcdefABCDEF" for c in h):
        raise ValueError(f"a colour must look like #RRGGBB, not {hex_rgb!r}")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def caption_fields(b, vertical=False):
    """Default white text, 50% dark box"""
    c = b["captions"]
    box = c["box"]
    return {"FontSize": (FONT_SIZE_916 if vertical else FONT_SIZE)[c["size"]],
            "PrimaryColour": ass_colour(c["text_color"]),
            "OutlineColour": ass_colour(c["box_color"], 0x80 if box else 0),
            "BackColour": ass_colour(c["box_color"], 0x80 if box else 0),
            "BorderStyle": 3 if box else 1, "Outline": 1, "Shadow": 0}


def force_style(session_dir, vertical=False):
    from ai_director.audio.subtitles import FONT
    f = caption_fields(load_brand(session_dir), vertical)
    return (f"FontName={FONT},FontSize={f['FontSize']},PrimaryColour={f['PrimaryColour']},"
            f"BorderStyle={f['BorderStyle']},OutlineColour={f['OutlineColour']},Outline={f['Outline']},"
            f"Shadow={f['Shadow']},MarginV=30,Encoding=-1")


def logo_overlay(b, inp, width, out):
    lw = max(2, round(width * b["logo_size"] / 2) * 2)
    m = round(width * 0.025)
    x = m if "left" in b["logo_corner"] else f"main_w-overlay_w-{m}"
    y = m if "top" in b["logo_corner"] else f"main_h-overlay_h-{m}"
    return f"[{inp}:v]scale={lw}:-1,format=rgba[logo];", f"overlay=x={x}:y={y}[{out}]"
