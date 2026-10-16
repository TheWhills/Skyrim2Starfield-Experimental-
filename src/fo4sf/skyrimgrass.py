"""Skyrim's grass on the Tamriel overlay (make_skyrim_objects.py grass; docs/terrain/skyrim-objects.md "Grass").

Skyrim (UESP "Skyrim Mod:Mod File Format/LTEX", "GRAS"; verified only on synthetic files here): a landscape texture
lists the grass that grows on it (LTEX GNAM, one GRAS FormID each). A GRAS names a model (MODL) and DATA (32 bytes):
density u8 (percent), min slope u8, max slope u8 (degrees), u8, units from water u16, u16, water rule u32,
position range f32 (units of random offset), height range f32 (scale variation), colour range f32, wave period f32,
flags u8 (1 vertex lighting, 2 uniform scaling, 4 fit to slope), 3 bytes. The engine scatters it at run time on a grid
wherever the texture is painted.

Starfield has no run-time grass for a custom BTD overlay, so the scatter happens here, once: per Skyrim cell, a
jittered grid (--grass-spacing) picks a painted texture by its weight, one of its grasses, and keeps the point with
the grass's density (scaled by --grass-density), inside its slope range and above the cell's water. All instances
of one grass model in one cell are merged into ONE static mesh (a "patch") placed by one reference, so a cell costs
a few references instead of thousands. Patches have no collision.
"""
import math
import re
import struct
from typing import Dict, List, Optional, Tuple

import numpy as np

from fo4sf import fo4land

CELL = fo4land.CELL_UNITS                     # 4096 units per Skyrim cell
STEP = CELL / 32.0                            # LAND vertex spacing
FIT_TO_SLOPE, UNIFORM_SCALE = 4, 2


def parse_gras_data(d: bytes) -> dict:
    if len(d) < 32:
        raise ValueError(f"GRAS DATA is {len(d)} bytes, expected 32")
    (density, min_slope, max_slope, _u, from_water, _u2, water_rule, pos_range, height_range, colour_range,
     wave, flags) = struct.unpack_from("<BBBBHHIffffB", d)
    return {"density": density, "min_slope": min_slope, "max_slope": max_slope, "units_from_water": from_water,
            "water_rule": water_rule, "position_range": pos_range, "height_range": height_range,
            "colour_range": colour_range, "wave_period": wave, "flags": flags}


def read_grass(esm: str) -> Tuple[Dict[int, List[int]], Dict[int, dict]]:
    """({LTEX fid: [GRAS fid, ...]}, {GRAS fid: {"edid", "model", DATA fields}}) of one plugin."""
    ltex_grass, gras = {}, {}
    with fo4land.Plugin(esm) as p:
        for sig in (b"LTEX", b"GRAS"):
            rng = p.top_group(sig)
            if rng is None:
                continue
            for typ, off, _fl, fid in fo4land.iter_items(p.buf, *rng):
                if typ == "GRUP":
                    continue
                subs = list(fo4land.iter_subrecords(fo4land.record_data(p.buf, off)))
                if sig == b"LTEX":
                    g = [struct.unpack_from("<I", d)[0] for s, d in subs if s == b"GNAM" and len(d) >= 4]
                    if g:
                        ltex_grass[fid] = g
                else:
                    f = dict(subs)
                    if b"MODL" not in f or b"DATA" not in f:
                        continue
                    rec = parse_gras_data(f[b"DATA"])
                    rec.update(edid=fo4land.zstring(f.get(b"EDID", b"")), model=fo4land.zstring(f[b"MODL"]))
                    gras[fid] = rec
    return ltex_grass, gras


def _bilinear(g: np.ndarray, u: float, v: float) -> float:
    """g (33, 33) [row = y, col = x] at fractional vertex coordinates (u = x, v = y)."""
    c0, r0 = min(int(u), 31), min(int(v), 31)
    fu, fv = u - c0, v - r0
    return float(g[r0, c0] * (1 - fu) * (1 - fv) + g[r0, c0 + 1] * fu * (1 - fv) +
                 g[r0 + 1, c0] * (1 - fu) * fv + g[r0 + 1, c0 + 1] * fu * fv)


