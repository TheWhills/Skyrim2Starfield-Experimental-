"""Make console text OCR-friendly: keep bright, low-saturation pixels (the console font) as black on white, upscale 2x.
usage: ocr_prep.py <in.png> <out.png> [min_brightness=145] [max_saturation=35]"""
import sys

import numpy as np
from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
lo = int(sys.argv[3]) if len(sys.argv) > 3 else 145
sat = int(sys.argv[4]) if len(sys.argv) > 4 else 35
a = np.asarray(Image.open(src).convert("RGB")).astype(np.int16)
mx, mn = a.max(axis=2), a.min(axis=2)
text = (mx > lo) & ((mx - mn) < sat)
out = np.where(text, 0, 255).astype(np.uint8)
Image.fromarray(out).resize((out.shape[1] * 2, out.shape[0] * 2), Image.NEAREST).save(dst)
