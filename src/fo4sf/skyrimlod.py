"""Distant-object LOD for the Skyrim overlay, in vanilla Starfield's layout (make_skyrim_objects.py lod;
docs/terrain/skyrim-objects.md "Distant-object LOD").

Vanilla layout (verified from the owner's archives):
  lodsettings\\<world>.lod                 5 x int32: south-west cell x, y, cells per side, 0, 0
  meshes\\lod\\generated\\composite\\<world>\\<object>_<x>_<y>_lod_<L>_cell0.nif
      L = 0..3, one file per source object per block of 2^L x 2^L cells (aligned to the lodsettings origin, named by
      the block's south-west cell), geometry already in world coordinates (identity transforms).
Here every reference of a large static (radius x scale >= min_radius) is merged per object and cell into level-0
meshes in world coordinates (the converted full model; no simplification, no texture baking: the model's own
materials). A level-L file lists the level-0 meshes of its block, so no geometry is stored twice. Supported
hypothesis, not yet seen in game: that the engine finds these files by name for a modded worldspace.
"""
import math
import os
import struct
from typing import Dict, List, Optional, Tuple

import numpy as np

from fo4sf import convert_static, exterior, nif as nifmod, sfmesh, sfnif

CELL_M = 100.0
LEVELS = 4
MAX_VERTS = 0xFFFF


def layer_name(base_edid: str) -> str:
    """The LAYR EditorID (= composite file name prefix) for a base's LOD."""
    return f"{base_edid}_LOD"


