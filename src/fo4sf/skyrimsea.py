"""Distant sea for the Skyrim overlay (make_skyrim_objects.py lod; docs/terrain/skyrim-objects.md "Distant sea").

Why: Starfield cell water draws only in the cells loaded round the player (owner's Jemison views: past them the sea
floor showed dry, icebergs on it), and the planet's own ocean is no way out: on an ocean spot of Jemison the engine
walls the player in ("You cannot go that way" in Riverwood) and floods the coast (owner's test at lat -0.15).

What: flat statics at Skyrim's sea level (a little below the cell water, so up close the real water draws over them)
covering the overlay in tiles, plus strips and corners reaching `reach_m` past its edges; they go into object LOD
like any big static, so the game draws them at every distance. Land hides them wherever it is above the sea.
One-sided, facing up (counter-clockwise seen from above, the winding our converted Skyrim models keep and that draws
in game), so from under the water they are invisible. Material: our own (template .mat from ContentResources) with a
dark sea colour, tiling wave normals and low roughness. Supported hypothesis, not yet seen in game: how water-like it
looks from afar.
"""
import math
import os
import shutil
import tempfile
from typing import Dict, List, Tuple

import numpy as np

from fo4sf import convert_material as cm, convert_static, nif as nifmod, sfmesh, sfnif, textures

EDID_PREFIX = "SKY_DistantSea"
SRC_PREFIX = "distant_sea:"
MODEL_DIR = "skyrim\\distantsea"
TEX_REL = "textures/skyrim/distantsea/sea"
MAT_REL = "materials/skyrim/distantsea/sea.mat"
WAVE_M = 48.0          # one repeat of the wave normal map (16 m showed a visible grid from afar, owner)
OVERLAP_M = 2.0        # neighbouring pieces overlap, so position quantisation leaves no cracks
COLOUR = (12, 34, 46)  # sRGB, dark sea (22, 48, 58 read pale / milky next to the cell water, owner)
ROUGHNESS = 60         # 0..255, low = glossy / reflective


def tile_layout(cell_min: int, cell_max: int, target_cells: int = 8) -> Tuple[float, int, float]:
    """(tile size m, tiles per side, south-west corner m) covering cells cell_min..cell_max exactly."""
    n = cell_max - cell_min + 1
    k = max(1, math.ceil(n / target_cells))
    return n * 100.0 / k, k, cell_min * 100.0


def quads(x0: float, x1: float, y0: float, y1: float, z: float, step: float):
    """Grid of quads over [x0, x1] x [y0, y1] at height z, each quad with its own UVs 0..size / WAVE_M rounded to a whole
    number of repeats (the texture tiles seamlessly; half-float UVs stay small). Returns (positions, uvs, triangles)."""
    nx, ny = max(1, round((x1 - x0) / step)), max(1, round((y1 - y0) / step))
    xs, ys = np.linspace(x0, x1, nx + 1), np.linspace(y0, y1, ny + 1)
    reps_u = max(1, round((x1 - x0) / nx / WAVE_M))
    reps_v = max(1, round((y1 - y0) / ny / WAVE_M))
    pos, uv, tris = [], [], []
    for j in range(ny):
        for i in range(nx):
            b = len(pos)
            pos += [(xs[i], ys[j], z), (xs[i + 1], ys[j], z), (xs[i + 1], ys[j + 1], z), (xs[i], ys[j + 1], z)]
            uv += [(0.0, float(reps_v)), (float(reps_u), float(reps_v)), (float(reps_u), 0.0), (0.0, 0.0)]
            tris += [(b, b + 1, b + 2), (b, b + 2, b + 3)]          # counter-clockwise seen from above (+z)
    return pos, uv, tris


def mesh_bytes(pos, uv, tris, double_sided: bool = False) -> Tuple[bytes, float, list]:
    if double_sided:
        tris = tris + [(a, c, b) for a, b, c in tris]
    m = sfmesh.SfMesh(version=2)
    m.scale, m.positions = sfmesh.encode_positions([tuple(map(float, p)) for p in pos])
    m.triangles = [tuple(t) for t in tris]
    m.uv1 = [(sfmesh.float_to_half(u), sfmesh.float_to_half(v)) for u, v in uv]
    m.normals = [sfmesh.encode_packed(0.0, 0.0, 1.0, w=1.0 / 3.0)] * len(pos)
    m.tangents = [sfmesh.encode_packed(1.0, 0.0, 0.0, w=1.0)] * len(pos)
    sfmesh.build_meshlets(m)
    return sfmesh.serialize(m), m.scale, m.positions