def scatter(weights: Dict[int, np.ndarray], heights: np.ndarray, ltex_grass: Dict[int, List[int]],
            gras: Dict[int, dict], spacing: float, rng: np.random.Generator, density_scale: float = 1.0,
            water: Optional[float] = None) -> List[tuple]:
    """[(GRAS fid, x, y, z, yaw, scale)] in units inside one cell (x, y from its south-west corner; z absolute)."""
    grown = [f for f in weights if any(g in gras for g in ltex_grass.get(f, []))]
    if not grown:
        return []
    out = []
    n = max(1, int(CELL // spacing))
    fids = list(weights)
    for j in range(n):
        for i in range(n):
            x = (i + rng.random()) * spacing
            y = (j + rng.random()) * spacing
            u, v = x / STEP, y / STEP
            w = np.array([max(_bilinear(weights[f], u, v), 0.0) for f in fids])
            tot = w.sum()
            if tot <= 0:
                continue
            f = fids[int(rng.choice(len(fids), p=w / tot))]
            choices = [g for g in ltex_grass.get(f, []) if g in gras]
            if not choices:
                continue
            g = choices[int(rng.integers(len(choices)))]
            gr = gras[g]
            if rng.random() >= gr["density"] / 100.0 * density_scale:
                continue
            ua, ub, va, vb = max(u - 0.5, 0.0), min(u + 0.5, 32.0), max(v - 0.5, 0.0), min(v + 0.5, 32.0)
            dzdx = (_bilinear(heights, ub, v) - _bilinear(heights, ua, v)) / ((ub - ua) * STEP)
            dzdy = (_bilinear(heights, u, vb) - _bilinear(heights, u, va)) / ((vb - va) * STEP)
            slope = math.degrees(math.atan(math.hypot(dzdx, dzdy)))
            if not gr["min_slope"] <= slope <= max(gr["max_slope"], gr["min_slope"]):
                continue
            jitter = gr["position_range"]
            px = min(max(x + (rng.random() * 2 - 1) * jitter, 0.0), CELL)
            py = min(max(y + (rng.random() * 2 - 1) * jitter, 0.0), CELL)
            z = _bilinear(heights, px / STEP, py / STEP)
            if water is not None and z < water + gr["units_from_water"] * (gr["water_rule"] == 0):
                continue
            scale = max(0.3, 1.0 + (rng.random() * 2 - 1) * 0.5 * gr["height_range"])
            out.append((g, px, py, z, rng.random() * 2 * math.pi, scale))
    return out


def instance_shapes(shapes, instances, origin, max_vertices: int):
    """Merge instances [(x, y, z, yaw, scale)] (units) of a model's shapes (nif.Fo4Shape, own transforms) into new
    shapes with identity transforms, positions relative to `origin`, each at most max_vertices vertices.
    Returns [(index of the source shape, merged shape)]."""
    import dataclasses
    out = []
    for si, s in enumerate(shapes):
        r = np.array(s.rotation, np.float64).reshape(3, 3)
        base = (np.array(s.positions, np.float64) @ r.T) * s.scale + np.array(s.translation, np.float64)
        nrm = np.array(s.normals, np.float64) @ r.T if s.normals else None
        tan = np.array(s.tangents, np.float64) @ r.T if s.tangents else None
        nv = len(base)
        if nv == 0 or nv > max_vertices:
            continue
        per = max(1, max_vertices // nv)
        for k in range(0, len(instances), per):
            pos, nr, tg, tris = [], [], [], []
            for m, (x, y, z, yaw, sc) in enumerate(instances[k:k + per]):
                c, sn = math.cos(yaw), math.sin(yaw)
                rz = np.array([[c, -sn, 0.0], [sn, c, 0.0], [0.0, 0.0, 1.0]])
                pos.append(base @ rz.T * sc + (x - origin[0], y - origin[1], z - origin[2]))
                if nrm is not None:
                    nr.append(nrm @ rz.T)
                if tan is not None:
                    tg.append(tan @ rz.T)
                tris += [(a + m * nv, b + m * nv, cc + m * nv) for a, b, cc in s.triangles]
            cnt = len(pos)
            out.append((si, dataclasses.replace(
                s, translation=(0.0, 0.0, 0.0), rotation=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0), scale=1.0,
                positions=[tuple(p) for p in np.concatenate(pos)],
                normals=[tuple(v) for v in np.concatenate(nr)] if nr else [],
                tangents=[tuple(v) for v in np.concatenate(tg)] if tg else [],
                uvs=list(s.uvs) * cnt if s.uvs else s.uvs,
                colors=list(s.colors) * cnt if s.colors else s.colors,
                triangles=tris)))
    return out


def vertex_colour(vc: np.ndarray, x: float, y: float) -> tuple:
    """A cell's VCLR (33, 33, 3) uint8 at (x, y) units from its south-west corner, as 0..1 RGB (bilinear)."""
    u, v = min(max(x / STEP, 0.0), 32.0), min(max(y / STEP, 0.0), 32.0)
    return tuple(_bilinear(vc[..., k].astype(np.float64), u, v) / 255.0 for k in range(3))


def patch_stem(cx: int, cy: int, model: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "_", model.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()).strip("_")
    return f"c{cx}_{cy}".replace("-", "m") + "_" + stem
