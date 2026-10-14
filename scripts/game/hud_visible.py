"""Is the plain in-game HUD showing (no console, no menu)? Prints 'yes' or 'no'.

usage: python hud_visible.py shot.png
In normal play the oxygen ring (bottom left) and the health bar (bottom right) are bright: in shot.ps1's 1280x720 output
about 12% of the ring box and 57% of the bar box are above 215 / 200. The console overlay dims both to ~0, and menus
(Skills, Status) hide them. route_run / readpos check "yes" before pressing the console key and "no" right after, so a
console toggle that the game dropped can never send typed commands into the game or a menu ("p" opens Skills there).
"""
import sys

from PIL import Image


def frac(im, box, threshold):
    w, h = im.size
    sx, sy = w / 1280.0, h / 720.0
    hist = im.crop((int(box[0] * sx), int(box[1] * sy), int(box[2] * sx), int(box[3] * sy))).histogram()
    return sum(hist[threshold:]) / max(sum(hist), 1)


def visible(path):
    im = Image.open(path).convert("L")
    return frac(im, (55, 535, 200, 685), 216) > 0.04 and frac(im, (1020, 628, 1210, 638), 200) > 0.25


if __name__ == "__main__":
    print("yes" if visible(sys.argv[1]) else "no")
