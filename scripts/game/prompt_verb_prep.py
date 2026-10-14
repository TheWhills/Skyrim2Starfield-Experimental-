"""Prepare the activation prompt's verb ("OPEN" / "CLOSE") for OCR: crop, keep only near-white text, invert to black
on white, enlarge. The raw crop failed on bright backgrounds (Parsons wallpaper): OCR returned nothing for "OPEN".

usage: python prompt_verb_prep.py shot.png out.png
"""
import sys

from PIL import Image

THRESHOLD = 150


def prep(src, dst):
    im = Image.open(src).convert("L")
    w, h = im.size
    sx, sy = w / 1280.0, h / 720.0
    crop = im.crop((int(950 * sx), int(203 * sy), int(1036 * sx), int(222 * sy)))   # verb left of the [E] key box
    big = crop.resize((crop.width * 5, crop.height * 5), Image.LANCZOS)             # smooth first: thin glyph strokes
    bw = big.point(lambda p: 0 if p > THRESHOLD else 255)                           # white text -> black on white
    canvas = Image.new("L", (bw.width + 40, bw.height + 40), 255)                   # margin helps the OCR engine
    canvas.paste(bw, (20, 20))
    canvas.save(dst)


if __name__ == "__main__":
    prep(sys.argv[1], sys.argv[2])
