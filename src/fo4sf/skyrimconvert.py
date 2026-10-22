"""Skyrim (Special Edition) static models -> Starfield NIF + .mesh + .mat + DDS, on top of pipeline.Converter.

What is reused unchanged: Starfield mesh / NIF writing (convert_static.shape_to_mesh, sfnif.build_static_nif), texture
conversion and caps (Converter._convert_texture_set: colour BC1, normal BC5, roughness BC4, opacity BC4), the cloned
vanilla material templates (opaque, alpha-tested cutout, decal), the neutral fallback material, and the box-collision
writer verified in game (sfcollision.box_blob).

What is Skyrim's: geometry (skyrimnif.trishapes: BS 100 BSTriShape, NiTriShape / NiTriStrips), materials named by
BSShaderTextureSet (diffuse + normal; Skyrim keeps specular in the normal map's alpha and has no smoothness map, so
roughness is the converter's uniform "fairly rough"), NiAlphaProperty test / blend (foliage cutouts, decals), and
collision: Skyrim's own Havok collision decoded to triangles (skyrimnif.collision_bodies) and, with a Starfield mesh
template, encoded as native Starfield compressed-mesh bodies, one per Skyrim body with its layer (cmsencode,
meshcollision.mesh_body; 2026-10-22); otherwise, or if that fails, rebuilt as Starfield boxes (sfcollision.mesh_boxes:
thin boxes behind flat surfaces + voxel boxes for the rest, which put ledges on ramps: docs/interior/skyrim-interiors.md). A model Skyrim gives no
collision gets none (grass, small plants, cobwebs: the player walks through them in Skyrim too). Boxes are an
approximation of curved rock and tree collision, not Starfield's native mesh shape (see docs/terrain/skyrim-objects.md).
"""
import dataclasses
import hashlib
import os
import re
from typing import Dict, List, Optional

from . import convert_static, nif as nifmod, pipeline, sfcollision, sfmesh, sfnif, skyrimnif

UNIT = 1.0 / 70.0
# landscape pieces (rocks, cliffs, mountains, boulders): solid from below, what matters is the walkable top and the
# sides, so they get column boxes; everything else (buildings, ruins, bridges, trees, props) keeps the surface/voxel
# boxes FO4 architecture uses (thin walls, floors and arches stay open)
LANDSCAPE_RE = re.compile(r"[\\/]landscape[\\/]|rock|cliff|mountain|boulder|glacier|iceberg", re.I)
COLUMN_MIN_BOXES, COLUMN_MAX_BOXES = 128, 512