def write_model(data_dir: str, name: str, pos, uv, tris, material: str, double_sided: bool = False) -> Tuple[str, list]:
    """Write geometries/<hash>.mesh and meshes/<MODEL_DIR>/<name>.nif; returns (model path under meshes, bounds)."""
    data, scale, raw = mesh_bytes(pos, uv, tris, double_sided)
    d, fn = convert_static.mesh_file_path(data)
    mp = os.path.join(data_dir, "geometries", d, fn + ".mesh")
    os.makedirs(os.path.dirname(mp), exist_ok=True)
    with open(mp, "wb") as fh:
        fh.write(data)
    pts = [sfmesh.decode_position(q, scale) for q in raw]
    sphere, box = sfnif.bounds_from_points(pts)
    node = f"{MODEL_DIR}\\{name}".encode()
    n_idx = len(tris) * (2 if double_sided else 1) * 3
    f = sfnif.build_static_nif(node, [sfnif.StaticShape(node + b":0", f"{d}\\{fn}".encode(), n_idx, len(pos),
                                                        material, sphere, box)], bsx=1)
    model = f"{MODEL_DIR}\\{name}.nif"
    np_ = os.path.join(data_dir, "meshes", *model.split("\\"))
    os.makedirs(os.path.dirname(np_), exist_ok=True)
    with open(np_, "wb") as fh:
        fh.write(nifmod.serialize(f))
    a = np.asarray(pts, np.float64)
    return model, [[round(float(v), 3) for v in a.min(0)], [round(float(v), 3) for v in a.max(0)]]


def wave_normals(size: int = 256, seed: int = 7):
    """Tiling wave normal map (R, G as unsigned 0..255) from a few integer-frequency swells plus band-limited noise."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size] / size * 2.0 * np.pi
    h = np.zeros((size, size))
    for fx, fy, amp in ((1, 2, 1.0), (2, -1, 0.9), (3, 1, 0.7), (1, 4, 0.6), (5, -2, 0.45), (-2, 7, 0.35),
                        (9, 4, 0.25), (-7, 11, 0.18), (13, -6, 0.12)):
        h += amp * np.sin(fx * x + fy * y + rng.uniform(0, 2 * np.pi))
    spec = np.fft.fft2(rng.normal(size=(size, size)))
    fy_, fx_ = np.meshgrid(np.fft.fftfreq(size) * size, np.fft.fftfreq(size) * size, indexing="ij")
    r = np.hypot(fx_, fy_)
    spec *= np.where((r > 4) & (r < 60), 1.0 / np.maximum(r, 1.0), 0.0)
    noise = np.real(np.fft.ifft2(spec))
    h += noise / (np.abs(noise).max() or 1.0) * 0.8
    gx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 0.5
    gy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * 0.5
    k = 0.6 / (max(np.abs(gx).max(), np.abs(gy).max()) or 1.0)     # gentle slopes: |n.xy| <= ~0.5
    nx, ny = -gx * k, -gy * k
    nz = np.sqrt(np.clip(1.0 - nx ** 2 - ny ** 2, 0.0, 1.0))
    norm = np.sqrt(nx ** 2 + ny ** 2 + nz ** 2)
    to_u8 = lambda v: np.clip(np.rint((v / norm + 1.0) * 127.5), 0, 255).astype(np.uint8)   # noqa: E731
    return to_u8(nx), to_u8(ny)


def write_material(data_dir: str, content_resources: str, texconv: str, colour=COLOUR, roughness: int = ROUGHNESS) -> str:
    """Sea colour / wave normal / roughness textures and a .mat cloned from the converter's template; returns the
    material path as NIFs store it ("materials\\...")."""
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        c = np.zeros((64, 64, 4), np.uint8)
        c[..., :3] = colour
        c[..., 3] = 255
        textures.write_dds_dx10(os.path.join(tmp, "c_in.dds"), 64, 64, textures.DXGI_R8G8B8A8_UNORM, c.tobytes(), 4)
        textures.texconv(texconv, os.path.join(tmp, "c_in.dds"), tmp, "BC1_UNORM_SRGB")
        r, g = wave_normals(512)
        textures.write_rg8_snorm(os.path.join(tmp, "n_in.dds"), r, g)
        textures.texconv(texconv, os.path.join(tmp, "n_in.dds"), tmp, "BC5_SNORM")
        textures.write_r8(os.path.join(tmp, "r_in.dds"), np.full((64, 64), int(roughness), np.uint8))
        textures.texconv(texconv, os.path.join(tmp, "r_in.dds"), tmp, "BC4_UNORM")
        for kind, fn in (("color", "c_in.dds"), ("normal", "n_in.dds"), ("rough", "r_in.dds")):
            dst = os.path.join(data_dir, *f"{TEX_REL}_{kind}.dds".split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(tmp, fn), dst)
            out[kind] = cm.game_path(f"{TEX_REL}_{kind}.dds")
    mat = cm.build_mat(cm.read_template(content_resources), "SKY_DistantSea", out["color"], out["normal"], out["rough"])
    p = os.path.join(data_dir, *MAT_REL.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(cm.dump_mat(mat))
    return MAT_REL.replace("/", "\\")


def remove(objects: dict) -> int:
    """Drop an earlier run's sea bases and references from objects.json (reindexing the other references)."""
    keep = [i for i, b in enumerate(objects["bases"]) if not b["edid"].startswith(EDID_PREFIX)]
    if len(keep) == len(objects["bases"]):
        return 0
    new = {old: new for new, old in enumerate(keep)}
    n = len(objects["bases"]) - len(keep)
    objects["bases"] = [objects["bases"][i] for i in keep]
    objects["refs"] = [dict(r, base=new[r["base"]]) for r in objects["refs"]
                       if not str(r.get("src", "")).startswith(SRC_PREFIX) and r["base"] in new]
    return n


