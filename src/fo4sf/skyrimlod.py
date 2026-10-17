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


def manifest_path(data_dir: str, world: str) -> str:
    """The list of files a lod run wrote (so the next run removes them). It sits in Data's root, outside the folders
    the installer packs (it used to sit in lodsettings\\, which is now packed too)."""
    return os.path.join(data_dir, f"{world.lower()}.lodfiles.json")


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


def model_bounds(data_dir: str, model: str):
    """[[min x, y, z], [max x, y, z]] in metres of a converted static's geometry (load_model), or None."""
    shapes, _r = load_model(data_dir, model)
    if not shapes:
        return None
    pts = np.concatenate([s.pos for s in shapes])
    return [[round(float(v), 4) for v in pts.min(0)], [round(float(v), 4) for v in pts.max(0)]]


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
          layer: Optional[str] = None,
          skip_paths=("\\trees\\", "/trees/"), log=print) -> dict:
    """Write the LOD files for objects.json (stage output) into data_dir; returns stats incl. the base indices with
    LOD (to flag distant_lod)."""
    bases = objects["bases"]
    cache: Dict[str, Optional[Tuple[List[Shape], float]]] = {}
    groups: Dict[Tuple[int, Tuple[int, int]], list] = {}          # (base, cell) -> [(pos, matrix, scale)]
    skipped_small = 0
    large: Dict[int, List[List[int]]] = {}                    # ref index -> cells its bounding circle covers
    for ri, r in enumerate(objects["refs"]):
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
        rad = mdl[1] * sc
        large[ri] = [[x, y] for x in range(int(math.floor((r["pos"][0] - rad) / CELL_M)),
                                           int(math.floor((r["pos"][0] + rad) / CELL_M)) + 1)
                     for y in range(int(math.floor((r["pos"][1] - rad) / CELL_M)),
                                    int(math.floor((r["pos"][1] + rad) / CELL_M)) + 1)]
        groups.setdefault((r["base"], cell), []).append((np.asarray(r["pos"], np.float64),
                                                         np.asarray(exterior.ref_matrix(r["rot"])).reshape(3, 3), sc))
    manifest = manifest_path(data_dir, world)
    old_manifest = os.path.join(data_dir, "lodsettings", f"{world.lower()}.files.json")
    for mf in (manifest, old_manifest):              # a rerun: remove what the previous run wrote
        if os.path.isfile(mf):
            import json
            for rel in json.load(open(mf, encoding="utf-8")):
                p = os.path.join(data_dir, *rel.split("/"))
                if os.path.isfile(p):
                    os.remove(p)
            os.remove(mf)
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
        # one file per layer and block (vanilla); `layer` puts every object in one layer (e.g. a vanilla one)
        blocks: Dict[Tuple[str, Tuple[int, int]], List[sfnif.StaticShape]] = {}
        for (bi, cell), shapes in level0.items():
            ln = layer or layer_name(bases[bi]["edid"])
            blocks.setdefault((ln, block_of(cell, (x0, y0), level)), []).extend(shapes)
            flagged.add(bi)
        for (ln, blk), shapes in sorted(blocks.items()):
            name = f"{ln}_{blk[0]}_{blk[1]}_lod_{level}_cell0"
            node = f"Composite\\{wl}\\{name}".encode()   # vanilla: lowercase world folder
            f = sfnif.build_static_nif(node, shapes, bsx=1)            # vanilla composites: BSXFlags 1
            with open(os.path.join(root, name.lower() + ".nif"), "wb") as fh:
                fh.write(nifmod.serialize(f))
            written.append(f"meshes/lod/generated/composite/{wl}/{name.lower()}.nif")
            nfiles += 1
    import json
    with open(manifest, "w", encoding="utf-8") as fh:
        json.dump(written, fh)
    return {"lodsettings": [x0, y0, size], "objects_with_lod": len(flagged), "instances": ninst,
            "skipped_small": skipped_small, "meshes": nmesh, "mesh_bytes": nbytes, "nif_files": nfiles,
            "flag_bases": sorted(flagged), "large_refs": large}


VANILLA_TEST = {   # a vanilla composite per LOD level (SettleGagarinWorld's crane; owner's survey), source of --vanilla-test
    0: "meshes\\lod\\generated\\composite\\settlegagarinworld\\gagarin_lod_crane01_1_1_lod_0_cell0.nif",
    1: "meshes\\lod\\generated\\composite\\settlegagarinworld\\gagarin_lod_crane01_1_0_lod_1_cell0.nif",
    2: "meshes\\lod\\generated\\composite\\settlegagarinworld\\gagarin_lod_crane01_1_-2_lod_2_cell0.nif",
    3: "meshes\\lod\\generated\\composite\\settlegagarinworld\\gagarin_lod_crane01_-3_-6_lod_3_cell0.nif",
}


def _first_sphere(n):
    for i in range(len(n.blocks)):
        if n.type_of(i) == "BSGeometry":
            return sfnif.parse_bsgeometry(n.blocks[i]).sphere
    return None


