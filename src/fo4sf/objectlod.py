"""Object LOD for a modded Starfield worldspace, in the layout the Creation Kit's `-MockWorldSpaceLOD` writes
(docs/terrain/skyrim-objects.md "Object LOD"). Verified from the owner's Creation Kit output for SKY_Tamriel
(3,316 files, 175,472 entries) and in game: with those files packed in our archive, Whiterun, the forests and the
cliffs showed from the Throat of the World.

    lodsettings\\<World>.lod                          5 x int32: south-west cell x, y, cells per side, 0, 0
                                                      (the cells that hold references; side = the larger extent)
    meshes\\terrain\\<World>\\objects\\<World>.<L>.<x>.<y>.nif
        L = 1, 2, 4, 8 cells per side; (x, y) = the block's south-west cell, blocks aligned to the lodsettings
        origin; every level lists every reference of the world (cell = floor(position / 100 m)).

Each NIF (bs_version 175, user_version 12) holds ONE block, BSWeakReferenceNode: a NiNode with identity transform,
flags 0x2000000E, no children, then
    u32 count; per base object, sorted by FormID:
        u32 base FormID (raw, this plugin's index), u32 crc(model file stem), 'nif\\0',
        u32 crc('meshes\\' + model folder), u32 n, n x 64 bytes:
            3 rows of (3 f32 rotation, f32 0), f32 x, y, z (metres, world), f32 scale
        u32 0
    then 10 zero bytes.
crc = Bethesda's CRC32 (sfnif.material_id) of the lowercase, backslash path. The world name the CK used is the
EditorID without underscores ("SKYTamriel"); which one the game reads is not yet known, so both can be written.
"""
import itertools
import math
import os
import struct
from typing import Dict, Iterable, List, Optional, Tuple

from fo4sf import exterior, nif as nifmod, sfnif

LEVELS = (1, 2, 4, 8)
CELL_M = 100.0
NODE_HEADER = (struct.pack("<iIiI", 0, 0, -1, 0x2000000E) + struct.pack("<3f9ff", 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 1.0)
               + struct.pack("<iI", -1, 0))


def model_hashes(model: str) -> Tuple[int, int]:
    """(crc of the file stem, crc of 'meshes\\' + folder) for a model path relative to meshes\\."""
    m = model.lower().replace("/", "\\")
    folder, _sep, name = m.rpartition("\\")
    stem = name.rsplit(".", 1)[0]
    return sfnif.material_id(stem), sfnif.material_id("meshes\\" + folder if folder else "meshes")


def _elem(axis, a):
    c, s = math.cos(a), math.sin(a)
    if axis == "x":
        return (1, 0, 0, 0, c, -s, 0, s, c)
    if axis == "y":
        return (c, 0, s, 0, 1, 0, -s, 0, c)
    return (c, -s, 0, s, c, 0, 0, 0, 1)


def _mul(a, b):
    return tuple(sum(a[3 * r + k] * b[3 * k + c] for k in range(3)) for r in range(3) for c in range(3))


# Candidate conventions for a reference's (x, y, z) angles -> the 3x3 rows the CK writes: the order the elementary
# rotations multiply in (left to right), the angle sign, and whether the result is transposed. "zyx-T" (= our
# exterior.ref_matrix transposed) matched only 3,544 of 10,220 CK instances (mostly z-only turns): the CK combines
# the angles differently; compare() tries them all. Verified: "zyx+" (= Rz(z) Ry(y) Rx(x), positive angles; the same
# matrix as "xyz--T") matched 10,140 of 10,220 CK instances (owner's run), and tilted rocks then looked right in game.
CONVENTIONS = [f"{''.join(o)}{sg}{'-T' if t else ''}" for o in itertools.permutations("xyz") for sg in ("+", "-")
               for t in (False, True)]


def rotation_rows(rot, convention="zyx+"):
    order, sign, transpose = convention[:3], convention[3], convention.endswith("-T")
    k = -1.0 if sign == "-" else 1.0
    ang = {"x": rot[0] * k, "y": rot[1] * k, "z": rot[2] * k}
    m = (1, 0, 0, 0, 1, 0, 0, 0, 1)
    for axis in order:
        m = _mul(m, _elem(axis, ang[axis]))
    if transpose:
        m = (m[0], m[3], m[6], m[1], m[4], m[7], m[2], m[5], m[8])
    return m


