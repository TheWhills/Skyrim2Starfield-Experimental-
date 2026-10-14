"""Fallout 4 static NIF -> Starfield NIF + .mesh files (spike S1, fidelity tier T1: geometry + placeholder material).

    files = convert_static(open("chair.nif", "rb").read(), "fo4port/setdressing/chair")
    # {"meshes/fo4port/setdressing/chair.nif": b"...", "geometries/<20hex>/<20hex>.mesh": b"...", ...}

Unverified assumptions (see docs/RISKS.md S4): 1 Fallout 4 unit = 1/70 m, same handedness / winding / UV
convention, Z-up in both. Collision, materials and skinning are not converted yet.
"""
import hashlib
import struct
from dataclasses import replace
from typing import Dict, Tuple

from . import nif as nifmod
from . import sfcollision, sfmesh, sfnif

UNIT_SCALE = 1.0 / 70.0           # Fallout 4 units -> metres (Starfield .mesh coordinates are metres)
PLACEHOLDER_MATERIAL = "Materials\\Common\\Metal\\MetalIronCast01.mat"   # vanilla material, T0 look


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def tangent_signs(positions, uvs, normals, tangents, triangles):
    """Per-vertex handedness bit (1 = positive) derived from the UV gradient; the Starfield tangent's top two
    bits are 3 for positive and 0 for negative (verified against 99% of 22k vanilla vertices)."""
    sign = [None] * len(positions)
    for a, b, c in triangles:
        if all(s is not None for s in (sign[a], sign[b], sign[c])):
            continue
        e1, e2 = _sub(positions[b], positions[a]), _sub(positions[c], positions[a])
        du1, dv1 = uvs[b][0] - uvs[a][0], uvs[b][1] - uvs[a][1]
        du2, dv2 = uvs[c][0] - uvs[a][0], uvs[c][1] - uvs[a][1]
        det = du1 * dv2 - du2 * dv1
        if abs(det) < 1e-12:
            continue
        bit = tuple((e2[k] * du1 - e1[k] * du2) / det for k in range(3))
        for v in (a, b, c):
            if sign[v] is None:
                h = _dot(_cross(normals[v], tangents[v]), bit)
                if abs(h) > 1e-12:
                    sign[v] = 1 if h > 0 else 0
    return [1 if s is None else s for s in sign]


def shape_to_mesh(shape: nifmod.Fo4Shape, unit_scale: float = UNIT_SCALE) -> sfmesh.SfMesh:
    pts = []
    r = shape.rotation
    for x, y, z in shape.positions:
        # NIF rotation is row-major; apply scale, rotation and translation of the shape node
        px = shape.scale * (r[0] * x + r[1] * y + r[2] * z) + shape.translation[0]
        py = shape.scale * (r[3] * x + r[4] * y + r[5] * z) + shape.translation[1]
        pz = shape.scale * (r[6] * x + r[7] * y + r[8] * z) + shape.translation[2]
        pts.append((px * unit_scale, py * unit_scale, pz * unit_scale))
    m = sfmesh.SfMesh(version=2)
    m.scale, m.positions = sfmesh.encode_positions(pts)
    m.triangles = [tuple(t) for t in shape.triangles]
    if shape.uvs:
        m.uv1 = [(sfmesh.float_to_half(u), sfmesh.float_to_half(v)) for u, v in shape.uvs]
    def rot_dir(v):                                   # directions take the rotation only (uniform scale), renormalised
        d = (r[0] * v[0] + r[1] * v[1] + r[2] * v[2], r[3] * v[0] + r[4] * v[1] + r[5] * v[2],
             r[6] * v[0] + r[7] * v[1] + r[8] * v[2])
        ln = (d[0] ** 2 + d[1] ** 2 + d[2] ** 2) ** 0.5 or 1.0
        return (d[0] / ln, d[1] / ln, d[2] / ln)
    normals = [rot_dir(v) for v in shape.normals]
    tangents = [rot_dir(v) for v in shape.tangents]
    if normals:
        m.normals = [sfmesh.encode_packed(*n, w=1.0 / 3.0) for n in normals]
    if normals and tangents and shape.uvs:
        # handedness is rotation-invariant: compute it in the shape's local space
        signs = tangent_signs(shape.positions, shape.uvs, shape.normals, shape.tangents, shape.triangles)
        m.tangents = [sfmesh.encode_packed(*t, w=float(s)) for t, s in zip(tangents, signs)]
    if shape.colors:
        m.colors = [(c[2]) | (c[1] << 8) | (c[0] << 16) | (c[3] << 24) for c in shape.colors]   # RGBA -> BGRA u32
    sfmesh.build_meshlets(m)
    return m


