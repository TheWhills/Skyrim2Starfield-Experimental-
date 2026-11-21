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
falloff(d) / falloff(LADDER_HEIGHT_M) = that ladder tile's lumens / TEST_LM. Fixed exposure (LGT_NoLut), no
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
COLS, ROWS = 6, 5
SPACING_M = 10.0
RADIUS_M = 8.0
TILE_M = 1.6
STAND_M = 60.0                                          # the arrival tile, south of the grid, out of view from above
TEST_LM = 4000.0
TEST_HEIGHTS_M = (1.0, 1.5, 2.0, 3.0, 4.0, 6.0)
LADDER_HEIGHT_M = 2.0
LADDER_STEPS = list(range(-11, 7))                      # lumens TEST_LM x 2^(k / 2): 2^-5.5 .. 2^3
FLOOR_RX = re.compile(r"floor", re.I)
SKIP_RX = re.compile(r"candle|rug|trapdoor|door|stair|clutter", re.I)
CALIB_LIGHTING = {"IMAGE_SPACE": "1C6C37", "ADAPT_IS": "0", "ENV_AMBIENT": "0", "CELL_AMBIENT": "template",
                  "LIGHT_ADAPT": "0", "LIGHT_MERGE_M": "0.05", "LIGHT_FLICKER": "subtle", "LIGHT_FALLOFF": "skyrim",
                  "LIGHT_TEMPERATURE": "keep", "OMNI_LIGHT": "3197A6", "LIGHTING_TEMPLATE": "006658"}


def layout():
    """[(role, value, falloff exponent, light height m, lumens)] in grid order: row by row from the far row (y max),
    column by column from x min. Rows 0 - 2: the ladder (18); row 3: test, exponent 1; row 4: test, exponent 2."""
    spots = [("ladder", k, 1.0, LADDER_HEIGHT_M, TEST_LM * 2 ** (k / 2)) for k in LADDER_STEPS]
    spots += [("test_e1", d, 1.0, d, TEST_LM) for d in TEST_HEIGHTS_M]
    spots += [("test_e2", d, 2.0, d, TEST_LM) for d in TEST_HEIGHTS_M]
    assert len(spots) == COLS * ROWS
    return spots


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
                               "flicker": False, "falloff_exponent": fexp, "calib_lumens": round(lm, 1)}})
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
def find_tiles(lum, n, min_frac=0.0004):
    """The n largest bright blobs of a luminance image (2-D numpy array): [(cy, cx, ys, xs)], sorted into the grid
    (rows top to bottom by centre y, then x). Threshold: above the image's 60th percentile x 3 (the black void)."""
    import numpy as np
    thr = max(float(np.percentile(lum, 60)) * 3.0, 2.0 / 255)
    mask = lum > thr
    h, w = mask.shape
    lab = np.zeros((h, w), np.int32)
    blobs, cur = [], 0
    for y0 in range(h):
        row = mask[y0]
        for x0 in np.nonzero(row & (lab[y0] == 0))[0]:
            cur += 1
            stack, pts = [(y0, int(x0))], []
            lab[y0, x0] = cur
            while stack:
                y, x = stack.pop()
                pts.append((y, x))
                for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and lab[yy, xx] == 0:
                        lab[yy, xx] = cur
                        stack.append((yy, xx))
            if len(pts) >= min_frac * h * w:
                ys = np.array([p[0] for p in pts])
                xs = np.array([p[1] for p in pts])
                blobs.append((float(ys.mean()), float(xs.mean()), ys, xs))
    blobs = sorted(blobs, key=lambda b: -len(b[2]))[:n]
    if len(blobs) < n:
        return blobs
    blobs.sort(key=lambda b: b[0])
    rows = [sorted(blobs[i:i + COLS], key=lambda b: b[1]) for i in range(0, n, COLS)]
    return [b for r in rows for b in r]


def tile_value(lum, blob):
    """Median luminance of the middle third of a blob (away from its edges)."""
    import numpy as np
    cy, cx, ys, xs = blob
    ry, rx = (ys.max() - ys.min()) / 6.0, (xs.max() - xs.min()) / 6.0
    sel = (abs(ys - cy) <= ry) & (abs(xs - cx) <= rx)
    return float(np.median(lum[ys[sel], xs[sel]])) if sel.any() else float(np.median(lum[ys, xs]))


def h1(d, r=RADIUS_M):
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
    blobs = find_tiles(lum, len(spots))
    if len(blobs) != len(spots):
        sys.exit(f"found {len(blobs)} tiles, expected {len(spots)}: look straight down with the whole grid in view")
    res = analyze([tile_value(lum, b) for b in blobs], spots)
    print("falloff relative to the ladder height (2 m): measured / H1 inverse square / Skyrim")
    for t in res["tests"]:
        print(f"  {t['role']:8} {t['d']:4.1f} m  {t['measured'] if t['measured'] is not None else 'off ladder':>10}"
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