def lodsettings(cell_min: int, cell_max: int) -> Tuple[bytes, Tuple[int, int, int]]:
    """(file bytes, (x0, y0, size)): a square from cell_min, size rounded up to a multiple of 2^(LEVELS-1)."""
    step = 2 ** (LEVELS - 1)
    size = -(-(cell_max - cell_min + 1) // step) * step
    return struct.pack("<5i", cell_min, cell_min, size, 0, 0), (cell_min, cell_min, size)


def block_of(cell: Tuple[int, int], origin: Tuple[int, int], level: int) -> Tuple[int, int]:
    s = 2 ** level
    return tuple(origin[a] + ((cell[a] - origin[a]) // s) * s for a in range(2))


def _unpack(arr):
    a = np.asarray(arr, np.uint32)
    x = (a & 0x3FF) / 1023.0 * 2.0 - 1.0
    y = ((a >> 10) & 0x3FF) / 1023.0 * 2.0 - 1.0
    z = ((a >> 20) & 0x3FF) / 1023.0 * 2.0 - 1.0
    return np.stack([x, y, z], 1), (a >> 30)


def _pack(v, w):
    q = np.clip(np.rint((v + 1.0) * 0.5 * 1023.0), 0, 1023).astype(np.uint32)
    return (q[:, 0] | (q[:, 1] << 10) | (q[:, 2] << 20) | (np.asarray(w, np.uint32) << 30)).tolist()


class Shape:
    """One shape of a converted Starfield static: model-space geometry (metres) and its material."""
    def __init__(self, material, pos, tris, uv, col, nrm, nw, tan, tw):
        self.material, self.pos, self.tris, self.uv, self.col = material, pos, tris, uv, col
        self.nrm, self.nw, self.tan, self.tw = nrm, nw, tan, tw


def load_model(data_dir: str, model: str) -> Tuple[List[Shape], float]:
    """(shapes, bounding radius in metres) of a converted static NIF (identity-transform shapes, as
    skyrimconvert.convert_static_sse writes them) under data_dir ("meshes\\<model>")."""
    p = os.path.join(data_dir, "meshes", *model.replace("\\", "/").split("/"))
    n = nifmod.parse(open(p, "rb").read())
    shapes, radius = [], 0.0
    for i in range(len(n.blocks)):
        if n.type_of(i) != "BSGeometry":
            continue
        g = sfnif.parse_bsgeometry(n.blocks[i])
        ref = next((m for m in g.meshes if m), None)
        if ref is None or g.shader < 0:
            continue
        si, = struct.unpack_from("<i", n.blocks[g.shader], 0)
        material = n.strings[si].decode("latin-1") if 0 <= si < len(n.strings) else ""
        mp = os.path.join(data_dir, "geometries", *ref.path.decode("latin-1").replace("\\", "/").split("/")) + ".mesh"
        m = sfmesh.parse(open(mp, "rb").read())
        if not m.positions or not m.triangles:
            continue
        pos = np.asarray(m.positions, np.float64) / 32767.0 * m.scale
        nv = len(pos)
        nrm, nw = _unpack(m.normals) if m.normals else (np.tile([0.0, 0.0, 1.0], (nv, 1)), np.zeros(nv, np.uint32))
        tan, tw = _unpack(m.tangents) if m.tangents else (None, None)
        shapes.append(Shape(material, pos, np.asarray(m.triangles, np.int64), list(m.uv1), list(m.colors),
                            nrm, nw, tan, tw))
        radius = max(radius, float(np.sqrt((pos ** 2).sum(1)).max()))
    return shapes, radius


def _encode(parts, material) -> sfmesh.SfMesh:
    pos = np.concatenate([p[0] for p in parts])
    m = sfmesh.SfMesh(version=2)
    m.scale, m.positions = sfmesh.encode_positions([tuple(v) for v in pos])
    off, tris = 0, []
    for p in parts:
        tris += [tuple(int(v) + off for v in t) for t in p[1]]
        off += len(p[0])
    m.triangles = tris
    if all(p[2] for p in parts):
        m.uv1 = [uv for p in parts for uv in p[2]]
    if all(p[3] for p in parts):
        m.colors = [c for p in parts for c in p[3]]
    m.normals = [v for p in parts for v in _pack(p[4], p[5])]
    if all(p[6] is not None for p in parts):
        m.tangents = [v for p in parts for v in _pack(p[6], p[7])]
    sfmesh.build_meshlets(m)
    return m


def build(objects: dict, data_dir: str, world: str, cell_min: int, cell_max: int, min_radius: float = 20.0,
          skip_paths=("\\trees\\", "/trees/"), log=print) -> dict:
    """Write the LOD files for objects.json (stage output) into data_dir; returns stats incl. the base indices with
    LOD (to flag distant_lod)."""
    bases = objects["bases"]
    cache: Dict[str, Optional[Tuple[List[Shape], float]]] = {}
    groups: Dict[Tuple[int, Tuple[int, int]], list] = {}          # (base, cell) -> [(pos, matrix, scale)]
    skipped_small = 0
    for r in objects["refs"]:
        if r.get("disabled"):
            continue
        b = bases[r["base"]]
        if b.get("door") or any(s in (b.get("source") or "").lower() for s in skip_paths):
            continue
        if b["model"] not in cache:
            try:
                cache[b["model"]] = load_model(data_dir, b["model"])
            except (OSError, ValueError, struct.error) as e:
                log(f"  lod: {b['model']}: {type(e).__name__}: {e}")
                cache[b["model"]] = None
        mdl = cache[b["model"]]
        if not mdl or not mdl[0]:
            continue
        sc = float(r.get("scale") or 1.0)
        if mdl[1] * sc < min_radius:
            skipped_small += 1
            continue
        cell = (int(math.floor(r["pos"][0] / CELL_M)), int(math.floor(r["pos"][1] / CELL_M)))
        groups.setdefault((r["base"], cell), []).append((np.asarray(r["pos"], np.float64),
                                                         np.asarray(exterior.ref_matrix(r["rot"])).reshape(3, 3), sc))
    manifest = os.path.join(data_dir, "lodsettings", f"{world.lower()}.files.json")
    if os.path.isfile(manifest):                      # a rerun: remove what the previous run wrote
        import json
        for rel in json.load(open(manifest, encoding="utf-8")):
            p = os.path.join(data_dir, *rel.split("/"))
            if os.path.isfile(p):
                os.remove(p)
    written: List[str] = []
    data, (x0, y0, size) = lodsettings(cell_min, cell_max)
    wl = world.lower()
    os.makedirs(os.path.join(data_dir, "lodsettings"), exist_ok=True)
    with open(os.path.join(data_dir, "lodsettings", f"{wl}.lod"), "wb") as f:
        f.write(data)
    level0: Dict[Tuple[int, Tuple[int, int]], List[sfnif.StaticShape]] = {}
    nmesh = nbytes = ninst = 0
    for (bi, cell), inst in sorted(groups.items()):
        shapes = cache[bases[bi]["model"]][0]
        out = []
        for s in shapes:
            per = max(1, MAX_VERTS // len(s.pos))
            for k in range(0, len(inst), per):
                parts = []
                for pos, mat, sc in inst[k:k + per]:
                    parts.append((s.pos @ mat.T * sc + pos, s.tris, s.uv, s.col, s.nrm @ mat.T, s.nw,
                                  None if s.tan is None else s.tan @ mat.T, s.tw))
                m = _encode(parts, s.material)
                raw = sfmesh.serialize(m)
                d, fn = convert_static.mesh_file_path(raw)
                mp = os.path.join(data_dir, "geometries", d, fn + ".mesh")
                os.makedirs(os.path.dirname(mp), exist_ok=True)
                with open(mp, "wb") as f:
                    f.write(raw)
                written.append(f"geometries/{d}/{fn}.mesh")
                pts = [sfmesh.decode_position(p, m.scale) for p in m.positions]
                sphere, box = sfnif.bounds_from_points(pts)
                out.append(sfnif.StaticShape(b"LOD", f"{d}\\{fn}".encode(), len(m.triangles) * 3, len(m.positions),
                                             s.material, sphere, box))
                nmesh += 1
                nbytes += len(raw)
        ninst += len(inst)
        level0[(bi, cell)] = out
    nfiles, flagged = 0, set()
    root = os.path.join(data_dir, "meshes", "lod", "generated", "composite", wl)
    os.makedirs(root, exist_ok=True)
    for level in range(LEVELS):
        blocks: Dict[Tuple[int, Tuple[int, int]], List[sfnif.StaticShape]] = {}
        for (bi, cell), shapes in level0.items():
            blocks.setdefault((bi, block_of(cell, (x0, y0), level)), []).extend(shapes)
        for (bi, blk), shapes in sorted(blocks.items()):
            name = f"{layer_name(bases[bi]['edid'])}_{blk[0]}_{blk[1]}_lod_{level}_cell0"
            node = f"Composite\\{world}\\{name}".encode()
            f = sfnif.build_static_nif(node, shapes, bsx=1)            # vanilla composites: BSXFlags 1
            with open(os.path.join(root, name.lower() + ".nif"), "wb") as fh:
                fh.write(nifmod.serialize(f))
            written.append(f"meshes/lod/generated/composite/{wl}/{name.lower()}.nif")
            nfiles += 1
            flagged.add(bi)
    import json
    with open(manifest, "w", encoding="utf-8") as fh:
        json.dump(written, fh)
    return {"lodsettings": [x0, y0, size], "objects_with_lod": len(flagged), "instances": ninst,
            "skipped_small": skipped_small, "meshes": nmesh, "mesh_bytes": nbytes, "nif_files": nfiles,
            "flag_bases": sorted(flagged)}