def _load_crane(read_vanilla):
    """(material path, SfMesh, vertex positions (n, 3) m, sphere centre) of the vanilla Gagarin level-3 crane."""
    v = nifmod.parse(read_vanilla(VANILLA_TEST[3]))
    gi = next(i for i in range(len(v.blocks)) if v.type_of(i) == "BSGeometry")
    g = sfnif.parse_bsgeometry(v.blocks[gi])
    ref = next(m for m in g.meshes if m)
    si, = struct.unpack_from("<i", v.blocks[g.shader], 0)
    mesh = sfmesh.parse(read_vanilla("geometries\\" + ref.path.decode("latin-1") + ".mesh"))
    pos = np.asarray(mesh.positions, np.float64) / 32767.0 * mesh.scale
    return v.strings[si].decode("latin-1"), mesh, pos, np.asarray(g.sphere[:3], np.float64)


def _write_crane(crane, data_dir: str, at, node: bytes) -> Tuple[bytes, str]:
    """(NIF bytes, mesh path under data_dir) of the crane moved (in its vertices) so its sphere centre is at `at`."""
    import dataclasses
    material, mesh, pos, centre = crane
    moved = pos + (np.asarray(at, np.float64) - centre)
    scale, raw = sfmesh.encode_positions([tuple(q) for q in moved])
    m = sfmesh.build_meshlets(dataclasses.replace(mesh, scale=scale, positions=raw))
    data = sfmesh.serialize(m)
    d, fn = convert_static.mesh_file_path(data)
    mp = os.path.join(data_dir, "geometries", d, fn + ".mesh")
    os.makedirs(os.path.dirname(mp), exist_ok=True)
    with open(mp, "wb") as fh:
        fh.write(data)
    sphere, box = sfnif.bounds_from_points([sfmesh.decode_position(q, scale) for q in raw])
    f = sfnif.build_static_nif(node, [sfnif.StaticShape(node + b":0", f"{d}\\{fn}".encode(), len(m.triangles) * 3,
                                                        len(m.positions), material, sphere, box)], bsx=1)
    return nifmod.serialize(f), f"geometries/{d}/{fn}.mesh"


def vanilla_test(data_dir: str, world: str, read_vanilla) -> int:
    """Diagnostic: replace every composite LOD NIF this build wrote with a vanilla Gagarin crane composite
    (vanilla material; the vanilla level-3 mesh with its vertices moved so the crane stands 60 m above our first
    shape). The offset is baked into the vertices, as vanilla composites keep world coordinates with identity
    transforms (the first version moved the root node instead, which the engine may ignore). If cranes then show far
    away, the engine loads our files and our NIF / material contents are the problem; if not, it does not look at them
    at all. One small crane for every level: a moved copy per file of each level's own crane pushed the owner's
    whole-map build past one archive's 4 GiB. read_vanilla(archive path) -> bytes. Returns files replaced."""
    import json
    crane = _load_crane(read_vanilla)
    manifest = manifest_path(data_dir, world)
    written = json.load(open(manifest, encoding="utf-8"))
    for rel in [r for r in written if r.endswith(".mesh")]:   # our own LOD meshes: no longer referenced
        pth = os.path.join(data_dir, *rel.split("/"))
        if os.path.isfile(pth):
            os.remove(pth)
        written.remove(rel)
    n, extra = 0, []
    for rel in list(written):
        if not rel.endswith(".nif"):
            continue
        p = os.path.join(data_dir, *rel.split("/"))
        ours = _first_sphere(nifmod.parse(open(p, "rb").read()))
        if ours is None:
            continue
        node = f"Composite\\{world.lower()}\\{os.path.splitext(os.path.basename(p))[0]}".encode()
        data, mrel = _write_crane(crane, data_dir, (ours[0], ours[1], ours[2] + 60.0), node)
        with open(p, "wb") as fh:
            fh.write(data)
        extra.append(mrel)
        n += 1
    with open(manifest, "w", encoding="utf-8") as fh:      # so the next lod run removes the moved meshes too
        json.dump(written + extra, fh)
    return n


def override_test(data_dir: str, targets, read_vanilla) -> List[str]:
    """Diagnostic in a vanilla world whose composite LOD draws: for each vanilla composite (archive path, NIF bytes) in
    `targets`, write a file at the SAME path under data_dir holding the crane, standing 20 m above the top of the
    vanilla object's bounding sphere. Packed into our archive, it overrides the vanilla file: if cranes then show
    there from afar, the engine reads composite LOD from a plugin's archive (and our NIF / mesh layout draws). Returns
    the files written (relative, '/')."""
    crane = _load_crane(read_vanilla)
    out = []
    for path, raw in targets:
        sph = _first_sphere(nifmod.parse(raw))
        if sph is None:
            continue
        rel = path.replace("\\", "/").lower()
        node = ("Composite\\" + "\\".join(rel.split("/")[-2:])[:-4]).encode()
        data, mrel = _write_crane(crane, data_dir, (sph[0], sph[1], sph[2] + sph[3] + 20.0), node)
        p = os.path.join(data_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)
        out += [rel, mrel]
    return out
