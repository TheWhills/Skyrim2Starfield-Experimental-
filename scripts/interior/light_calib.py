"""Light falloff calibration cell (2026-11-21; docs/interior/lighting-model.md): measures how a Starfield light's
brightness falls with distance, so the converter can match Skyrim's (1 - (d / r)^2) curve in rooms of any size.

    make     --work <batch work>   adds the cell FO4Port_S2SLightCalib to the batch (cells/S2SLightCalib.json,
                                   cells.txt, convert/lighting.json, light_calib_layout.json); riverwood_doors -LightCalib
    analyze  --work <batch work> --shot <screenshot.png>   reads the tiles off a screenshot from straight above

The cell: a 6 x 5 grid of identical floor tiles (one converted Skyrim floor model, scaled to about TILE_M), 10 m apart
in an empty black cell, each under its own light straight above it (N.L = 1), the lights' radius RADIUS_M so no light
reaches a neighbouring tile. Rows of test tiles: one light of TEST_LM lumens at heights TEST_HEIGHTS_M, falloff
exponent 1 (what the converter uses) and 2 (Starfield's vanilla). The other tiles are a ladder: lights at
LADDER_HEIGHT_M whose lumens step by half stops. A test tile is as bright on screen as the ladder tile whose light it
equals, whatever the tone curve and exposure do (both are the same everywhere in one frame, and monotonic), so
falloff(d) / falloff(LADDER_HEIGHT_M) = that ladder tile's lumens / TEST_LM. Result (owner 2026-11-21):
lightmodel.STARFIELD_FALLOFF. Rows 4 and 5 (2026-11-21): the same test lights as spheres (AREA_RADII_M). Fixed exposure (LGT_NoLut), no
environment light, no adaptation in this cell."""
import argparse
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

UNITS_PER_M = 70.0
CELL = "S2SLightCalib"
COLS, ROWS = 6, 6
SPACING_M = 10.0
RADIUS_M = 8.0
TILE_M = 1.6
STAND_M = 60.0                                          # the arrival tile, south of the grid, out of view from above
TEST_LM = 4000.0
TEST_HEIGHTS_M = (1.0, 1.5, 2.0, 3.0, 4.0, 6.0)
LADDER_HEIGHT_M = 2.0
LADDER_STEPS = list(range(-11, 7))                      # lumens TEST_LM x 2^(k / 2): 2^-5.5 .. 2^3
# 2026-11-21 (owner: walls and tables right at a light far too bright): the falloff exponent had no effect, so its row
# became area-light rows: the same test lights as spheres of these radii (Light FLAD, Type Sphere; supported hypothesis:
# metres, like the light's Radius) to measure how much a light's size flattens the curve near it
AREA_RADII_M = (0.5, 1.5)
FLOOR_RX = re.compile(r"floor", re.I)
SKIP_RX = re.compile(r"candle|rug|trapdoor|door|stair|clutter", re.I)
CALIB_LIGHTING = {"IMAGE_SPACE": "1C6C37", "ADAPT_IS": "0", "ENV_AMBIENT": "0", "CELL_AMBIENT": "template",
                  "LIGHT_ADAPT": "0", "LIGHT_MERGE_M": "0.05", "LIGHT_FLICKER": "subtle", "LIGHT_FALLOFF": "skyrim",
                  "LIGHT_TEMPERATURE": "keep", "OMNI_LIGHT": "3197A6", "LIGHTING_TEMPLATE": "006658"}


def layout():
    """[(role, value, falloff exponent, light height m, lumens)] in grid order: row by row from the far row (y max),
    column by column from x min. Rows 0 - 2: the ladder (18); row 3: test, a point light (exponent 1); rows 4, 5: test,
    sphere lights of AREA_RADII_M (role test_a<radius>)."""
    spots = [("ladder", k, 1.0, LADDER_HEIGHT_M, TEST_LM * 2 ** (k / 2)) for k in LADDER_STEPS]
    spots += [("test_e1", d, 1.0, d, TEST_LM) for d in TEST_HEIGHTS_M]
    for r in AREA_RADII_M:
        spots += [(f"test_a{r:g}", d, 1.0, d, TEST_LM) for d in TEST_HEIGHTS_M]
    assert len(spots) == COLS * ROWS
    return spots


