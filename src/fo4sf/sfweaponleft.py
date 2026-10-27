"""Left-hand worn versions of Starfield weapon models (dual wield, S2SCombat): a weapon NIF's shapes, moved from the
weapon's frame (WEAPON / WeaponLeft bone) into the left wrist's frame at the left grip and rigidly skinned to L_Wrist
(identity bind, as skyrimconvert.convert_skinned_sse), so a worn ARMO draws the weapon in the left hand.

Each shape's LOD0 .mesh gets its vertices / normals / tangents moved (node transforms of the NIF composed as
skyrimnif / convert_static: p' = s * R * p + t, R row-major as stored) and one bone weight per vertex; triangles, UVs,
colours, LOD index lists and the meshlet split are kept, the meshlet culling data recomputed. Not carried over:
collision, lights (NiAmbientLight and the like), effects, and anything the weapon's object mods add in game.
"""
import struct
from typing import Callable, Dict, List, Optional, Tuple

from . import convert_static, nif as nifmod, sfmesh, sfnif

IDENT = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
Xf = Tuple[tuple, tuple, float]                     # (row-major rotation, translation, scale)


def _mat(a, b):
    return tuple(sum(a[3 * r + k] * b[3 * k + c] for k in range(3)) for r in range(3) for c in range(3))


def _apply(rot, v):
    return tuple(rot[3 * r] * v[0] + rot[3 * r + 1] * v[1] + rot[3 * r + 2] * v[2] for r in range(3))


def compose(a: Xf, b: Xf) -> Xf:
    """a * b (b's frame inside a's)."""
    ra, ta, sa = a
    rb, tb, sb = b
    t = _apply(ra, tb)
    return _mat(ra, rb), tuple(ta[i] + sa * t[i] for i in range(3)), sa * sb


def _node(blk: bytes):
    """(name index, local transform, children) of an NiNode block (build_static_nif / vanilla layout)."""
    name, n_extra = struct.unpack_from("<iI", blk, 0)
    p = 8 + 4 * n_extra + 8                           # extra refs, controller + flags
    f = struct.unpack_from("<13f", blk, p)
    coll, n_child = struct.unpack_from("<iI", blk, p + 52)
    children = list(struct.unpack_from(f"<{n_child}i", blk, p + 60))
    return name, (tuple(f[3:12]), tuple(f[0:3]), f[12]), children


NODE_TYPES = ("NiNode", "BSFadeNode", "BSLeafAnimNode", "BSOrderedNode", "BSMultiBoundNode")


def shapes_in_model(n: nifmod.NifFile) -> List[Tuple[int, Xf]]:
    """[(BSGeometry block, its transform in the model's root frame)] reachable from block 0 (the root's own
    transform is left out: it is where the game places the model)."""
    out = []

    def walk(i, xf, depth):
        if i < 0 or i >= len(n.blocks) or depth > 64:
            return
        t = n.type_of(i)
        if t == "BSGeometry":
            g = sfnif.parse_bsgeometry(n.blocks[i])
            out.append((i, compose(xf, (tuple(g.rotation), tuple(g.translation), g.scale))))
        elif t in NODE_TYPES:
            _name, local, children = _node(n.blocks[i])
            here = xf if depth == 0 else compose(xf, local)
            for c in children:
                walk(c, here, depth + 1)

    walk(0, (IDENT, (0.0, 0.0, 0.0), 1.0), 0)
    return out


def mesh_archive_path(p: bytes) -> str:
    """The archive path of a BSGeometry mesh reference (vanilla: '<hash>\\<hash>'; mods: a relative path, with or
    without 'geometries\\'), always ending in .mesh."""
    s = p.decode("latin-1").replace("\\", "/").lower()
    if not s.startswith("geometries/"):
        s = "geometries/" + s
    return s if s.endswith(".mesh") else s + ".mesh"