def mesh_file_path(mesh_bytes: bytes):
    h = hashlib.sha1(mesh_bytes).hexdigest()
    return h[:20], h[20:40]


def collision_template_from_nif(sf_nif: bytes) -> bytes:
    """Pull the Havok blob out of a vanilla Starfield NIF that has plain box collision (run-time input, not committed)."""
    n = nifmod.parse(sf_nif)
    for i, b in enumerate(n.blocks):
        if n.type_of(i) == "bhkPhysicsSystem":
            size, = struct.unpack_from("<I", b, 0)
            blob = b[4:4 + size]
            sfcollision.check_template(blob)
            return blob
    raise nifmod.NifError("template NIF has no bhkPhysicsSystem")


def fo4_native_collision(src, universal_template: bytes, report: dict = None):
    """[Starfield single-body physics blobs], one per FO4 collision body (meshcollision.convert_bodies), or None to fall
    back. Unsupported shape classes and malformed data return None and record why. One exception, reported as
    report["skipped_parts"]: precombine debris parts in the undecoded primitive encoding (see convert_bodies) are left
    out and the rest of the model keeps its native bodies."""
    from . import meshcollision
    objs = [i for i in range(len(src.blocks)) if src.type_of(i) == "bhkNPCollisionObject"]
    if not objs:
        return None
    blobs, skipped = [], []
    world = nifmod.world_transforms(src)
    for i in objs:
        target, _, data = struct.unpack_from("<iHi", src.blocks[i], 0)
        if not (0 <= target < len(src.blocks)):
            if report is not None:
                report["fo4_collision_error"] = "collision object has no target node"
            return None
        # FO4 bhkNPCollisionObject: target, flags, data, body index. Several objects can share one system and each
        # owns one body. Shapes are in the target node's space: the body goes on a child node with that transform.
        body, = struct.unpack_from("<I", src.blocks[i], 10) if len(src.blocks[i]) >= 14 else (0,)
        tr, rot, scale = world(target)
        if abs(scale - 1.0) > 1e-3:
            if report is not None:
                report["fo4_collision_error"] = f"collision node scaled {scale:.3f} (not supported yet)"
            return None
        place = None if target == 0 else (tuple(x * UNIT_SCALE for x in tr), tuple(rot))
        shared = sum(1 for j in objs if struct.unpack_from("<iHi", src.blocks[j], 0)[2] == data)
        if not (0 <= data < len(src.blocks)) or src.type_of(data) != "bhkPhysicsSystem":
            if report is not None:
                report["fo4_collision_error"] = f"collision data is {src.type_of(data) if 0 <= data < len(src.blocks) else 'missing'}"
            return None
        n, = struct.unpack_from("<I", src.blocks[data], 0)
        try:
            new = meshcollision.convert_bodies(src.blocks[data][4:4 + n], universal_template,
                                               select=[body] if shared > 1 else None, node_rot=tuple(rot),
                                               skipped=skipped)
            node = place or ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0))
            for b in new:
                if isinstance(b, tuple):                 # rotated compound instance: node transform * instance
                    blob, ti, Ri = b
                    Rn, tn = node[1], node[0]
                    R2 = tuple(sum(Rn[3 * r + k] * Ri[3 * k + c] for k in range(3)) for r in range(3) for c in range(3))
                    t2 = tuple(tn[r] + sum(Rn[3 * r + k] * ti[k] for k in range(3)) for r in range(3))
                    blobs.append((blob, t2, R2))
                else:
                    blobs.append(b if place is None else (b, place[0], place[1]))
        except Exception as e:                           # noqa: BLE001  (fallback by design, reason recorded)
            if report is not None:
                report["fo4_collision_error"] = f"{type(e).__name__}: {e}"
            return None
    if report is not None and skipped:
        report["skipped_parts"] = skipped
    if report is not None and blobs:
        report["source"] = "fo4-native"
        report["bodies"] = len(blobs)
    return blobs or None