def area_radius(role) -> float:
    """The sphere radius (m) of a test_a<radius> role, 0 for any other."""
    return float(role[6:]) if role.startswith("test_a") else 0.0


def spot_xy(i):
    r, c = divmod(i, COLS)
    return ((c - (COLS - 1) / 2) * SPACING_M, ((ROWS - 1) / 2 - r) * SPACING_M)


def pick_floor(manifest):
    """(Skyrim model path relative to meshes\\, source) of a converted floor model: the first whose source names a
    floor and nothing in SKIP_RX, shortest path first (generic pieces)."""
    cands = []
    for it in manifest.get("items", []):
        src = it["source"].replace("/", "\\")
        base = src.rsplit("\\", 1)[-1]
        if FLOOR_RX.search(base) and not SKIP_RX.search(base):
            cands.append(src)
    if not cands:
        return None
    src = sorted(cands, key=lambda s: (len(s), s.lower()))[0]
    rel = re.sub(r"^meshes\\", "", src, flags=re.I)
    return rel, src


def tile_size_m(work, manifest, src):
    """The converted model's horizontal size (m) from its NIF's geometry boxes, None if unreadable."""
    try:
        import make_items
        item = next(i for i in manifest["items"] if i["source"].replace("/", "\\") == src)
        path = os.path.join(work, "convert", "meshes", *item["model"].split("\\"))
        with open(path, "rb") as fh:
            b = make_items.geometry_bounds(fh.read())
        return None if b is None else max(b[1][0] - b[0][0], b[1][1] - b[0][1])
    except (OSError, StopIteration, ImportError, ValueError):
        return None


def cell_json(model_rel, scale):
    refs = [{"formkey": "CALIB:arrival", "type": "Static", "base_editor_id": "COCMarkerHeading", "model": "",
             "pos": [0.0, -STAND_M * UNITS_PER_M, 20.0], "rot": [0.0, 0.0, 0.0], "scale": 1.0,
             "disabled": 0},
            {"formkey": "CALIB:stand", "type": "Static", "base_editor_id": "S2SCalibStand", "model": model_rel,
             "pos": [0.0, -STAND_M * UNITS_PER_M, 0.0], "rot": [0.0, 0.0, 0.0], "scale": scale,
             "disabled": 0}]
    for i, (role, val, fexp, h, lm) in enumerate(layout()):
        x, y = spot_xy(i)
        refs.append({"formkey": f"CALIB:tile{i:02d}", "type": "Static", "base_editor_id": "S2SCalibTile",
                     "model": model_rel, "pos": [x * UNITS_PER_M, y * UNITS_PER_M, 0.0], "rot": [0.0, 0.0, 0.0],
                     "scale": scale, "disabled": 0})
        refs.append({"formkey": f"CALIB:light{i:02d}", "type": "Light", "base_editor_id": "S2SCalibLight",
                     "model": "", "pos": [x * UNITS_PER_M, y * UNITS_PER_M, h * UNITS_PER_M],
                     "rot": [0.0, 0.0, 0.0], "scale": 1.0, "disabled": 0,
                     "light": {"radius": RADIUS_M * UNITS_PER_M, "color": [255, 255, 255], "fade": 1.0,
                               "flicker": False, "falloff_exponent": fexp, "calib_lumens": round(lm, 1),
                               **({"area_radius_m": area_radius(role)} if area_radius(role) else {})}})
    return {"schema_version": 2, "cell": CELL, "cell_formkey": None, "refs": refs}


