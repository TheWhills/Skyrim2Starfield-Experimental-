"""What ground textures are at one spot of a Skyrim overlay build (read-only), for "why does the ground look like this".

Give the position `player.getpos x` / `player.getpos y` prints in game, and with --spawn-at the same two values read
right after `coc` (Starfield reports the planet's merged grid; the arrival gives the shift). Prints:
  * Skyrim: the LTEX layers Skyrim paints at the nearest LAND vertex (EditorID, diffuse texture, weight);
  * the build: the quadrant's LTEX table bytes and the sample's 3-bit alphas in the staged BTD, i.e. what Starfield
    draws there, with the Skyrim texture each overridden Starfield LTEX stands for.
With --zip it also writes those Skyrim diffuse (and normal) textures as PNG previews (texconv -ft png) into a zip.

    python -I scripts\\terrain\\ground_at.py --skyrim "<Skyrim SE>\\Data\\Skyrim.esm" ^
        --terrain C:\\Modding\\staging\\skyrim_tamriel --pos 867.06 -1956.06 --spawn-at 900.1 -1900.3 --texconv C:\\Modding\\tools\\texconv.exe ^
        --zip C:\\Modding\\work\\ground_at.zip
"""
import argparse
import json
import os
import struct
import sys
import tempfile
import zipfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import btd, landtex, skyrimground  # noqa: E402
from fo4sf import terrain_grid as tg  # noqa: E402

CELL = 4096.0
STEP = CELL / 32.0                       # Skyrim LAND vertex spacing (units)