def fo4_mesh_collision(src, sf_mesh_template: bytes, report: dict = None):
    """Starfield collision blob made from the FO4 NIF's own mesh collision (on the root node), or None.
    FO4 bhkNPCollisionObject: target node i32, flags u16, data (bhkPhysicsSystem) i32."""
    from . import meshcollision
    for i in range(len(src.blocks)):
        if src.type_of(i) != "bhkNPCollisionObject":
            continue
        target, _, data = struct.unpack_from("<iHi", src.blocks[i], 0)
        if target != 0 or not (0 <= data < len(src.blocks)) or src.type_of(data) != "bhkPhysicsSystem":
            continue
        n, = struct.unpack_from("<I", src.blocks[data], 0)
        try:
            out = meshcollision.transplant(src.blocks[data][4:4 + n], sf_mesh_template)
        except Exception as e:                       # noqa: BLE001  (fallback by design, reason recorded)
            if report is not None:
                report["fo4_collision_error"] = f"{type(e).__name__}: {e}"
            return None
        if out is not None and report is not None:
            report["source"] = "fo4-mesh"
        return out
    return None


def convert_static(fo4_nif: bytes, out_name: str, material_path: str = PLACEHOLDER_MATERIAL,
                   unit_scale: float = UNIT_SCALE, collision_template: bytes = None,
                   material_paths: list = None, collision_mode: str = "box",
                   include_skinned: bool = False, report: dict = None, sf_mesh_template: bytes = None,
                   allow_guess: bool = True) -> Dict[str, bytes]:
    """collision_mode: "box" = one AABB on the root; "surfaces" = thin boxes behind flat surfaces, one body each.
    sf_mesh_template: a vanilla Starfield mesh-collision blob; when given, FO4's own collision mesh is transplanted
    (meshcollision.transplant) and the box methods are only the fallback.
    allow_guess=False: FO4's own collision or nothing, never a guessed box (vegetation, mounds, door frames: a box
    around them would be an invisible wall). A failed native conversion is reported as "fo4-native-failed"."""
    src = nifmod.parse(fo4_nif)
    shapes = [s for s in nifmod.fo4_trishapes(src) if (include_skinned or not s.skinned) and s.positions and s.triangles]
    if not shapes:
        raise nifmod.NifError("no static BSTriShape geometry found")
    files, static_shapes, all_pts, all_tris = {}, [], [], []
    for i, s in enumerate(shapes):
        if material_paths and material_paths[i] is None:      # caller asked to drop this shape (e.g. effect shader)
            continue
        m = shape_to_mesh(s, unit_scale)
        data = sfmesh.serialize(m)
        d, f = mesh_file_path(data)
        files[f"geometries/{d}/{f}.mesh"] = data
        pts = [sfmesh.decode_position(p, m.scale) for p in m.positions]
        all_tris += [(a + len(all_pts), b + len(all_pts), c + len(all_pts)) for a, b, c in m.triangles]
        all_pts += pts
        sphere, box = sfnif.bounds_from_points(pts)
        name = s.name or f"Shape{i}".encode()
        static_shapes.append(sfnif.StaticShape(name, f"{d}\\{f}".encode(), len(m.triangles) * 3, len(m.positions),
                                               material_paths[i] if material_paths else material_path, sphere, box))
    node_name = out_name.rsplit("/", 1)[-1].encode()
    blob, child_blobs = None, []
    native = None
    fo4_has_collision = any(src.type_of(i) == "bhkNPCollisionObject" for i in range(len(src.blocks)))
    if sf_mesh_template is not None and collision_template is not None:
        native = fo4_native_collision(src, sf_mesh_template, report)   # FO4's own bodies as native Starfield bodies
    if sf_mesh_template is not None and collision_template is not None and not fo4_has_collision:
        # FO4 gives this model no collision (rubble, debris, paper, signs, posters, plants): the player walks through
        # it there, so it gets none here either. A guessed box would be an invisible wall.
        if report is not None:
            report["source"] = "fo4-none"
    elif native:
        child_blobs = native                         # one body per child node, as vanilla multi-body files do
    elif not allow_guess:
        if report is not None and fo4_has_collision:
            report["source"] = "fo4-native-failed"
    elif collision_template is not None and collision_mode == "surfaces":
        for c, h in sfcollision.mesh_boxes(all_pts, all_tris, report=report):
            child_blobs.append(sfcollision.box_blob(collision_template, c, h))
    elif collision_template is not None:     # T3: one axis-aligned box around all geometry
        lo = [min(p[a] for p in all_pts) for a in range(3)]
        hi = [max(p[a] for p in all_pts) for a in range(3)]
        blob = sfcollision.box_blob(collision_template, tuple((lo[a] + hi[a]) / 2 for a in range(3)),
                                    tuple((hi[a] - lo[a]) / 2 for a in range(3)))
    out = sfnif.build_static_nif(node_name, static_shapes, collision_blob=blob, child_collision_blobs=child_blobs)
    files[f"meshes/{out_name}.nif"] = nifmod.serialize(out)
    return files