def cmd_make(a):
    work = a.work
    with open(os.path.join(work, "convert", "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    pick = pick_floor(manifest)
    if pick is None:
        sys.exit("no converted floor model in the manifest (convert the batch first)")
    model_rel, src = pick
    size = tile_size_m(work, manifest, src)
    scale = round(min(1.0, TILE_M / size), 3) if size else 0.3
    cell = cell_json(model_rel, scale)
    path = os.path.join(work, "cells", CELL + ".json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cell, fh, indent=1)
    txt = os.path.join(work, "cells.txt")
    lines = []
    if os.path.exists(txt):
        with open(txt, encoding="utf-8") as fh:
            lines = [ln.strip() for ln in fh]
    lines = [ln for ln in lines if ln and not ln.endswith(CELL + ".json")] + [path]
    with open(txt, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    lj = os.path.join(work, "convert", "lighting.json")
    cfg = {}
    if os.path.exists(lj):
        with open(lj, encoding="utf-8") as fh:
            cfg = json.load(fh)
    cfg[CELL] = dict(CALIB_LIGHTING)
    with open(lj, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=1)
    with open(os.path.join(work, "light_calib_layout.json"), "w", encoding="utf-8") as fh:
        json.dump({"model": model_rel, "scale": scale, "tile_m": size, "cols": COLS, "rows": ROWS,
                   "spots": [dict(zip(("role", "value", "falloff_exponent", "height_m", "lumens"), s))
                             for s in layout()]}, fh, indent=1)
    print(f"light calibration cell FO4Port_{CELL}: {COLS * ROWS} tiles of {model_rel} x{scale} "
          f"({size or 0:.2f} m model), {SPACING_M:g} m apart -> {path}")


# ---- analyze ------------------------------------------------------------------------------------------------------
def find_tiles(rgb, n):
    """The tiles of a screenshot (H x W x 3, 0..1): [(cy, cx, ys, xs)] in grid order (row 0 = the far row, north).
    The cell's void renders flat grey (owner 2026-11-21): a tile is any blob that differs from the image's median colour;
    the n (+1: the arrival tile) largest are kept. With the arrival tile in view it marks south, so a view looking back
    the other way is turned round; without it, north is up."""
    import numpy as np
    bg = np.median(rgb.reshape(-1, 3), 0)
    mask = np.abs(rgb - bg).max(2) > 0.03
    for _ in range(4):                                    # close gaps in pale tiles (4-neighbour dilation)
        m = mask.copy()
        m[1:] |= mask[:-1]
        m[:-1] |= mask[1:]
        m[:, 1:] |= mask[:, :-1]
        m[:, :-1] |= mask[:, 1:]
        mask = m
    h, w = mask.shape
    seen = np.zeros((h, w), bool)
    blobs = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        stack, ys, xs = [(int(y0), int(x0))], [], []
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop()
            ys.append(y)
            xs.append(x)
            for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not seen[yy, xx]:
                    seen[yy, xx] = True
                    stack.append((yy, xx))
        ys, xs = np.array(ys), np.array(xs)
        blobs.append(((ys.min() + ys.max()) / 2.0, (xs.min() + xs.max()) / 2.0, ys, xs))
    blobs = sorted(blobs, key=lambda b: -len(b[2]))[:n + 1]
    flip = False
    if len(blobs) == n + 1:
        # the arrival tile is 4 grid steps south of the grid: the blob farthest from its nearest neighbour
        def nn(b):
            return min(math.hypot(b[0] - o[0], b[1] - o[1]) for o in blobs if o is not b)
        gaps = sorted(nn(b) for b in blobs)
        stand = max(blobs, key=nn)
        if nn(stand) > 2.0 * gaps[len(gaps) // 2]:
            cy = float(np.median([b[0] for b in blobs if b is not stand]))
            blobs = [b for b in blobs if b is not stand]
            flip = stand[0] < cy                          # the arrival tile (south) at the top: looking back north->south
        else:
            blobs = blobs[:n]
    if len(blobs) < n:
        return blobs
    blobs = blobs[:n]
    sgn = -1 if flip else 1
    blobs.sort(key=lambda b: sgn * b[0])
    rows = [sorted(blobs[i:i + COLS], key=lambda b: sgn * b[1]) for i in range(0, n, COLS)]
    return [b for r in rows for b in r]


def tile_value(lum, blob):
    """Median luminance of the middle 40 % of a blob's box (inside the tile whatever its outline)."""
    import numpy as np
    cy, cx, ys, xs = blob
    ry, rx = max(1, (ys.max() - ys.min()) * 0.2), max(1, (xs.max() - xs.min()) * 0.2)
    return float(np.median(lum[int(cy - ry):int(cy + ry) + 1, int(cx - rx):int(cx + rx) + 1]))


def h1(d, r=RADIUS_M):
    """The first hypothesis (windowed inverse square), kept for the printout."""
    return max(0.0, 1 - (d / r) ** 4) ** 2 / (d * d)


def skyrim(d, r=RADIUS_M):
    return max(0.0, 1 - (d / r) ** 2)


def analyze(values, spots):
    """{"ladder": [(log2 lumens ratio, value)], "tests": [{role, d, measured, h1, skyrim}]}: each test tile's value
    read off the ladder (piecewise linear in log2 lumens), as falloff(d) / falloff(LADDER_HEIGHT_M)."""
    lad = sorted(((math.log2(s[4] / TEST_LM), v) for s, v in zip(spots, values) if s[0] == "ladder"),
                 key=lambda t: t[1])
    out = {"ladder": lad, "tests": []}
    for s, v in zip(spots, values):
        if not s[0].startswith("test"):
            continue
        m = None
        for (l0, v0), (l1, v1) in zip(lad, lad[1:]):
            if v0 <= v <= v1 and v1 > v0:
                m = 2 ** (l0 + (l1 - l0) * (v - v0) / (v1 - v0))
                break
        d = s[1]
        out["tests"].append({"role": s[0], "d": d, "value": round(v, 5),
                             "measured": None if m is None else round(m, 4),
                             "h1": round(h1(d) / h1(LADDER_HEIGHT_M), 4),
                             "skyrim": round(skyrim(d) / skyrim(LADDER_HEIGHT_M), 4)})
    return out


def cmd_analyze(a):
    import numpy as np
    from PIL import Image
    img = np.asarray(Image.open(a.shot).convert("RGB")).astype(float) / 255
    lin = np.where(img <= 0.04045, img / 12.92, ((img + 0.055) / 1.055) ** 2.4)
    lum = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
    with open(os.path.join(a.work, "light_calib_layout.json"), encoding="utf-8") as fh:
        spots = [tuple(s[k] for k in ("role", "value", "falloff_exponent", "height_m", "lumens"))
                 for s in json.load(fh)["spots"]]
    blobs = find_tiles(img, len(spots))
    if len(blobs) != len(spots):
        sys.exit(f"found {len(blobs)} tiles, expected {len(spots)}: look straight down with the whole grid in view")
    res = analyze([tile_value(lum, b) for b in blobs], spots)
    print("falloff relative to the ladder height (2 m): measured / H1 inverse square / Skyrim")
    for t in res["tests"]:
        print(f"  {t['role']:9} {t['d']:4.1f} m  {t['measured'] if t['measured'] is not None else 'off ladder':>10}"
              f"  {t['h1']:8.3f}  {t['skyrim']:8.3f}")
    out = os.path.join(a.work, "light_calib_result.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    print(f"written: {out}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("make", "analyze"))
    ap.add_argument("--work", required=True)
    ap.add_argument("--shot", help="analyze: the screenshot")
    a = ap.parse_args(argv)
    return cmd_make(a) if a.cmd == "make" else cmd_analyze(a)


if __name__ == "__main__":
    sys.exit(main())