def skyrim_layers(esm, xu, yu):
    """[(ltex fid, edid, diffuse, normal, weight)] at the LAND vertex nearest Skyrim position (xu, yu) units."""
    cells, ltex = landtex.read_world_textures(esm)
    cx, cy = int(xu // CELL), int(yu // CELL)
    col = int(round((xu - cx * CELL) / STEP))
    row = int(round((yu - cy * CELL) / STEP))
    ws = cells.get((cx, cy), {})
    out = []
    for fid, w in ws.items():
        v = float(w[min(row, 32), min(col, 32)])
        if v > 0.001:
            info = ltex.get(fid, {"edid": "(engine default)" if fid == 0 else "?", "diffuse": "", "normal": ""})
            out.append((fid, info["edid"], info.get("diffuse", ""), info.get("normal", ""), round(v, 3)))
    return (cx, cy, row, col), sorted(out, key=lambda t: -t[4])


def btd_sample(path, x, y):  # noqa: D401
    """(quadrant LTEX table indices bytes, 3-bit alphas of bytes 0..4, LTEX table, (row, col)) at local metres."""
    with open(path, "rb") as f:
        t = btd.read(f.read())
    n = t.ncx
    o = tg.grid_origin(n)
    c = int((x - o) / tg.SF_STEP_M)
    r = int((y - o) / tg.SF_STEP_M)
    rows, cols = t.weights.shape
    if not (0 <= r < rows and 0 <= c < cols):
        raise SystemExit(f"position ({x}, {y}) is outside the BTD ({cols} x {rows} samples)")
    q = [int(b) for b in t.quad_map[r // 64, c // 64]]
    word = int(t.weights[r, c])
    alphas = [(word >> (3 * i)) & 7 for i in range(5)]
    return q, alphas, list(t.ltex), (r, c)


def hypotheses(q, word, table):
    """[(label, LTEX fid)] the sample shows under each candidate reading: texture index rule (landtex.INDEX_RULES) x
    which alpha bits belong to overlay byte i (bits 3i, or 3(4 - i): fo76utils reverses the five groups on load).
    Alphas count as on at 4 and above (the build's solid blend writes only 0 or 7)."""
    from fo4sf import landtex as lt
    n = len(table)
    out = []
    for rule, order, five in [(r, o, False) for r in lt.INDEX_RULES for o in ("bits 3i", "bits 3(4-i)")] + \
            [("head", "bits 3i", True)]:
        valid = [i for i in range(5 if five else 8) if 0 < q[i] <= n]
        if not valid:
            continue
        if True:
            pick = valid[-1]
            for i in range(5):
                if i == valid[-1] or not 0 < q[i] <= n:
                    continue
                g = i if order == "bits 3i" else 4 - i
                if ((word >> (3 * g)) & 7) >= 4:
                    pick = i
                    break
            out.append((f"index {rule}, alpha {order}" + (", bytes 0..4 only (Starfield)" if five else "")
                        , table[lt.entry_for(q[pick], n, rule)]))
    return out


LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def skyrim_weight_at(cells, xu, yu):
    """{Skyrim LTEX: weight} at Skyrim position (xu, yu) units, bilinear inside the cell holding it."""
    cx, cy = int(xu // CELL), int(yu // CELL)
    ws = cells.get((cx, cy))
    if not ws:
        return {}
    fx, fy = (xu - cx * CELL) / STEP, (yu - cy * CELL) / STEP
    c0, r0 = min(int(fx), 31), min(int(fy), 31)
    tx, ty = fx - c0, fy - r0
    out = {}
    for fid, w in ws.items():
        v = ((w[r0, c0] * (1 - tx) + w[r0, c0 + 1] * tx) * (1 - ty) + (w[r0 + 1, c0] * (1 - tx) + w[r0 + 1, c0 + 1] * tx) * ty)
        if v > 0.001:
            out[fid] = float(v)
    return out


def ground_map(esm, path, pos, origin, radius_m, over_edid, step_m=1.0):
    """Two character maps around pos (overlay metres), north up: what Skyrim paints most (bilinear inside its cell)
    and what the BTD draws, one letter per texture (the same letter for a Skyrim texture and the converted slot that
    stands for it), '+' / '|' / '-' on the BTD's 50 m quadrant edges and ':' on Skyrim's 58.5 m cell edges. Returns
    the lines to print."""
    cells, ltex = landtex.read_world_textures(esm)
    with open(path, "rb") as f:
        t = btd.read(f.read())
    o = tg.grid_origin(t.ncx)
    dec_cache = {}
    letters = {}

    def letter(key, label):
        if key not in letters:
            letters[key] = (LETTERS[len(letters) % len(LETTERS)], label)
        return letters[key][0]

    def drawn(r, c):
        qr, qc = r // 64, c // 64
        if (qr, qc) not in dec_cache:
            dec = landtex.decode_quadrants(t.quad_map[qr:qr + 1, qc:qc + 1], t.weights[qr * 64:(qr + 1) * 64,
                                                                                       qc * 64:(qc + 1) * 64], t.ltex)
            ids = sorted(dec)
            dec_cache[(qr, qc)] = (np.asarray(ids), np.argmax(np.stack([dec[i] for i in ids]), axis=0))
        ids, arg = dec_cache[(qr, qc)]
        return int(ids[arg[r - qr * 64, c - qc * 64]])
    n = int(round(radius_m / step_m))
    sky_rows, btd_rows = [], []
    for j in range(n, -n - 1, -1):
        srow, brow = [], []
        for i in range(-n, n + 1):
            x, y = pos[0] + i * step_m, pos[1] + j * step_m
            xu, yu = (x + origin[0]) * 70.0, (y + origin[1]) * 70.0
            ws = skyrim_weight_at(cells, xu, yu)
            half = 70.0 * step_m / 2
            edge_c = min(xu % CELL, CELL - xu % CELL) < half or min(yu % CELL, CELL - yu % CELL) < half
            if ws:
                f = max(ws, key=ws.get)
                e = ltex.get(f, {}).get("edid", "(engine default)" if f == 0 else f"{f:08X}")
                srow.append(":" if edge_c else letter(e, e))
            else:
                srow.append("?")
            c = int((x - o) / tg.SF_STEP_M)
            r = int((y - o) / tg.SF_STEP_M)
            if not (0 <= r < t.weights.shape[0] and 0 <= c < t.weights.shape[1]):
                brow.append(" ")
                continue
            on_c = c % 64 < step_m / tg.SF_STEP_M
            on_r = r % 64 < step_m / tg.SF_STEP_M
            if on_c or on_r:
                brow.append("+" if on_c and on_r else ("|" if on_c else "-"))
                continue
            sf = drawn(r, c)
            e = over_edid.get(sf, f"{sf:08X} (Starfield)")
            brow.append(letter(e, e))
        sky_rows.append("".join(srow))
        btd_rows.append("".join(brow))
    out = [f"maps {2 * n + 1} x {2 * n + 1} m around the spot (north up, 1 character = {step_m:g} m, the spot in the "
           f"middle); left: what Skyrim paints most, right: what the build draws"]
    for k, (a_, b_) in enumerate(zip(sky_rows, btd_rows)):
        mark = " <" if k == n else ""
        out.append(f"  {a_}   {b_}{mark}")
    out.append("  legend: " + ", ".join(f"{l} {lab}" for _k, (l, lab) in letters.items())
               + "; ':' Skyrim cell edge, '|' '-' '+' the BTD's 50 m quadrant edges")
    qr, qc = int((pos[1] - o) / tg.SF_STEP_M) // 64, int((pos[0] - o) / tg.SF_STEP_M) // 64
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            rr, cc = qr + dr, qc + dc
            if 0 <= rr < t.quad_map.shape[0] and 0 <= cc < t.quad_map.shape[1]:
                q = [int(b) for b in t.quad_map[rr, cc]]
                ids = [t.ltex[landtex.entry_for(b, len(t.ltex))] for b in q[:5] if 0 < b <= len(t.ltex)]
                names = [over_edid.get(f, f"{f:08X}") for f in ids]
                out.append(f"  quadrant ({dr:+d}, {dc:+d}) from the spot's: its five {names}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True, help="Skyrim.esm")
    ap.add_argument("--terrain", required=True, help="the staged overlay build (make_skyrim_overlay.py build --out)")
    ap.add_argument("--pos", type=float, nargs=2, required=True, metavar=("X", "Y"), help="player.getpos x / y")
    ap.add_argument("--spawn-at", type=float, nargs=2, metavar=("X", "Y"),
                    help="player.getpos x / y right after coc, before moving: Starfield reports positions in the "
                         "planet's merged grid, so this gives the shift to the overlay's own frame")
    ap.add_argument("--ltex-index", choices=["head", "tail"], default="head",
                    help="the build's --ltex-index (default head)")
    ap.add_argument("--colours", default="",
                    help="the build's --skyrim-ground-colours string, to print the colour each reading predicts")
    ap.add_argument("--texconv", default="", help="with --zip: texconv.exe for the PNG previews")
    ap.add_argument("--zip", default="", help="write the Skyrim textures found here as PNG previews (outside the repo)")
    ap.add_argument("--map", type=float, default=0.0, metavar="M",
                    help="also print maps of what Skyrim paints and what the build draws within M metres (e.g. 15)")
    a = ap.parse_args(argv)
    with open(os.path.join(a.terrain, "overlays_params.json"), encoding="utf-8") as f:
        prm = json.load(f)
    ov = prm["overlays"][0]
    if a.spawn_at:                                    # planet frame -> overlay frame through the COC marker
        sx, sy = ov["spawn"][:2]
        a.pos = [a.pos[0] - a.spawn_at[0] + sx, a.pos[1] - a.spawn_at[1] + sy]
        print(f"merge shift ({a.spawn_at[0] - sx:.2f}, {a.spawn_at[1] - sy:.2f}) m: overlay position "
              f"({a.pos[0]:.2f}, {a.pos[1]:.2f})")
    ox, oy = (float(v) for v in ov.get("origin_cw_m", [0, 0]))
    xu, yu = (a.pos[0] + ox) * 70.0, (a.pos[1] + oy) * 70.0
    (cx, cy, row, col), layers = skyrim_layers(a.skyrim, xu, yu)
    from fo4sf import terrain_grid as tgrid
    sc = tgrid.sf_cell_of(a.pos[0], a.pos[1])
    wl = {(c[0], c[1]): c[2] for c in (prm.get("water") or {}).get("cells", [])}
    near = sorted(((x, y), h) for (x, y), h in wl.items() if abs(x - sc[0]) <= 1 and abs(y - sc[1]) <= 1)
    print(f"Starfield cell {list(sc)}: water level {wl.get(sc, 'none')}"
          + (f"; neighbours with water {near}" if near else "") + f" (overlay height offset "
          f"{ov.get('height_offset_m', 0)} m)")
    print(f"position {a.pos[0]:g}, {a.pos[1]:g} m -> Skyrim ({xu:.0f}, {yu:.0f}) units, cell ({cx}, {cy}) vertex "
          f"row {row} col {col}")
    print("Skyrim paints here (weight, EditorID, diffuse):")
    for fid, edid, diff, _nrm, w in layers:
        print(f"  {w:5.3f}  {edid:32} {diff}")
    over = {int(o["form_id"]): f"{o['skyrim']}, vanilla record {o.get('vanilla_edid', '?')}"
            for o in prm.get("ltex_overrides", [])}
    q, alphas, table, (r, c) = btd_sample(os.path.join(a.terrain, "Data", "Terrain", f"{ov['world']}.btd"), *a.pos)
    n = len(table)

    def name(b):
        if not b:
            return "-"
        fid = table[landtex.entry_for(b, n, a.ltex_index)]
        return f"{fid:08X}" + (f" (Skyrim {over[fid]})" if fid in over else "")
    print(f"the build draws (BTD sample row {r} col {c}; overlay bytes 0..4 top first, then the base):")
    for i in range(5):
        if q[i] and i != max(j for j in range(8) if q[j]):
            print(f"  overlay {i}: {name(q[i])}  alpha {alphas[i]}/7")
    vb = [i for i in range(8) if q[i]]
    if vb:
        print(f"  base (byte {vb[-1]}): {name(q[vb[-1]])}")
    cols = {k: v for k, v in (p.split("=") for p in a.colours.replace(" ", "").split(",") if "=" in p)} \
        if a.colours else {}
    sky_of = {int(o["form_id"]): o["skyrim"] for o in prm.get("ltex_overrides", [])}
    word = sum(al << (3 * i) for i, al in enumerate(alphas))
    print("what each reading of the file would show at this spot (compare with the screen):")
    for label, fid in hypotheses(q, word, table):
        sk = sky_of.get(fid, "")
        print(f"  {label:34} {sk or f'{fid:08X} (not a Skyrim texture)':30} "
              f"{cols.get(sk.lower(), cols.get(sk, '')) if sk else ''}")
    if a.map > 0:
        over_edid = {int(o_["form_id"]): o_["skyrim"] for o_ in prm.get("ltex_overrides", [])}
        for line in ground_map(a.skyrim, os.path.join(a.terrain, "Data", "Terrain", f"{ov['world']}.btd"), a.pos,
                               (ox, oy), a.map, over_edid):
            print(line)
    if a.zip:
        if not a.texconv:
            sys.exit("--zip needs --texconv for the PNG previews")
        from fo4sf import bsa
        src = bsa.SkyrimArchives(os.path.dirname(os.path.abspath(a.skyrim)))
        os.makedirs(os.path.dirname(os.path.abspath(a.zip)) or ".", exist_ok=True)
        done = 0
        with zipfile.ZipFile(a.zip, "w") as z, tempfile.TemporaryDirectory() as tmp:
            for _fid, edid, diff, nrm, w in layers:
                for kind, p in (("diffuse", diff), ("normal", nrm)):
                    data = src.texture(skyrimground.texture_path(p)) if p else None
                    if data is None:
                        continue
                    dds = os.path.join(tmp, f"{edid}_{kind}.dds")
                    with open(dds, "wb") as f:
                        f.write(data)
                    import subprocess
                    subprocess.run([a.texconv, "-nologo", "-y", "-ft", "png", "-f", "R8G8B8A8_UNORM", "-m", "1",
                                    "-o", tmp, dds], capture_output=True, text=True)
                    png = dds[:-4] + ".png"
                    if os.path.exists(png):
                        z.write(png, f"{w:.2f}_{edid}_{kind}.png")
                        done += 1
            z.writestr("ground_at.txt", json.dumps({"pos": a.pos, "skyrim": layers, "btd": {"bytes": q, "alphas": alphas,
                                                     "table": [f"{t:08X}" for t in table]}}, indent=1))
        print(f"{done} texture previews -> {a.zip}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
