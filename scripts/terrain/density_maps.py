"""Biome-mask density maps for the staged Skyrim terrain (test, 2026-11-23).

Starfield ships, per terrain source block, six soft 0-255 masks in Starfield - DensityMaps.ba2:
textures\\terrain\\<folder>\\<block>_{base,flatinner,flatouter,flow,solid,talus}.dds (block = the BTD's file name,
folder = its sub-folder under Data\\TERRAIN; 100 px per cell, legacy BC4, one mip; owner's samples, decoded). Our
world has none. In game (owner, 2026-11-23), ground cover on our terrain grows only in small spots near banks and
edges, whichever mask quadrant byte 6 names (FlatOut -> mask 2 only, Base -> mask 0 only) and on every texture
(control): a per-spot density from somewhere else. Supported hypothesis: the missing density maps. This writes a
uniform set (every pixel = --value) for the staged BTD, at the path the vanilla naming gives
(Data\\TERRAIN\\SKY_Tamriel.btd -> textures\\terrain\\sky_tamriel_<mask>.dds) and, with --layout both, also in a
folder named after the world (textures\\terrain\\sky_tamriel\\sky_tamriel_<mask>.dds). `remove` deletes them.
The exterior has to be reinstalled afterwards (tools\\owner\\terrain_density.ps1 does both).

    python -I scripts\\terrain\\density_maps.py uniform --staging C:\\Modding\\staging\\skyrim_all --value 255
    python -I scripts\\terrain\\density_maps.py remove --staging C:\\Modding\\staging\\skyrim_all
"""
import argparse
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

MASKS = ("base", "flatinner", "flatouter", "flow", "solid", "talus")
PX_PER_CELL = 100


def uniform_bc4_dds(width: int, height: int, value: int) -> bytes:
    """A legacy-header BC4 ('BC4U') DDS, one mip, every pixel = value (like vanilla density maps)."""
    if width % 4 or height % 4:
        raise ValueError("width and height must be multiples of 4")
    v = max(0, min(255, int(value)))
    nblocks = (width // 4) * (height // 4)
    hdr = bytearray(124)
    struct.pack_into("<IIIIIII", hdr, 0, 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000, height, width, nblocks * 8, 0, 1)
    struct.pack_into("<II4s", hdr, 72, 32, 0x4, b"BC4U")
    struct.pack_into("<I", hdr, 104, 0x1000)
    return b"DDS " + bytes(hdr) + bytes((v, v, 0, 0, 0, 0, 0, 0)) * nblocks


def targets(staging, layout="both"):
    """[(world lower, relative paths per mask)] for the staged BTD (overlays_params.json btd_file)."""
    with open(os.path.join(staging, "overlays_params.json"), encoding="utf-8") as f:
        prm = json.load(f)
    out = []
    for o in prm["overlays"]:
        stem = os.path.splitext(os.path.basename(o["btd_file"]))[0].lower()
        rels = [f"Data/textures/terrain/{stem}_{m}.dds" for m in MASKS]
        if layout == "both":
            rels += [f"Data/textures/terrain/{stem}/{stem}_{m}.dds" for m in MASKS]
        out.append((stem, os.path.join(staging, *o["btd_file"].split("/")), rels))
    return out


def btd_cells(path):
    """(cells x, cells y) of a BTD from its quadrant map (two quadrants per cell)."""
    from fo4sf import btd
    with open(path, "rb") as f:
        t = btd.read(f.read())
    return t.quad_map.shape[1] // 2, t.quad_map.shape[0] // 2


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["uniform", "remove"])
    ap.add_argument("--staging", required=True)
    ap.add_argument("--value", type=int, default=255)
    ap.add_argument("--layout", choices=["flat", "both"], default="both")
    ap.add_argument("--cells", type=int, nargs=2, metavar=("X", "Y"), help="BTD cells (default: read the BTD)")
    a = ap.parse_args(argv)
    n = 0
    for stem, btd_path, rels in targets(a.staging, "both" if a.cmd == "remove" else a.layout):
        if a.cmd == "remove":
            for rel in rels:
                p = os.path.join(a.staging, *rel.split("/"))
                if os.path.exists(p):
                    os.remove(p)
                    n += 1
            continue
        cx, cy = a.cells if a.cells else btd_cells(btd_path)
        data = uniform_bc4_dds(cx * PX_PER_CELL, cy * PX_PER_CELL, a.value)
        for rel in rels:
            p = os.path.join(a.staging, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data)
            n += 1
        print(f"{stem}: {cx} x {cy} cells -> {cx * PX_PER_CELL} x {cy * PX_PER_CELL} px, value {a.value}, "
              f"{len(rels)} files ({len(data) / 1e6:.1f} MB each)")
    print(f"{'removed' if a.cmd == 'remove' else 'wrote'} {n} density map(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
