"""DDS facts for comparing converted textures with vanilla Starfield ones (read-only): DXGI format (sRGB or not), size,
mip count, and the average colour / alpha of the top mip when it can be decoded here (uncompressed, or BC1 / BC3 / BC4 /
BC5). Files can be loose paths or names inside Starfield's texture archives (--sf-data).

    python -I scripts\\tools\\dds_info.py --sf-data "<Starfield>\\Data" ^
        textures\\Landscape\\Ground\\Dirt\\DirtFootprints01_color.dds ^
        C:\\Modding\\staging\\skyrim_tamriel\\Data\\textures\\skyrim\\ground\\ldirt02_color.dds
"""
import argparse
import glob
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import ba2, textures  # noqa: E402

DXGI = {28: "R8G8B8A8_UNORM", 29: "R8G8B8A8_UNORM_SRGB", 71: "BC1_UNORM", 72: "BC1_UNORM_SRGB", 74: "BC2_UNORM",
        75: "BC2_UNORM_SRGB", 77: "BC3_UNORM", 78: "BC3_UNORM_SRGB", 80: "BC4_UNORM", 81: "BC4_SNORM",
        83: "BC5_UNORM", 84: "BC5_SNORM", 95: "BC6H_UF16", 98: "BC7_UNORM", 99: "BC7_UNORM_SRGB", 61: "R8_UNORM"}


def _bc1_colours(block):
    c0, c1 = struct.unpack_from("<HH", block)

    def rgb(c):
        return (((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31)
    return rgb(c0), rgb(c1)


def average(data, h):
    """Rough average RGB(A) of the top mip from block endpoints (BC1 / BC3 / BC7 skipped) or raw pixels."""
    off, w, hh = h["data_offset"], h["width"], h["height"]
    fmt = h["dxgi"]
    if fmt in (28, 29):
        n = w * hh
        px = data[off:off + n * 4]
        return [round(sum(px[i::4]) / max(1, n), 1) for i in range(4)]
    if fmt in (71, 72, 77, 78):
        bs = 8 if fmt in (71, 72) else 16
        nb = max(1, w // 4) * max(1, hh // 4)
        tot, alpha, k = [0, 0, 0], 0.0, 0
        for b in range(0, min(nb, 65536)):
            blk = data[off + b * bs: off + (b + 1) * bs]
            if len(blk) < bs:
                break
            col = blk[8:] if bs == 16 else blk
            a, c = _bc1_colours(col)
            for i in range(3):
                tot[i] += (a[i] + c[i]) / 2
            if bs == 16:
                alpha += (blk[0] + blk[1]) / 2
            k += 1
        return [round(t / max(1, k), 1) for t in tot] + ([round(alpha / max(1, k), 1)] if bs == 16 else [])
    return None


def find_in_archives(sf_data, name):
    for p in sorted(glob.glob(os.path.join(sf_data, "Starfield - Textures*.ba2"))) + \
            sorted(glob.glob(os.path.join(sf_data, "*.ba2"))):
        try:
            a = ba2.Ba2(p)
        except Exception:                         # noqa: BLE001
            continue
        i = a.find(name)
        if i is not None:
            return a.read(i), os.path.basename(p)
    return None, None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sf-data", default="", help="Starfield Data folder (for archive names)")
    ap.add_argument("files", nargs="+")
    a = ap.parse_args(argv)
    for f in a.files:
        if os.path.isfile(f):
            data, where = open(f, "rb").read(), "loose"
        elif a.sf_data:
            data, where = find_in_archives(a.sf_data, f.replace("/", "\\"))
        else:
            data, where = None, None
        if data is None:
            print(f"{f}: not found")
            continue
        try:
            h = textures.read_dds_header(data)
        except Exception as e:                    # noqa: BLE001
            print(f"{f}: not a DDS ({e})")
            continue
        fmt = DXGI.get(h["dxgi"], h.get("fourcc") or h["dxgi"])
        print(f"{f}  [{where}]\n   {h['width']} x {h['height']}, mips {h.get('mips')}, format {fmt}, "
              f"average RGB(A) {average(data, h)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