def instance_bytes(pos, rot, scale, convention="zyx+") -> bytes:
    m = rotation_rows(rot, convention)
    return struct.pack("<16f", m[0], m[1], m[2], 0.0, m[3], m[4], m[5], 0.0, m[6], m[7], m[8], 0.0,
                       pos[0], pos[1], pos[2], scale)


def node_bytes(entries: Dict[int, Tuple[Tuple[int, int], List[bytes]]]) -> bytes:
    """entries: {raw base FormID: ((stem crc, folder crc), [instance bytes])}, in the order to write (the CK's own
    order is neither FormID nor reference order; plan() sorts by FormID) -> the BSWeakReferenceNode block, which
    ends in 10 zero bytes (all 3,316 CK files)."""
    out = [NODE_HEADER, struct.pack("<I", len(entries))]
    for fid, ((h1, h2), inst) in entries.items():
        out.append(struct.pack("<II", fid, h1) + b"nif\0" + struct.pack("<II", h2, len(inst)))
        out.extend(inst)
        out.append(struct.pack("<I", 0))
    out.append(b"\0" * 10)
    return b"".join(out)


def nif_bytes(block: bytes) -> bytes:
    f = nifmod.NifFile(endian=1, user_version=12, bs_version=175, author=b"\x00", unknown_int=3, export_script=b"\x00",
                       sf_data=b"\x00")
    f.string_index(b"")
    f.add_block("BSWeakReferenceNode", block)
    f.footer = struct.pack("<II", 1, 0)
    return nifmod.serialize(f)


def f32(v: float) -> float:
    """The value as the plugin stores it (REFR DATA is float32): 3599.99997 in objects.json is 3600.0 there."""
    return struct.unpack("<f", struct.pack("<f", v))[0]


def cell_of(pos) -> Tuple[int, int]:
    return int(math.floor(f32(pos[0]) / CELL_M)), int(math.floor(f32(pos[1]) / CELL_M))


def settings(cells: Iterable[Tuple[int, int]]) -> Tuple[int, int, int]:
    cells = list(cells)
    x0, y0 = min(c[0] for c in cells), min(c[1] for c in cells)
    x1, y1 = max(c[0] for c in cells), max(c[1] for c in cells)
    return x0, y0, max(x1 - x0, y1 - y0) + 1