def pieces(cell_min: int, cell_max: int, reach_m: float):
    """[(kind, (x, y) ref position, rotation z)]: tiles over the overlay, a strip off every edge tile, a corner piece
    off every corner tile. Strip / corner meshes reach +y / +x+y; the rotation turns them to their side."""
    t, k, x0 = tile_layout(cell_min, cell_max)
    centre = lambda i: x0 + t / 2 + i * t                                 # noqa: E731
    out = [("tile", (centre(i), centre(j)), 0.0) for j in range(k) for i in range(k)]
    # Bethesda z rotation turns clockwise seen from above: heading 0 = +y (north), pi/2 = +x, pi = -y, 3pi/2 = -x
    for i in range(k):
        out += [("strip", (centre(i), centre(k - 1)), 0.0), ("strip", (centre(k - 1), centre(i)), math.pi / 2),
                ("strip", (centre(i), centre(0)), math.pi), ("strip", (centre(0), centre(i)), 3 * math.pi / 2)]
    out += [("corner", (centre(k - 1), centre(k - 1)), 0.0), ("corner", (centre(k - 1), centre(0)), math.pi / 2),
            ("corner", (centre(0), centre(0)), math.pi), ("corner", (centre(0), centre(k - 1)), 3 * math.pi / 2)]
    return out


def add(objects: dict, data_dir: str, cell_min: int, cell_max: int, sea_level_m: float, content_resources: str,
        texconv: str, reach_m: float = 60000.0, below_m: float = 0.3, double_sided: bool = False,
        colour=COLOUR, roughness: int = ROUGHNESS) -> Dict[str, int]:
    """Write the sea models and material under data_dir and append their bases / references to objects.json's dict."""
    remove(objects)
    material = write_material(data_dir, content_resources, texconv, colour, roughness)
    t, _k, _x0 = tile_layout(cell_min, cell_max)
    h, o = t / 2, OVERLAP_M
    reach = max(t, round(reach_m / t) * t)
    far = max(t / 2, reach / 100.0)               # <= 100 x 100 quads (40,000 vertices; one mesh holds 65,535)
    shapes = {"tile": quads(-h - o, h + o, -h - o, h + o, 0.0, t),
              "strip": quads(-h - o, h + o, h - o, h + reach, 0.0, far),
              "corner": quads(h - o, h + reach, h - o, h + reach, 0.0, far)}
    base_of = {}
    for kind, (pos, uv, tris) in shapes.items():
        model, bounds = write_model(data_dir, kind, pos, uv, tris, material, double_sided)
        base_of[kind] = len(objects["bases"])
        objects["bases"].append({"edid": f"{EDID_PREFIX}_{kind.capitalize()}", "model": model,
                                 "source": "generated: distant sea", "collision": "none", "bounds": bounds})
    z = round(sea_level_m - below_m, 4)
    n = 0
    for kind, (x, y), rz in pieces(cell_min, cell_max, reach_m):
        cell = [int(math.floor(x / 100.0)), int(math.floor(y / 100.0))]
        objects["refs"].append({"src": f"{SRC_PREFIX}{kind}:{n}", "base": base_of[kind], "cell": cell,
                                "pos": [round(x, 4), round(y, 4), z], "rot": [0.0, 0.0, round(rz, 6)], "scale": 1.0,
                                "disabled": False})
        n += 1
    return {"pieces": n, "tile_m": round(t, 3), "reach_m": reach, "z": z}