def column_budget(points) -> int:
    """Boxes a landscape piece may use: one per 16 m2 of footprint, at least 128, at most 512."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    area = (max(xs) - min(xs)) * (max(ys) - min(ys))
    return int(min(COLUMN_MAX_BOXES, max(COLUMN_MIN_BOXES, area / 16.0)))


def _surface_samples(P, T, spacing):
    """Vertices plus barycentric samples so that no point of any triangle is farther than about `spacing` from one."""
    import numpy as np
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    edge = np.max(np.stack([np.linalg.norm(a - b, axis=1), np.linalg.norm(b - c, axis=1),
                            np.linalg.norm(c - a, axis=1)]), axis=0)
    k = np.clip(np.ceil(edge / spacing), 1, 64).astype(np.int64)
    out = [P]
    for kk in np.unique(k):
        if kk < 2:
            continue
        sel = k == kk
        w = np.array([(i / kk, j / kk) for i in range(kk + 1) for j in range(kk + 1 - i)])
        u, v = w[:, 0][None, :, None], w[:, 1][None, :, None]
        pts = (1 - u - v) * a[sel][:, None, :] + u * b[sel][:, None, :] + v * c[sel][:, None, :]
        out.append(pts.reshape(-1, 3))
    return np.concatenate(out)


def column_boxes(points, triangles, max_boxes=None, cell=None, report=None):
    """Axis-aligned boxes covering a solid landscape piece: the collision surface is rasterised into vertical columns of
    `cell` metres (each spans from the piece's lowest point up to the highest surface point in it), columns are merged along x then y where
    their bottoms and tops agree within a tolerance, and the grid coarsens (x 1.25) until the count fits the budget
    (column_budget unless given). Nothing is dropped: a large piece gets coarser columns, never holes. Walkable tops
    keep the surface height within about half a cell times the slope. Returns [(centre, half)]."""
    import numpy as np
    P = np.asarray(points, np.float64)
    T = np.asarray(triangles, np.int64)
    budget = max_boxes or column_budget(points)
    lo, hi = P.min(axis=0), P.max(axis=0)
    area = max((hi[0] - lo[0]) * (hi[1] - lo[1]), 1e-6)
    cell = cell or max(0.5, 0.5 * (area / budget) ** 0.5)       # start near the size that can fit the budget
    S = _surface_samples(P, T, cell / 2.0)
    while True:
        ix = np.floor((S[:, 0] - lo[0]) / cell).astype(np.int64)
        iy = np.floor((S[:, 1] - lo[1]) / cell).astype(np.int64)
        key = ix * (iy.max() + 2) + iy
        order = np.argsort(key, kind="stable")
        ks, zs = key[order], S[order, 2]
        starts = np.flatnonzero(np.r_[True, ks[1:] != ks[:-1]])
        zmax = np.maximum.reduceat(zs, starts)
        cx, cy = ix[order][starts], iy[order][starts]
        # solid from the piece's lowest point: Skyrim rock collision is often open underneath (sunk into the
        # ground); a column then still blocks from below, and merging depends on the tops only
        cols = {(int(x), int(y)): (float(lo[2]), float(b)) for x, y, b in zip(cx, cy, zmax)}
        tol = max(0.1, 0.3 * cell)
        runs = []                                   # merge along x into runs, then equal x spans along y
        for y in sorted({k[1] for k in cols}):
            cur = None
            for x in sorted(k[0] for k in cols if k[1] == y):
                z0, z1 = cols[(x, y)]
                if cur and x == cur[1] + 1 and abs(z0 - cur[2]) <= tol and abs(z1 - cur[3]) <= tol:
                    cur = [cur[0], x, min(cur[2], z0), max(cur[3], z1), y, y]
                else:
                    if cur:
                        runs.append(cur)
                    cur = [x, x, z0, z1, y, y]
            if cur:
                runs.append(cur)
        merged, open_ = [], {}
        for r in sorted(runs, key=lambda r: (r[4], r[0])):
            o = open_.get((r[0], r[1]))
            if o and r[4] == o[5] + 1 and abs(r[2] - o[2]) <= tol and abs(r[3] - o[3]) <= tol:
                o[2], o[3], o[5] = min(o[2], r[2]), max(o[3], r[3]), r[4]
            else:
                if o:
                    merged.append(o)
                open_[(r[0], r[1])] = list(r)
        merged += open_.values()
        if len(merged) <= budget:
            boxes = []
            for x0, x1, z0, z1, y0, y1 in merged:
                bl = (lo[0] + x0 * cell, lo[1] + y0 * cell, z0)
                bh = (min(lo[0] + (x1 + 1) * cell, hi[0]), min(lo[1] + (y1 + 1) * cell, hi[1]), max(z1, z0 + 0.05))
                boxes.append((tuple((bl[k] + bh[k]) / 2 for k in range(3)), tuple((bh[k] - bl[k]) / 2 for k in range(3))))
            if report is not None:
                report["column_cell_m"] = round(cell, 3)
                report["boxes"] = len(boxes)
                report["column_budget"] = budget
            return boxes
        cell *= 1.25


def native_collision(src: nifmod.NifFile, sf_mesh_template: bytes, report: dict) -> list:
    """The model's own Skyrim collision as native Starfield bodies: one compressed-mesh body per Skyrim rigid body, same
    triangles (metres, root frame), same Havok layer (stair helpers stay stair helpers). Non-solid bodies (triggers,
    portals, AI / sound volumes) get none. Raises on anything it cannot encode (the caller falls back to boxes)."""
    from . import meshcollision
    bodies = skyrimnif.collision_bodies(src, report)
    blobs, skipped, n_tris = [], {}, 0
    for layer, pts, tris in bodies:
        if layer in meshcollision.NON_SOLID_LAYERS:
            skipped[str(layer)] = skipped.get(str(layer), 0) + 1
            continue
        if not tris:
            continue
        m = [(x * UNIT, y * UNIT, z * UNIT) for x, y, z in pts]
        blobs.append(meshcollision.mesh_body(m, tris, sf_mesh_template, layer))
        n_tris += len(tris)
    report["source"] = "skyrim-native" if blobs else "skyrim-none"
    report["bodies"] = len(blobs)
    report["layers"] = sorted({str(l) for l, _p, t in bodies if t and l not in meshcollision.NON_SOLID_LAYERS})
    report["skyrim_collision_triangles"] = n_tris
    if skipped:
        report["skipped_layers"] = skipped
    return blobs


def collision_boxes(src: nifmod.NifFile, template: bytes, report: dict, landscape: bool = False) -> list:
    """Starfield single-box physics blobs approximating the model's own Skyrim collision (metres), or []. Non-solid
    bodies (meshcollision.NON_SOLID_LAYERS) are left out: a trigger volume made into boxes is an invisible wall."""
    from . import meshcollision
    pts, tris = skyrimnif.collision_triangles(src, report, skip_layers=tuple(meshcollision.NON_SOLID_LAYERS))
    if not tris:
        report["source"] = "skyrim-none"
        return []
    m = [(x * UNIT, y * UNIT, z * UNIT) for x, y, z in pts]
    lo = [min(p[a] for p in m) for a in range(3)]
    hi = [max(p[a] for p in m) for a in range(3)]
    report["collision_bounds_m"] = [[round(v, 3) for v in lo], [round(v, 3) for v in hi]]
    if landscape:
        boxes = column_boxes(m, tris, report=report)
        report["method"] = "columns"
    else:
        boxes = sfcollision.mesh_boxes(m, tris, report=report)
        report["method"] = "surfaces+voxels"
    report["source"] = "skyrim-boxes"
    return [sfcollision.box_blob(template, c, h) for c, h in boxes]


MAX_VERTICES = 0xFFFF                 # Starfield .mesh triangle indices are u16


def with_back_faces(s: nifmod.Fo4Shape) -> Optional[nifmod.Fo4Shape]:
    """The shape plus a mirrored copy of every triangle (reversed winding, normals negated, tangents kept so the
    recomputed handedness flips with the normal): a double-sided Skyrim surface as plain one-sided Starfield geometry,
    with no new material type. None when the doubled vertex count would not fit u16 indices."""
    nv = len(s.positions)
    if 2 * nv > MAX_VERTICES:
        return None
    return dataclasses.replace(
        s, positions=list(s.positions) * 2, uvs=list(s.uvs) * 2 if s.uvs else s.uvs,
        normals=list(s.normals) + [(-x, -y, -z) for x, y, z in s.normals] if s.normals else s.normals,
        tangents=list(s.tangents) * 2 if s.tangents else s.tangents,
        colors=list(s.colors) * 2 if s.colors else s.colors,
        triangles=[tuple(t) for t in s.triangles] + [(a + nv, c + nv, b + nv) for a, b, c in s.triangles])


def convert_static_sse(src: nifmod.NifFile, shapes: List[nifmod.Fo4Shape], out_name: str, material_paths: list,
                       collision_template: Optional[bytes], report: dict, landscape: bool = False,
                       sf_mesh_template: Optional[bytes] = None) -> Dict[str, bytes]:
    """sf_mesh_template (a vanilla Starfield multi-shape physics blob, meshcollision.UNIVERSAL_TEMPLATE_NIF): Skyrim's
    own collision becomes native Starfield mesh bodies (native_collision); boxes are the fallback, with the reason in
    report["native_error"]."""
    files, static_shapes, all_pts = {}, [], []
    for i, s in enumerate(shapes):
        if material_paths[i] is None:                 # effect shader / refraction / skipped shape
            continue
        m = convert_static.shape_to_mesh(s, UNIT)
        data = sfmesh.serialize(m)
        d, f = convert_static.mesh_file_path(data)
        files[f"geometries/{d}/{f}.mesh"] = data
        pts = [sfmesh.decode_position(p, m.scale) for p in m.positions]
        all_pts += pts
        sphere, box = sfnif.bounds_from_points(pts)
        static_shapes.append(sfnif.StaticShape(s.name or f"Shape{i}".encode(), f"{d}\\{f}".encode(),
                                               len(m.triangles) * 3, len(m.positions), material_paths[i], sphere, box))
    if not static_shapes:
        raise nifmod.NifError("no shape left after skipping effect shaders")
    lo = [min(p[a] for p in all_pts) for a in range(3)]
    hi = [max(p[a] for p in all_pts) for a in range(3)]
    report["render_bounds_m"] = [[round(v, 3) for v in lo], [round(v, 3) for v in hi]]
    blobs = None
    if sf_mesh_template is not None:
        try:
            blobs = native_collision(src, sf_mesh_template, report)
        except Exception as e:                       # noqa: BLE001  (fallback by design, reason recorded)
            report["native_error"] = f"{type(e).__name__}: {e}"
            for k in ("source", "bodies", "layers", "skipped_layers"):
                report.pop(k, None)
    if blobs is None:
        blobs = collision_boxes(src, collision_template, report, landscape) if collision_template is not None else []
    if report.get("source") == "skyrim-native" and "collision_bounds_m" not in report:
        pts = [p for _l, v, _t in skyrimnif.collision_bodies(src) for p in v]
        if pts:
            report["collision_bounds_m"] = [[round(min(p[a] for p in pts) * UNIT, 3) for a in range(3)],
                                            [round(max(p[a] for p in pts) * UNIT, 3) for a in range(3)]]
    if "collision_bounds_m" in report:               # sanity on real data: collision should overlap the visible model
        cl, ch = report["collision_bounds_m"]
        overlap = all(cl[a] <= hi[a] + 0.5 and ch[a] >= lo[a] - 0.5 for a in range(3))
        report["collision_overlaps_render"] = overlap
    node = out_name.rsplit("/", 1)[-1].encode()
    out = sfnif.build_static_nif(node, static_shapes, child_collision_blobs=blobs)
    files[f"meshes/{out_name}.nif"] = nifmod.serialize(out)
    return files


def convert_skinned_sse(shapes: List[nifmod.Fo4Shape], out_name: str, material_paths: list, bone: str,
                        report: dict) -> Dict[str, bytes]:
    """A worn NIF in which every vertex rides one Starfield bone (rigid skinning, e.g. a weapon held by a bone):
    shapes must already be in that bone's local frame; the bind is identity (drawn at bone_world * vertex), so the
    result does not depend on the skeleton's rest pose."""
    files, skinned = {}, []
    lo, hi = [float("inf")] * 3, [float("-inf")] * 3
    for i, s in enumerate(shapes):
        if material_paths[i] is None:
            continue
        m = convert_static.shape_to_mesh(s, UNIT)
        m.weights_per_vertex = 4
        m.weights = [(0, 65535), (0, 0), (0, 0), (0, 0)] * len(m.positions)
        data = sfmesh.serialize(m)
        d, f = convert_static.mesh_file_path(data)
        files[f"geometries/{d}/{f}.mesh"] = data
        pts = [sfmesh.decode_position(p, m.scale) for p in m.positions]
        for p in pts:
            for a in range(3):
                lo[a], hi[a] = min(lo[a], p[a]), max(hi[a], p[a])
        (cx, cy, cz, r), _box = sfnif.bounds_from_points(pts)
        skinned.append(sfnif.SkinnedShape(s.name or f"Shape{i}".encode(), f"{d}\\{f}".encode(), len(m.triangles) * 3,
                                          len(m.positions), material_paths[i], [bone.encode()],
                                          [((cx, cy, cz, r), (1, 0, 0, 0, 1, 0, 0, 0, 1), (0, 0, 0), 1.0)]))
    if not skinned:
        raise nifmod.NifError("no shape left after skipping effect shaders")
    report["render_bounds_m"] = [[round(v, 3) for v in lo], [round(v, 3) for v in hi]]
    report["skinned_to"] = bone
    out = sfnif.build_skinned_nif(out_name.rsplit("/", 1)[-1].encode(), skinned)
    files[f"meshes/{out_name}.nif"] = nifmod.serialize(out)
    return files


class SkyrimConverter(pipeline.Converter):
    """pipeline.Converter with a Skyrim source (bsa.SkyrimArchives) and Skyrim materials / geometry / collision."""

    def __init__(self, src, staging, texconv_exe, content_resources, collision_template=None, prefix="skyrim",
                 max_texture=None, shape_hook=None, sf_mesh_template=None):
        super().__init__(src, staging, texconv_exe, content_resources, collision_template, prefix=prefix,
                         no_collision_pattern="", max_texture=max_texture)
        # shape_hook(nif, shapes, report) -> shapes: change the geometry before conversion (skyrimweapon.weapon_shapes
        # moves weapons into Starfield's WEAPON frame and drops scabbards)
        self.shape_hook = shape_hook
        self.sf_mesh_template = sf_mesh_template      # native Skyrim collision (convert_static_sse); None = boxes

    def skyrim_material(self, diffuse: str, normal: str, test: bool, blend: bool, ref: int,
                        flat_normal_ok: bool = False, albedo_tint: Optional[tuple] = None) -> Optional[str]:
        kind = "decal" if blend and not test else "cutout" if test else "opaque"
        ident = "|".join([diffuse.replace("\\", "/").lower(), normal.replace("\\", "/").lower(), kind, str(ref)]
                         + ([",".join(f"{v:.3f}" for v in albedo_tint)] if albedo_tint else []))
        stem = re.sub(r"^textures[\\/]", "", diffuse.replace("\\", "/"), flags=re.I).lower()
        stem = os.path.splitext(stem)[0] + "_" + hashlib.sha1(ident.encode()).hexdigest()[:8]
        if kind == "decal":
            stem = "decals/" + stem
        key = "sky:" + stem
        if key not in self._materials:
            try:
                self._materials[key] = self._convert_texture_set(stem, diffuse, normal, "", alpha_test=test,
                                                                 alpha_ref=ref, decal=(kind == "decal"),
                                                                 flat_normal_ok=flat_normal_ok,
                                                                 albedo_tint=albedo_tint)
                self.stats["materials_ok"] += 1
            except Exception as e:                    # noqa: BLE001  (fallback by design; reason is recorded)
                self._materials[key] = None
                self.stats["materials_fallback"] += 1
                self.material_errors[key] = f"{type(e).__name__}: {e}"
        return self._materials[key]

    def _shape_material(self, src, s, flat_normal_ok: bool = False,
                        albedo_tint: Optional[tuple] = None) -> Optional[str]:
        """flat_normal_ok: a diffuse without a normal map converts with a flat normal (Skyrim grass) instead of
        falling back to the neutral material."""
        if s.shader_ref < 0:
            return self.neutral
        kind = src.type_of(s.shader_ref)
        if kind == "BSEffectShaderProperty":          # glow, fog, waterfall spray, magic: not translated
            return None
        if skyrimnif.refraction(src, s.shader_ref):  # heat haze / refraction: not translated, like effect shaders
            return None
        paths = skyrimnif.texture_set(src, s.shader_ref)
        if skyrimnif.normal_map_as_diffuse(paths):
            return None
        if not paths or not paths[0]:
            return self.neutral
        test, blend, ref = skyrimnif.alpha_test(src, s.alpha_ref)
        normal = paths[1] if len(paths) > 1 else ""
        if normal and skyrimnif.model_space_normals(src, s.shader_ref):
            # an object-space normal map would light the surface wrongly in Starfield's tangent-space shader: drop it
            # and light from the mesh's own vertex normals (flat normal map) until a model -> tangent bake exists
            normal, flat_normal_ok = "", True
            self.stats["model_space_normals_dropped"] = self.stats.get("model_space_normals_dropped", 0) + 1
        if not normal and not (blend and not test) and not flat_normal_ok:
            return self.neutral
        mat = self.skyrim_material(paths[0], normal, test, blend, ref, flat_normal_ok=flat_normal_ok,
                                   albedo_tint=albedo_tint)
        if mat is None and blend and not test:
            return None                               # an overlay we could not convert: leave it out, as FO4 does
        return mat or self.neutral

    def convert_nif(self, nif_name: str, skin_bone: Optional[str] = None, out_suffix: str = "") -> dict:
        """skin_bone: write a worn NIF rigidly skinned to that Starfield bone (the shape hook must put the geometry in
        the bone's frame) instead of a static model; out_suffix is appended to the output name."""
        res = {"nif": nif_name, "ok": False}
        try:
            raw = self.src.mesh(nif_name)
            if raw is None:
                raise FileNotFoundError("mesh not in the Skyrim archives or loose files")
            src = nifmod.parse(raw)
            shapes = skyrimnif.trishapes(src)
            hook_report = {}
            if self.shape_hook is not None:
                shapes = self.shape_hook(src, shapes, hook_report)
            if not shapes:
                raise ValueError("no triangle geometry")
            mats = [self._shape_material(src, s) for s in shapes]
            if all(m is None for m in mats):
                raise ValueError("only effect-shader / refraction shapes, skipped")
            doubled = too_big = 0
            for i, s in enumerate(shapes):
                if mats[i] is not None and skyrimnif.double_sided(src, s.shader_ref):
                    d = with_back_faces(s)
                    if d is None:
                        too_big += 1                  # left one-sided: visible from the front only
                    else:
                        shapes[i], doubled = d, doubled + 1
            rel = re.sub(r"^meshes[\\/]", "", nif_name.replace("\\", "/"), flags=re.I)
            out_name = f"{self.prefix}/{os.path.splitext(rel)[0].lower()}{out_suffix}"
            report = {}
            if skin_bone:
                files = convert_skinned_sse(shapes, out_name, mats, skin_bone, report)
            else:
                files = convert_static_sse(src, shapes, out_name, mats, self.collision_template, report,
                                           landscape=bool(LANDSCAPE_RE.search(nif_name)),
                                           sf_mesh_template=self.sf_mesh_template)
            for relp, data in files.items():
                p = os.path.join(self.staging, *relp.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as f:
                    f.write(data)
            res.update(ok=True, out_name=out_name, shapes=len(shapes), materials=mats,
                       collision="skyrim" if self.collision_template is not None else None,
                       collision_report=report, skipped_effect_shapes=sum(1 for m in mats if m is None),
                       fallback_materials=sum(1 for m in mats if m == self.neutral),
                       double_sided_shapes=doubled, double_sided_too_big=too_big, **hook_report)
            self.stats["assets"] += 1
        except Exception as e:                       # noqa: BLE001  (recorded per asset, batch continues)
            res["reason"] = f"{type(e).__name__}: {e}"
            self.stats["failed"] += 1
        return res