def block_of(cell, origin, level):
    return tuple(origin[a] + ((cell[a] - origin[a]) // level) * level for a in range(2))


def plan(objects: dict, base_fids: Dict[int, int], plugin_index: int = 1, convention: str = "zyx+"):
    """(lodsettings (x0, y0, side), {level: {block: {raw FormID: (hashes, [instance bytes])}}}) for objects.json
    (stage output) and base index -> FormID (low 24 bits, from formids.json)."""
    bases = objects["bases"]
    hashes = {}
    placed = []
    for r in objects["refs"]:
        bi = r["base"]
        if bi not in base_fids:
            continue
        if bi not in hashes:
            hashes[bi] = model_hashes(bases[bi]["model"])
        placed.append((cell_of(r["pos"]), (plugin_index << 24) | base_fids[bi], hashes[bi],
                       instance_bytes(r["pos"], r["rot"], float(r.get("scale") or 1.0), convention)))
    if not placed:
        return None, {}
    x0, y0, side = settings(c for c, *_ in placed)
    levels = {}
    for level in LEVELS:
        blocks: Dict[Tuple[int, int], Dict[int, Tuple[Tuple[int, int], List[bytes]]]] = {}
        for cell, fid, h, inst in placed:
            e = blocks.setdefault(block_of(cell, (x0, y0), level), {})
            e.setdefault(fid, (h, []))[1].append(inst)
        levels[level] = {b: dict(sorted(e.items())) for b, e in blocks.items()}
    return (x0, y0, side), levels


def write(data_dir: str, world_names: List[str], lodset, levels, manifest: str) -> int:
    """Write the LOD files under every name in world_names; record them in `manifest` (removed on the next run)."""
    import json
    remove(data_dir, manifest)
    written = []
    for name in world_names:
        d = os.path.join(data_dir, "lodsettings")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{name.lower()}.lod"), "wb") as fh:
            fh.write(struct.pack("<5i", lodset[0], lodset[1], lodset[2], 0, 0))
        written.append(f"lodsettings/{name.lower()}.lod")
        od = os.path.join(data_dir, "meshes", "terrain", name.lower(), "objects")
        os.makedirs(od, exist_ok=True)
        for level, blocks in levels.items():
            for (bx, by), entries in blocks.items():
                fn = f"{name}.{level}.{bx}.{by}.nif"
                with open(os.path.join(od, fn), "wb") as fh:
                    fh.write(nif_bytes(node_bytes(entries)))
                written.append(f"meshes/terrain/{name.lower()}/objects/{fn}")
    with open(manifest, "w", encoding="utf-8") as fh:
        json.dump(written, fh)
    return len(written)


def remove(data_dir: str, manifest: str) -> int:
    import json
    if not os.path.isfile(manifest):
        return 0
    n = 0
    for rel in json.load(open(manifest, encoding="utf-8")):
        p = os.path.join(data_dir, *rel.split("/"))
        if os.path.isfile(p):
            os.remove(p)
            n += 1
    os.remove(manifest)
    return n


def parse_node(block: bytes) -> Dict[int, Tuple[Tuple[int, int], List[bytes]]]:
    """Inverse of node_bytes (for comparing with Creation Kit output)."""
    p = len(NODE_HEADER)
    n, = struct.unpack_from("<I", block, p)
    p += 4
    out = {}
    for _ in range(n):
        fid, h1 = struct.unpack_from("<II", block, p)
        h2, cnt = struct.unpack_from("<II", block, p + 12)
        p += 20
        out[fid] = ((h1, h2), [bytes(block[p + 64 * i:p + 64 * i + 64]) for i in range(cnt)])
        p += 64 * cnt + 4
    return out


def compare(ck_dir: str, world_ck_name: str, objects: dict, base_fids: Dict[int, int], sample: int = 200) -> dict:
    """Match our references to the Creation Kit's level-1 instances in ck_dir by POSITION (within 1 cm; FormIDs
    differ between builds) and count, for every rotation convention in CONVENTIONS, how many rotations agree within
    1e-3. Returns {"files", "inst", "pos_ok", "hash_ok", "rot": {convention: count}}."""
    _ls, levels = plan(objects, base_fids)
    pos_index: Dict[Tuple[int, int], List[Tuple[Tuple[float, ...], tuple]]] = {}
    for r in objects["refs"]:
        if r["base"] in base_fids:
            pos_index.setdefault(cell_of(r["pos"]), []).append(
                (tuple(f32(v) for v in r["pos"]), tuple(r["rot"]), model_hashes(objects["bases"][r["base"]]["model"])))
    st = {"files": 0, "missing": 0, "inst": 0, "pos_ok": 0, "hash_ok": 0, "rot": {c: 0 for c in CONVENTIONS}}
    for (bx, by) in sorted(levels.get(1, {}))[:sample]:
        p = os.path.join(ck_dir, f"{world_ck_name}.1.{bx}.{by}.nif")
        if not os.path.isfile(p):
            st["missing"] += 1
            continue
        st["files"] += 1
        ours = pos_index.get((bx, by), [])
        for (h, inst) in parse_node(nifmod.parse(open(p, "rb").read()).blocks[0]).values():
            for b in inst:
                c = struct.unpack("<16f", b)
                st["inst"] += 1
                hit = next((o for o in ours if all(abs(o[0][k] - c[12 + k]) < 0.01 for k in range(3))), None)
                if hit is None:
                    continue
                st["pos_ok"] += 1
                st["hash_ok"] += hit[2] == h
                ck_rot = (c[0], c[1], c[2], c[4], c[5], c[6], c[8], c[9], c[10])
                for conv in CONVENTIONS:
                    if all(abs(a - b) < 1e-3 for a, b in zip(rotation_rows(hit[1], conv), ck_rot)):
                        st["rot"][conv] += 1
    return st