def move_mesh(m: sfmesh.SfMesh, xf: Xf, bone: int = 0) -> sfmesh.SfMesh:
    """The mesh with its vertices put through xf (positions: s * R * p + t; directions: R, renormalised; the tangents'
    bitangent sign kept), rigidly weighted to `bone`; the meshlet split kept, its culling data recomputed."""
    rot, tr, sc = xf
    pts = []
    for raw in m.positions:
        v = _apply(rot, sfmesh.decode_position(raw, m.scale))
        pts.append(tuple(sc * v[i] + tr[i] for i in range(3)))

    def turn(u32):
        x, y, z, w = sfmesh.decode_packed(u32)
        d = _apply(rot, (x, y, z))
        ln = (d[0] ** 2 + d[1] ** 2 + d[2] ** 2) ** 0.5 or 1.0
        return sfmesh.encode_packed(d[0] / ln, d[1] / ln, d[2] / ln, w)

    out = sfmesh.SfMesh(version=m.version, triangles=list(m.triangles), uv1=list(m.uv1), uv2=list(m.uv2),
                        colors=list(m.colors), lods=[list(l) for l in m.lods])
    out.scale, out.positions = sfmesh.encode_positions(pts)
    out.normals = [turn(v) for v in m.normals]
    out.tangents = [turn(v) for v in m.tangents]
    out.weights_per_vertex = 4
    out.weights = [(bone, 65535), (0, 0), (0, 0), (0, 0)] * len(out.positions)
    groups, start = [], 0
    for _vc, _vo, count, _to in m.meshlets:
        groups.append((start, count))
        start += count
    sfmesh.build_meshlets(out, groups if groups and start == len(out.triangles) else None)
    return out


def left_hand_model(nif_bytes: bytes, read: Callable[[str], Optional[bytes]], out_name: str, grip: Tuple[tuple, tuple],
                    bone: bytes = b"L_Wrist") -> Tuple[Dict[str, bytes], dict]:
    """(files {relative path: bytes}, report): meshes/<out_name>.nif (skinned to `bone`) and its new .mesh files.
    read(archive path) gives a file of the weapon's mod (None when missing). grip: (rotation, translation) from the
    weapon frame into the bone's frame (skyrimweapon.left_grip_metres)."""
    n = nifmod.parse(nif_bytes)
    to_wrist = (grip[0], grip[1], 1.0)
    files, skinned, report = {}, [], {"shapes": [], "skipped": []}
    for i, xf in shapes_in_model(n):
        g = sfnif.parse_bsgeometry(n.blocks[i])
        name = n.strings[g.name_idx] if 0 <= g.name_idx < len(n.strings) else b"Shape%d" % i
        if g.skin >= 0 or not g.meshes or g.meshes[0] is None:
            report["skipped"].append(f"{name.decode('latin-1')}: skinned or no mesh")
            continue
        src = mesh_archive_path(g.meshes[0].path)
        raw = read(src)
        if raw is None:
            report["skipped"].append(f"{name.decode('latin-1')}: {src} not found")
            continue
        mat = ""
        if 0 <= g.shader < len(n.blocks) and n.type_of(g.shader) == "BSLightingShaderProperty":
            si, = struct.unpack_from("<i", n.blocks[g.shader], 0)
            mat = n.strings[si].decode("latin-1") if 0 <= si < len(n.strings) else ""
        m = move_mesh(sfmesh.parse(raw), compose(to_wrist, xf))
        data = sfmesh.serialize(m)
        d, f = convert_static.mesh_file_path(data)
        files[f"geometries/{d}/{f}.mesh"] = data
        pts = [sfmesh.decode_position(p, m.scale) for p in m.positions]
        (cx, cy, cz, r), _box = sfnif.bounds_from_points(pts)
        skinned.append(sfnif.SkinnedShape(name, f"{d}\\{f}".encode(), len(m.triangles) * 3, len(m.positions), mat,
                                          [bone], [((cx, cy, cz, r), IDENT, (0.0, 0.0, 0.0), 1.0)]))
        report["shapes"].append({"name": name.decode("latin-1"), "mesh": src, "material": mat})
    if not skinned:
        raise nifmod.NifError("no shape with a mesh")
    lights = [n.type_of(i) for i in range(len(n.blocks)) if n.type_of(i).endswith("Light")]
    if lights:
        report["left_out"] = sorted(set(lights))
    out = sfnif.build_skinned_nif(out_name.rsplit("/", 1)[-1].encode(), skinned)
    files[f"meshes/{out_name}.nif"] = nifmod.serialize(out)
    return files, report