def convert_door(fo4_nif: bytes, out_name: str, material_paths: list, unit_scale: float = UNIT_SCALE,
                 template: dict = None, collision_template: bytes = None,
                 leaf_physics_donor: bytes = None) -> Tuple[Dict[str, bytes], tuple, tuple]:
    """FO4 hinged door -> Starfield door NIF rigged like the vanilla template door (see sfnif.DOOR_TEMPLATE).
    Shapes under the node the FO4 "Open" sequence animates become the moving leaf; everything else is the static frame.
    Geometry is re-centred on the FO4 pivot and hung under the template's hinge position, so the NIF origin moves:
    returns (files, origin_offset, bounds) where origin_offset (metres, door-local) must be added (rotated and scaled) to the
    reference position to keep the door where FO4 drew it. bounds = (min xyz, max xyz) in NIF space (for the record's OBND)."""
    template = template or sfnif.DOOR_TEMPLATE
    src = nifmod.parse(fo4_nif)
    hinge = nifmod.door_hinge(src)
    if hinge is None:
        raise nifmod.NifError("no Open sequence / hinge node")
    moving_blocks = nifmod.descendants(src, hinge[0])
    pivot = hinge[1]
    shapes = [s for s in nifmod.fo4_trishapes(src) if s.positions and s.triangles]
    files, static_shapes, moving_shapes, moving_pts, all_pts = {}, [], [], [], []
    for i, s in enumerate(shapes):
        if material_paths[i] is None:
            continue
        s = replace(s, translation=tuple(s.translation[a] - pivot[a] for a in range(3)))
        m = shape_to_mesh(s, unit_scale)
        data = sfmesh.serialize(m)
        d, f = mesh_file_path(data)
        files[f"geometries/{d}/{f}.mesh"] = data
        pts = [sfmesh.decode_position(p, m.scale) for p in m.positions]
        sphere, box = sfnif.bounds_from_points(pts)
        st = sfnif.StaticShape(s.name or f"Shape{i}".encode(), f"{d}\\{f}".encode(), len(m.triangles) * 3, len(m.positions),
                               material_paths[i], sphere, box)
        all_pts += pts
        if s.block in moving_blocks:
            moving_shapes.append(st)
            moving_pts += pts
        else:
            static_shapes.append(st)
    if not moving_shapes:
        raise nifmod.NifError("door has no moving geometry")
    blob = None
    if collision_template is not None:          # box around the leaf (hinge-local): the body the player activates
        lo = [min(p[a] for p in moving_pts) for a in range(3)]
        hi = [max(p[a] for p in moving_pts) for a in range(3)]
        blob = sfcollision.box_blob(collision_template, tuple((lo[a] + hi[a]) / 2 for a in range(3)),
                                    tuple(max(0.02, (hi[a] - lo[a]) / 2) for a in range(3)))
        if leaf_physics_donor is not None:      # a static body pins its node: make it keyframed like vanilla door leaves
            blob = sfcollision.keyframed(blob, leaf_physics_donor)
    out = sfnif.build_door_nif(out_name.rsplit("/", 1)[-1].encode(), static_shapes, moving_shapes, template,
                               leaf_collision=blob)
    files[f"meshes/{out_name}.nif"] = nifmod.serialize(out)
    hp = template["hinge_pos"]
    bounds = ([min(p[a] for p in all_pts) + hp[a] for a in range(3)], [max(p[a] for p in all_pts) + hp[a] for a in range(3)])
    return files, tuple(pivot[a] * unit_scale - hp[a] for a in range(3)), bounds
