"""A Skyrim NPC's outfit fitted onto Starfield's body by the skeleton and body shape (fo4sf.gearfit), without Outfit
Studio (2026-11-06: Outfit Studio's fit left the collar over the face, the gloves following the hips and the coat
folded; owner: "fit the Starfield body the way it does on Skyrim's").

Reads the NPC's default outfit and the Skyrim body from Skyrim's archives, Starfield's body and skeleton from the
game's archives, fits (gearfit.fit), and writes the armor mod: one NIF per shape (meshes\\S2S\\<name>\\<shape>.nif),
its .mesh files and slider morph.dat, and S2SArmorTest.esm with one ARMA + MRPH (morph record) per shape, the ARMO and
an OTFT (os_export.write_armor_parts; --one-nif: the old single NIF). gear_fit.json holds the report.

    python -I scripts\\armor\\gear_fit.py --skyrim-data "<Skyrim>\\Data" --starfield "D:\\...\\Starfield" --npc Ralof ^
        --name Ralof_outfit --full "Stormcloak Cuirass (S2S)" --out "<MO2 mods>\\S2S Armor Test"
"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts", "npc"))

from fo4sf import ba2, bsa, facefit, gearfit, sfmesh, sfmorph, skyrimarmor, skyrimskin  # noqa: E402
from fo4sf import nif as nifmod  # noqa: E402
import hkx_to_af  # noqa: E402
import npc_hair  # noqa: E402
import os_convert  # noqa: E402
import os_export  # noqa: E402


def sky_shapes(nif_bytes: bytes):
    return [gearfit.from_skyrim(s) for s in skyrimskin.skinned_shapes(nifmod.parse(nif_bytes))]


TEXCONV_DEFAULT = r"C:\Modding\tools\texconv.exe"      # the owner's (found 2026-11-06)
TEXCONV_OTHERS = (r"C:\Modding\tools\xedit\Edit Scripts\Texconvx64.exe",)


def find_texconv(given: str = "") -> str:
    import shutil
    for c in (given, TEXCONV_DEFAULT, *TEXCONV_OTHERS, shutil.which("texconv") or "", shutil.which("texconv.exe") or ""):
        if c and os.path.isfile(c):
            return c
    return ""


def shape_materials(conv, nif_bytes: bytes) -> dict:
    """{shape name: Starfield .mat path} for a Skyrim NIF's skinned shapes, converted by the repo's Skyrim texture
    pipeline (SkyrimConverter: colour / normal / rough DDS + .mat, alpha test kept); None when it fell back."""
    n = nifmod.parse(nif_bytes)
    out = {}
    for s in skyrimskin.skinned_shapes(n):
        name = s.name.decode("latin-1", "replace")
        try:
            out[name] = conv._shape_material(n, s)
        except Exception as e:                           # report, keep going: the shape keeps the fallback material
            conv.material_errors[name] = f"{type(e).__name__}: {e}"
            out[name] = None
        if out[name] == conv.neutral:
            out[name] = None
    return out


def double_sided_shapes(nif_bytes: bytes) -> set:
    """Names of a Skyrim NIF's shapes whose shader is double-sided (Skyrim draws their back faces too)."""
    from fo4sf import skyrimnif
    n = nifmod.parse(nif_bytes)
    return {s.name.decode("latin-1", "replace") for s in skyrimskin.skinned_shapes(n)
            if skyrimnif.double_sided(n, s.shader_ref)}


def shape_textures(nif_bytes: bytes) -> dict:
    """{shape name: its texture set (diffuse first)} of a Skyrim NIF."""
    from fo4sf import skyrimnif
    n = nifmod.parse(nif_bytes)
    out = {}
    for s in skyrimskin.skinned_shapes(n):
        try:
            out[s.name.decode("latin-1", "replace")] = skyrimnif.texture_set(n, s.shader_ref) or []
        except Exception as e:                       # report, keep going
            out[s.name.decode("latin-1", "replace")] = [f"? {e}"]
    return out


def starfield_body(sf_data: str, female: bool):
    """(points mesh space, triangles, body binds {bone: bind}) of the game's naked body."""
    nif, _ = hkx_to_af.vanilla_file(os_convert.SF_BODY[female], sf_data)
    paths, skin = facefit.starfield_head_parts(nif)
    m = sfmesh.parse(hkx_to_af.vanilla_file("geometries/" + paths[0].replace("\\", "/") + ".mesh", sf_data)[0])
    pts, w = facefit.mesh_arrays(m)
    tris = np.array([tuple(t) for t in m.triangles], int).reshape(-1, 3)
    names = [b.decode("latin-1") for b in skin.get("bones", [])]
    binds = dict(zip(names, skin.get("binds", [])))
    weights = [[(names[b], x) for b, x in vw if b < len(names)] for vw in w]
    return pts, tris, binds, weights


def starfield_body_skin(sf_data: str, female: bool):
    """(UVs per vertex, material path) of the game's naked body: for our skin piece, cut from it like the vanilla
    outfits' own (AA_Clothes_Nightwear_01_Skin: a 938-vertex cut with Naked_M_Body.mat; slot_probe 2026-11-06)."""
    import slot_probe
    nif, _ = hkx_to_af.vanilla_file(os_convert.SF_BODY[female], sf_data)
    paths, _skin = facefit.starfield_head_parts(nif)
    m = sfmesh.parse(hkx_to_af.vanilla_file("geometries/" + paths[0].replace("\\", "/") + ".mesh", sf_data)[0])
    uv = np.array(m.uv1, np.uint16).reshape(-1, 2).view(np.float16).astype(float)
    mat = next((r["material"] for r in slot_probe.model_shapes(nif) if r["material"]), "")
    return [tuple(map(float, x)) for x in uv], mat


HIDE_BODY_SLOTS = [3, 5, 7]   # as vanilla outfits: 3 hides the naked body (nightwear upper body 3 + 5, lower 7)
SKIN_REACH = 0.03       # m: Starfield body vertices this close to a fitted Skyrim bare-skin piece show as skin
SKIN_SHAPE = b"S2S_Skin"


COVER_DEPTH = 0.06      # m: a body point with gear this close straight out from it counts as covered
COVER_MARGIN = 5        # rings of covered vertices kept along the edge of the visible skin (overlap under the gear;
#                         2026-11-07: with 2, a strip of bare body showed between the skin piece and the sleeve hems)


def covered_by(body: np.ndarray, body_nrm: np.ndarray, gear, depth: float = COVER_DEPTH) -> np.ndarray:
    """Which body points have gear straight out from them (closest gear point within `depth`, in the direction of the
    body's normal): skin there is never seen."""
    out = np.zeros(len(body), bool)
    for g in gear:
        gp = np.asarray(g.positions, float)
        gt = np.asarray(g.triangles, int).reshape(-1, 3)
        if not len(gt):
            continue
        gn = np.asarray(g.normals, float)
        lo, hi = gp.min(0) - depth, gp.max(0) + depth
        cand = np.nonzero(((body >= lo) & (body <= hi)).all(1) & ~out)[0]
        if not len(cand):
            continue
        cp, _s, dist = gearfit.closest_on_mesh(body[cand], gp, gt, gn)
        dirn = (cp - body[cand]) / np.maximum(dist, 1e-9)[:, None]
        hit = (dist < depth) & (np.einsum("ij,ij->i", dirn, body_nrm[cand]) > 0.5)
        out[cand[hit]] = True
    return out


def skin_piece(body_skel: np.ndarray, body_tris, body_uvs, body_w, sources: np.ndarray, reach: float = SKIN_REACH,
               gear=(), margin: int = COVER_MARGIN):
    """(HairShape in skeleton space, kept body vertex indices) of the Starfield body where Skyrim's bare-skin pieces
    lie after the fit (2026-11-06, owner: Skyrim's bare arm runs up under the sleeve, Starfield's skin starts lower):
    the body vertices within `reach` of them and the triangles among them. None when nothing is kept."""
    from fo4sf import skyrimhair
    if not len(sources):
        return None, []
    zero = np.tile([0.0, 0.0, 1.0], (len(sources), 1))
    _d, dist, _i = skyrimhair.nearest_surface(body_skel, sources, zero)
    keep = dist < reach
    t = np.asarray(body_tris, int).reshape(-1, 3)
    if len(gear):
        # only the skin that shows, plus a narrow overlap under the gear's edges (2026-11-06: under the cowl the skin
        # piece grew past the cowl on heavier bodies and showed through on the chest)
        bn = skyrimhair._vertex_face_normals(body_skel, t)
        bn /= np.maximum(np.linalg.norm(bn, axis=1, keepdims=True), 1e-12)
        cov = covered_by(body_skel, bn, gear) & keep
        visible = keep & ~cov
        grow = visible.copy()
        for _ in range(margin):
            touch = np.zeros(len(body_skel), bool)
            on = grow[t].any(1)
            touch[t[on].reshape(-1)] = True
            grow |= touch & keep
        keep = grow
    t = t[keep[t].all(1)]
    used = np.unique(t)
    if not len(used):
        return None, []
    new = -np.ones(len(body_skel), int)
    new[used] = np.arange(len(used))
    pos = body_skel[used]
    tri = new[t]
    nrm = skyrimhair._vertex_face_normals(body_skel, t)[used]
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    # the body's own weights, up to 8 per vertex (the writer stores 8 when needed; 2026-11-06: more than the writer's
    # slots shifted the next vertices onto wrong bones and threw the skin piece into shards, and 4 bent it apart from
    # the game's hands mesh)
    w4 = []
    for i in used:
        top = sorted(body_w[i], key=lambda kv: -kv[1])[:8]
        tot = sum(x for _b, x in top)
        w4.append([(b, x / tot) for b, x in top] if tot > 0 else top)
    sh = skyrimhair.HairShape(SKIN_SHAPE, pos, nrm, np.zeros_like(nrm), [body_uvs[i] for i in used],
                              [tuple(map(int, x)) for x in tri], w4, -1, -1, -1,
                              colors=[(255, 255, 255, 255)] * len(pos))
    return sh, used.tolist()


HAND_BONES = ("L_Wrist", "R_Wrist", "L_Index", "R_Index")


def sex_ok(base: str, female: bool) -> bool:
    """Whether a file name can be for this sex (names without a sex mark count for both)."""
    is_f = "female" in base or "_f." in base or "_f_" in base
    is_m = ("male" in base and "female" not in base) or "_m." in base or "_m_" in base
    return not is_m if female else not is_f


SF_HEADS = {False: "meshes/actors/human/characterassets/male/malehead_facebones.nif",
            True: "meshes/actors/human/characterassets/female/femalehead_facebones.nif"}
SKY_HEADS = {False: "meshes\\actors\\character\\character assets\\malehead.nif",
             True: "meshes\\actors\\character\\character assets\\femalehead.nif"}


def starfield_part(sf_data: str, nif_path: str, world):
    """(points in skeleton space, triangles, weights by bone name) of a vanilla skinned NIF's first shape (the head:
    the body mesh stops at the base of the neck, 2026-11-06: the cowl was fitted against the shoulders only)."""
    paths, skin = facefit.starfield_head_parts(hkx_to_af.vanilla_file(nif_path, sf_data)[0])
    m = sfmesh.parse(hkx_to_af.vanilla_file("geometries/" + paths[0].replace("\\", "/") + ".mesh", sf_data)[0])
    pts, w = facefit.mesh_arrays(m)
    bones = [b.decode("latin-1") for b in skin.get("bones", [])]
    frame = gearfit.mesh_frame(dict(zip(bones, skin.get("binds", []))), world)
    tris = np.array([tuple(t) for t in m.triangles], int).reshape(-1, 3)
    weights = [[(bones[b], x) for b, x in vw if b < len(bones)] for vw in w]
    return pts @ frame[:3, :3].T + frame[:3, 3], tris, weights


NECK_BONES_SF = ("C_Neck", "C_Neck1", "C_Neck_Twist", "C_Chest", "C_Spine2")
NECK_BONES_SKY = ("NPC Neck [Neck]", "NPC Spine2 [Spn2]")
NECK_SHARE = 0.3        # head vertices with at least this weight on neck / chest bones count as neck


def neck_part(points, tris, weights, neck_bones, share: float = NECK_SHARE):
    """The neck of a head mesh: vertices with >= share of their weight on neck / chest bones, and the triangles
    among them (2026-11-06: with the whole head in the surface, the cover step pushed Ralof's cowl out over the chin and
    jaw). weights: per vertex [(bone name, w)]. Returns (points, triangles, weights, kept vertex count)."""
    keep = np.array([sum(w for b, w in vw if b in neck_bones) >= share for vw in weights], bool)
    if not keep.any():
        return np.zeros((0, 3)), np.zeros((0, 3), int), [], 0
    new = -np.ones(len(points), int)
    new[keep] = np.arange(int(keep.sum()))
    t = np.asarray(tris, int).reshape(-1, 3)
    t = t[keep[t].all(1)]
    return np.asarray(points)[keep], new[t], [weights[i] for i in np.nonzero(keep)[0]], int(keep.sum())


def skyrim_head_shapes(nif_bytes: bytes):
    """The neck of the Skyrim head NIF's head shape (not face / eyes / mouth), as SkyShapes."""
    from fo4sf import skyrimnpc
    shapes = skyrimskin.skinned_shapes(nifmod.parse(nif_bytes))
    h = skyrimnpc.head_shape(shapes)
    if h is None:
        return []
    s = gearfit.from_skyrim(h)
    named = [[(s.bones[b], w) for b, w in vw if 0 <= b < len(s.bones)] for vw in s.weights]
    p, t, _w, n = neck_part(s.points, s.triangles, named, NECK_BONES_SKY)
    if not n:
        return []
    keep = [i for i, vw in enumerate(named) if sum(w for b, w in vw if b in NECK_BONES_SKY) >= NECK_SHARE]
    return [gearfit.SkyShape(s.name, p, s.normals[keep], [s.uvs[i] for i in keep] if s.uvs else [],
                             [tuple(map(int, x)) for x in t], s.bones, [s.weights[i] for i in keep], s.joints)]


def skyrim_head_mesh(nif_bytes: bytes):
    """(points, triangles) of the whole Skyrim head shape in Skyrim space, or None."""
    from fo4sf import skyrimnpc
    h = skyrimnpc.head_shape(skyrimskin.skinned_shapes(nifmod.parse(nif_bytes)))
    if h is None:
        return None
    s = gearfit.from_skyrim(h)
    return np.asarray(s.points, float), np.asarray(s.triangles, int).reshape(-1, 3)


def find_hands(sf_data: str, female: bool, world):
    """(path, points in skeleton space, triangles) of the game's hands mesh (a separate mesh from the naked body, so
    the push-out must see it too; 2026-11-06: Starfield fingers poked through the converted gloves), or (None, ...)."""
    from fo4sf import sfnif
    for fn in sorted(os.listdir(sf_data)):
        low = fn.lower()
        if not (low.startswith("starfield - meshes") and low.endswith(".ba2")):
            continue
        arc = ba2.Ba2(os.path.join(sf_data, fn))
        for i, name in enumerate(arc.names):
            p = name.replace("\\", "/").lower()
            base = p.rsplit("/", 1)[-1]
            if not (p.startswith("meshes/actors/human/") and p.endswith(".nif") and "hand" in base):
                continue
            if "1st" in base or not sex_ok(base, female):
                continue
            try:
                paths, skin = facefit.starfield_head_parts(arc.read(i))
            except Exception:
                continue
            bones = [b.decode("latin-1") for b in skin.get("bones", [])]
            if not paths or not any(b in bones for b in HAND_BONES):
                continue
            try:
                m = sfmesh.parse(hkx_to_af.vanilla_file("geometries/" + paths[0].replace("\\", "/") + ".mesh",
                                                        sf_data)[0])
            except SystemExit:
                continue
            pts, hw = facefit.mesh_arrays(m)
            frame = gearfit.mesh_frame(dict(zip(bones, skin.get("binds", []))), world)
            tris = np.array([tuple(t) for t in m.triangles], int).reshape(-1, 3)
            weights = [[(bones[b], x) for b, x in vw if b < len(bones)] for vw in hw]
            return p, pts @ frame[:3, :3].T + frame[:3, 3], tris, weights
    return None, None, None, None


def find_body_morph(sf_data: str, num_vertices: int, female: bool):
    """(path, Morph) of the game's chargen morph.dat for the naked body: the one under meshes/morphs/human/<sex>/
    with exactly the body mesh's vertex count and the Overweight key."""
    sex = "female" if female else "male"
    for fn in sorted(os.listdir(sf_data)):
        low = fn.lower()
        if not (low.startswith("starfield - ") and low.endswith(".ba2")):
            continue
        arc = ba2.Ba2(os.path.join(sf_data, fn))
        for i, name in enumerate(arc.names):
            p = name.replace("\\", "/").lower()
            if not (p.startswith(f"meshes/morphs/human/{sex}/") and p.endswith("morph.dat")):
                continue
            data = arc.read(i)
            try:
                head = sfmorph.parse(data)
            except sfmorph.MorphError:
                continue
            if head.num_vertices == num_vertices and "Overweight" in head.keys:
                return p, head
    return None, None


# Skyrim keeps the feet and hands out of the body mesh (2026-11-06: with malebody_1 alone there was no Skyrim foot to
# size the boots by)
SKYRIM_LIMBS = {False: ["meshes\\actors\\character\\character assets\\malefeet_1.nif",
                        "meshes\\actors\\character\\character assets\\malehands_1.nif"],
                True: ["meshes\\actors\\character\\character assets\\femalefeet_1.nif",
                       "meshes\\actors\\character\\character assets\\femalehands_1.nif"]}


SKIN_TEXTURES = "textures\\actors\\character\\"     # Skyrim's body / hands / feet skin


def body_skin_shapes(textures: dict) -> set:
    """The bare-skin shapes textured with Skyrim's BODY skin (not hands: Starfield's hands stay on their own slot)."""
    return {n for n in skin_shapes(textures) if "body" in textures[n][0].lower()}


def skin_shapes(textures: dict) -> set:
    """Names of shapes textured with Skyrim's own skin (bare body parts: Starfield's body shows there instead;
    2026-11-06, Ralof: MaleBodyStormcloak = MaleBody_1.dds, HandMale_Big1stperson = MaleHands_1.dds)."""
    return {n for n, t in textures.items() if t and t[0].lower().replace("/", "\\").startswith(SKIN_TEXTURES)}


TESSELLATE = 3                 # low-poly gear split n x n before the fit
TESSELLATE_BELOW = 2000        # vertices: only shapes smaller than this


def flat_subdivide(points, normals, uvs, tris, weights, n: int):
    """Every triangle split n x n on its own flat plane (no curved patch: on Ralof's cowl the PN patches ballooned
    the folds and opened the chest, 2026-11-06). Points on shared edges are shared (same position and UV); UVs,
    normals and weights {bone index: w} interpolated. Returns (points, normals, uvs, tris, weights)."""
    P, N, U = np.asarray(points, float), np.asarray(normals, float), np.asarray(uvs, float)
    W = [dict(vw) for vw in weights]
    pos, nrm, uv, wts, index = [], [], [], [], {}

    def point(t, i, j):
        a, b, c = t
        k = n - i - j
        ba, bb, bc = k / n, i / n, j / n
        corners = [(x, w) for x, w in ((a, ba), (b, bb), (c, bc)) if w > 0]
        if len(corners) == 1:
            key = ("v", corners[0][0])
        else:
            key = ("p",) + tuple(sorted((int(x), round(w, 6)) for x, w in corners))
        if key in index:
            return index[key]
        p_ = ba * P[a] + bb * P[b] + bc * P[c]
        n_ = ba * N[a] + bb * N[b] + bc * N[c]
        u_ = ba * U[a] + bb * U[b] + bc * U[c]
        w_ = {}
        for x, w in ((a, ba), (b, bb), (c, bc)):
            for bone, bw in W[x].items():
                w_[bone] = w_.get(bone, 0.0) + w * bw
        index[key] = len(pos)
        pos.append(p_)
        nrm.append(n_ / (np.linalg.norm(n_) or 1.0))
        uv.append(tuple(map(float, u_)))
        wts.append(sorted(w_.items(), key=lambda kv: -kv[1]))
        return index[key]

    out_t = []
    for t in tris:
        g = {}
        for i in range(n + 1):
            for j in range(n + 1 - i):
                g[i, j] = point(t, i, j)
        for i in range(n):
            for j in range(n - i):
                out_t.append((g[i, j], g[i + 1, j], g[i, j + 1]))
                if i + j < n - 1:
                    out_t.append((g[i + 1, j], g[i + 1, j + 1], g[i, j + 1]))
    return np.array(pos), np.array(nrm), uv, out_t, wts


def tessellate_shapes(gear, n: int = TESSELLATE, below: int = TESSELLATE_BELOW, skip=()):
    """Low-poly Skyrim shapes split into n x n smaller flat triangles before the fit (flat_subdivide) so the fit can
    shape them around Starfield's differently shaped body (2026-11-06, Ralof's boots: 202 vertices; covering the calf
    pushed the flat faces 2.5 cm looser than in Skyrim). Shapes named in skip (dropped skin pieces) are left.
    ([shapes], report)"""
    out, rep = [], {}
    for s in gear:
        name = s.name.decode("latin-1", "replace")
        if n < 2 or len(s.points) >= below or name in skip:
            out.append(s)
            continue
        p, nr, uv, tr, w = flat_subdivide(s.points, s.normals, s.uvs, s.triangles, s.weights, n)
        out.append(gearfit.SkyShape(s.name, p, nr, uv, tr, list(s.bones), w, s.joints))
        rep[name] = [len(s.points), len(p)]
    return out, rep


def write_obj(path: str, pts, tris) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for p in np.asarray(pts, float):
            fh.write(f"v {p[0]:.5f} {p[1]:.5f} {p[2]:.5f}\n")
        for t in np.asarray(tris, int).reshape(-1, 3):
            fh.write(f"f {t[0] + 1} {t[1] + 1} {t[2] + 1}\n")


def safe_name(n: str) -> str:
    """A file name part without characters Windows refuses (':' in 'MaleUnderwearBody:0' wrote an empty file)."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in n)


def debug_meshes(folder: str, shapes, frame, surf_pts, surf_tris, sky_gear, sky_body, sky_head=None,
                 sf_head=None) -> str:
    """OBJ files of the fit for a look from outside the game (Starfield skeleton space, metres): the Starfield body /
    hands / neck surface, every written shape, and the Skyrim gear and body as they came in (Skyrim model space,
    metres). Zipped into fit_debug.zip; returns its path."""
    import zipfile
    os.makedirs(folder, exist_ok=True)
    names = []
    write_obj(os.path.join(folder, "sf_surface.obj"), surf_pts, surf_tris)
    names.append("sf_surface.obj")
    for n, h in (("sf_head.obj", sf_head), ("skyhead_full.obj", sky_head)):    # whole heads (Skyrim: its space)
        if h is not None:
            write_obj(os.path.join(folder, n), *h)
            names.append(n)
    for sh in shapes:
        p = np.asarray(sh.positions) @ frame[:3, :3].T + frame[:3, 3]
        n = "fit_" + safe_name(sh.name.decode("latin-1", "replace")) + ".obj"
        write_obj(os.path.join(folder, n), p, sh.triangles)
        names.append(n)
    for tag, group in (("sky_", sky_gear), ("skybody_", sky_body)):
        for s in group:
            n = tag + safe_name(s.name.decode("latin-1", "replace")) + ".obj"
            write_obj(os.path.join(folder, n), s.points, s.triangles)
            names.append(n)
    z = os.path.join(folder, "fit_debug.zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for n in names:
            zf.write(os.path.join(folder, n), n)
    return z


def run(gear_nifs, body_nif, sf_data: str, female: bool, skip=(), gap: float = gearfit.GAP, skin_names=(),
        size_feet: bool = False, tessellate: int = TESSELLATE, sky_head: bytes = None, body_skin_names=(),
        head_weights: bool = False):
    """(shapes in mesh space with tangents, binds, report). head_weights: gear near the head takes the whole head's
    weights (off by default since 2026-11-07, owner: Skyrim's cowl sits on the outfit, low, and does not follow the
    neck or head; only the body's and neck part's weights are copied)."""
    world = npc_hair.skeleton_world(hkx_to_af.vanilla_file(npc_hair.SF_SKELETON, sf_data)[0])
    pts, tris, body_binds, body_w = starfield_body(sf_data, female)
    frame = gearfit.mesh_frame(body_binds, world)
    skel_pts = pts @ frame[:3, :3].T + frame[:3, 3]
    surf_pts, surf_tris, surf_w = skel_pts, tris, list(body_w)
    hand_path, hand_pts, hand_tris, hand_w = find_hands(sf_data, female, world)
    if hand_pts is not None:
        surf_pts = np.concatenate([skel_pts, hand_pts])
        surf_tris = np.concatenate([tris, hand_tris + len(skel_pts)])
        surf_w += hand_w if len(hand_w) == len(hand_pts) else [[] for _ in hand_pts]
    head_path = SF_HEADS[female]
    weight_src, sf_head_full = None, None
    try:
        h_pts, h_tris, h_w = starfield_part(sf_data, head_path, world)
        sf_head_full = (h_pts, h_tris)
        if head_weights and len(h_w) == len(h_pts):
            # weights also from the whole head: the collar's top takes the head's own neck-skin weights (2026-11-06:
            # with only the neck-weighted part, the collar had no C_Head and stayed facing forward when the head turned)
            weight_src = (np.concatenate([surf_pts, h_pts]), np.concatenate([surf_tris, h_tris + len(surf_pts)]),
                          list(surf_w) + list(h_w))
        h_pts, h_tris, h_w, h_n = neck_part(h_pts, h_tris, h_w, NECK_BONES_SF)
        head_path += f" (neck: {h_n} vertices)"
        surf_tris = np.concatenate([surf_tris, h_tris + len(surf_pts)])
        surf_pts = np.concatenate([surf_pts, h_pts])
        surf_w += h_w
    except (SystemExit, Exception) as e:            # report, keep going without the head
        head_path = f"NOT FOUND ({e})"
    gear = [s for nb in gear_nifs for s in sky_shapes(nb)]
    skipped = [s.name.decode("latin-1") for s in gear if s.name.decode("latin-1").lower() in {x.lower() for x in skip}]
    gear = [s for s in gear if s.name.decode("latin-1") not in skipped]
    gear, tess = tessellate_shapes(gear, tessellate, skip=set(skin_names))
    body_nifs = body_nif if isinstance(body_nif, (list, tuple)) else [body_nif]
    sky_body = [s for nb in body_nifs for s in sky_shapes(nb)]
    sky_head_full = None
    if sky_head:
        sky_body += skyrim_head_shapes(sky_head)
        sky_head_full = skyrim_head_mesh(sky_head)
    if weight_src is not None and len(weight_src[2]) != len(weight_src[0]):
        weight_src = None
    res = gearfit.fit(gear, sky_body, world, surf_pts, surf_tris, gap, sf_body_weights=surf_w, size_feet=size_feet,
                      weight_src=weight_src,
                      heads=(sky_head_full, sf_head_full) if sky_head_full and sf_head_full else None)
    skin = None
    if body_skin_names:                      # our own skin piece where Skyrim's body-skin pieces lie
        src = [np.asarray(sh.positions) for sh in res.shapes if sh.name.decode("latin-1", "replace")
               in set(body_skin_names)]
        if src:
            uvs, mat = starfield_body_skin(sf_data, female)
            skel_body = pts @ frame[:3, :3].T + frame[:3, 3]
            gear_fit_shapes = [sh for sh in res.shapes if sh.name.decode("latin-1", "replace") not in set(skin_names)]
            skin, used = skin_piece(skel_body, tris, uvs, body_w, np.concatenate(src), gear=gear_fit_shapes)
            if skin is not None:
                res.report["skin_piece"] = {"vertices": len(used), "material": mat, "from": sorted(body_skin_names)}
                res.report["_skin_used"] = used
    if skin_names:                           # Skyrim's bare-skin pieces
        drop = {n for n in res.report["shapes"] if n in set(skin_names)}
        res.shapes = [sh for sh in res.shapes if sh.name.decode("latin-1", "replace") not in drop]
        res.report["dropped_skin_pieces"] = sorted(drop)
    if skin is not None:
        res.shapes = list(res.shapes) + [skin]
    shapes = gearfit.to_mesh_space(res.shapes, frame)
    for i, sh in enumerate(shapes):
        sh.tangents = os_export.tangents(np.asarray(sh.positions), np.asarray(sh.normals), sh.uvs, sh.triangles)
        shapes[i] = sh
    bones = sorted({b for sh in shapes for vw in sh.weights for b, _w in vw} | {"C_Chest"})
    binds = gearfit.skeleton_binds(bones, world, frame, shapes)
    res.report.update(skipped=skipped, frame=frame.round(6).tolist(), hands=hand_path, tessellated=tess,
                      head=head_path, skyrim_head=bool(sky_head))
    res.report["_body_pts"] = pts
    res.report["_debug"] = (surf_pts, surf_tris, gear, sky_body, sky_head_full, sf_head_full)
    return shapes, binds, res.report


def skin_morph(body_morph, used) -> tuple:
    """The skin piece's slider deltas: the body's own, vertex for vertex."""
    d = {k: {j: body_morph.deltas[k][i] for j, i in enumerate(used) if i in body_morph.deltas[k]}
         for k in body_morph.keys}
    e = {k: {j: body_morph.extra[k][i] for j, i in enumerate(used) if i in body_morph.extra[k]}
         for k in body_morph.keys}
    return d, e


MORPH_MAX = 0.15     # metres: a slider delta longer than this is cut to it (and counted in the report)


def morph_stats(d: dict) -> dict:
    """{key: {"vertices", "max_mm", "over_cap"}} of {key: {vertex: delta}}."""
    out = {}
    for k, v in d.items():
        a = np.array(list(v.values()), float).reshape(-1, 3)
        n = np.linalg.norm(a, axis=1) if len(a) else np.zeros(0)
        out[k] = {"vertices": int(len(a)), "max_mm": round(float(n.max()) * 1000, 1) if len(n) else 0.0,
                  "not_finite": int((~np.isfinite(a)).any(1).sum()), "over_cap": int((n > MORPH_MAX).sum())}
    return out


def capped(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        out[k] = {}
        for i, x in v.items():
            a = np.nan_to_num(np.asarray(x, float))
            ln = float(np.linalg.norm(a))
            out[k][i] = tuple(float(y) for y in (a * (MORPH_MAX / ln) if ln > MORPH_MAX else a))
    return out


def morph_files(shapes, nif_rel: str, body_pts, body_morph, doubled=(), skin_used=None, stats=None) -> dict:
    """{path: morph.dat bytes} per shape: its vertices move with the nearest body vertices under the sliders. A shape
    written with back faces has its vertices twice (copies after the originals): the copies get the same deltas.
    Deltas over MORPH_MAX are cut to it; stats (a dict) gets morph_stats per shape, before the cut."""
    out = {}
    for sh in shapes:
        name = sh.name.decode("latin-1")
        n = len(sh.positions)
        if sh.name == SKIN_SHAPE and skin_used is not None:
            d, extra = skin_morph(body_morph, skin_used)
        else:
            d, extra = gearfit.morph_deltas(np.asarray(sh.positions), body_pts, body_morph)
        if stats is not None:
            stats[name] = morph_stats(d)
        d = capped(d)
        total = n
        if name in doubled:
            d = {k: {**v, **{i + n: x for i, x in v.items()}} for k, v in d.items()}
            extra = {k: {**v, **{i + n: x for i, x in v.items()}} for k, v in extra.items()}
            total = 2 * n
        out[gearfit.morph_path(nif_rel, name)] = sfmorph.build(total, list(body_morph.keys), d, extra)
    return out


# Skyrim biped slot -> Starfield addon slots (2026-11-07: by position, Hadvar's boots, his only piece, took the
# body's slots 3 + 5 and hid the naked body with nothing over it)
SKY_TO_SF_SLOTS = {32: [3, 5], 37: [7], 33: [8], 34: [8]}
SPARE_SLOTS = (9, 10, 11, 12)


def slots_by_shape(gear_bytes, meshes) -> dict:
    """{shape name: Starfield slots} from each Skyrim armor's biped slots (its body slot first: 32 body, 37 feet,
    33 hands, 34 forearms); pieces with none of those get spare slots in turn."""
    out, spare = {}, list(SPARE_SLOTS)
    for gb, m in zip(gear_bytes, meshes):
        sky = list(m.get("slots") or [])
        sf = next((SKY_TO_SF_SLOTS[x] for x in (32, 37, 33, 34) if x in sky), None)
        if sf is None:
            sf = [spare.pop(0)] if spare else [SPARE_SLOTS[-1]]
        for sh in sky_shapes(gb):
            out.setdefault(sh.name.decode("latin-1"), sf)
    return out


def zero_morph(data: bytes) -> bytes:
    """The same morph.dat layout (vertices, keys, which vertex has a record for which key) with every delta and
    normal / tangent word 0."""
    m = sfmorph.parse(data)
    return sfmorph.build(m.num_vertices, m.keys, {k: {v: (0.0, 0.0, 0.0) for v in d} for k, d in m.deltas.items()})


def test_morph_files(tests, morphs: dict, body_path: str, sf_data: str) -> dict:
    """morph.dat files for os_export.morph_tests' armors: zeroed copies of our pieces' files, and a parse-and-rebuild
    copy of the body's (printing whether it comes out byte for byte the same as the game's)."""
    out = {}
    for t in tests:
        for r in t["parts"]:
            dst = r["morph_folder"].replace("\\", "/").lower() + "/morph.dat"
            if t["tag"] == "Zero":
                src = dst.replace(os_export.ZERO_SUFFIX.lower() + "/morph.dat", "/morph.dat")
                if src in morphs:
                    out[dst] = zero_morph(morphs[src])
            elif t["tag"] == "BodyOurs":
                raw = hkx_to_af.vanilla_file(body_path, sf_data)[0]
                m = sfmorph.parse(raw)
                ours = sfmorph.build(m.num_vertices, m.keys, m.deltas, m.extra, m.version)
                same = ours == raw
                diff = next((i for i in range(min(len(ours), len(raw))) if ours[i] != raw[i]), None)
                print(f"  body morph rebuilt by our writer: {'byte for byte the same' if same else 'DIFFERENT'} "
                      f"({len(raw)} bytes game, {len(ours)} ours"
                      f"{'' if same else f', first difference at byte {diff}'}; layout {m.layout})")
                out[dst] = ours
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--npc", required=True, help="Skyrim NPC EditorID (its default outfit is converted)")
    ap.add_argument("--name", required=True, help="file / record name, e.g. Ralof_outfit")
    ap.add_argument("--full", default=None, help="the armor's in-game name")
    ap.add_argument("--out", required=True, help="the mod folder (outside the repository)")
    ap.add_argument("--skip", default="", help="comma-separated shape names to leave out")
    ap.add_argument("--keep-skin", action="store_true",
                    help="keep shapes textured with Skyrim's skin (dropped by default: Starfield's own skin shows)")
    ap.add_argument("--texconv", default="", help=f"texconv.exe (default: {TEXCONV_DEFAULT} if there)")
    ap.add_argument("--content-resources", default="",
                    help="ContentResources.zip (default: <Starfield>\\Tools\\ContentResources.zip)")
    ap.add_argument("--archive2", default="", help="Archive2.exe (default: <Starfield>\\Tools\\Archive2)")
    ap.add_argument("--no-textures", action="store_true", help="keep the borrowed nightwear material")
    ap.add_argument("--tessellate", type=int, default=TESSELLATE,
                    help=f"split low-poly shapes (under {TESSELLATE_BELOW} vertices) n x n before the fit; 1 = off")
    ap.add_argument("--size-feet", action="store_true",
                    help="scale the boots' foot section to Starfield's foot (off: it opened a seam at the ankle)")
    ap.add_argument("--no-skin-piece", action="store_true",
                    help="no own skin piece and the naked body left visible (the old behaviour)")
    ap.add_argument("--debug-dir", default="", help="also write the meshes as OBJ files (and a zip) into this folder")
    ap.add_argument("--back-faces", choices=("auto", "all", "none"), default="auto",
                    help="add back faces: to Skyrim's double-sided shapes (auto), to every shape, or none")
    ap.add_argument("--no-morphs", action="store_true", help="write no body-slider morph.dat files")
    ap.add_argument("--head-weights", action="store_true",
                    help="gear near the head takes the whole head's weights (turns with the head)")
    ap.add_argument("--morph-test", action="store_true",
                    help="also write [zero morph], [vanilla body] and [body our morph] test armors (slider spikes)")
    ap.add_argument("--test-variants", action="store_true",
                    help="also write a [no morph] and a [same slots] copy of the armor, to tell causes apart in game")
    ap.add_argument("--one-nif", action="store_true",
                    help="the old layout: all gear in one NIF and addon (its morph record is the nightwear's)")
    ap.add_argument("--gap", type=float, default=gearfit.GAP, help="metres outside the body (default %(default)s)")
    a = ap.parse_args(argv)
    if os.path.abspath(a.out).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    sf_data = os.path.join(a.starfield, "Data")
    esm = os.path.join(a.skyrim_data, "Skyrim.esm")
    o = os_convert.outfit_armor(esm, a.npc)
    female = o["npc"]["female"]
    meshes = os_convert.worn_meshes(skyrimarmor.read_armor(esm), o["armor"], o["race"], female)
    if not meshes:
        sys.exit(f"{a.npc}: no worn armor meshes in the default outfit")
    sky = bsa.SkyrimArchives(a.skyrim_data)

    def read(p):
        data = sky._read(bsa.norm(p))
        if data is None:
            sys.exit(f"not in Skyrim's archives: {p}")
        return data
    print(f"{a.npc} ({o['race']}, {'female' if female else 'male'}):",
          *[f"{m['armor']} {m['mesh']} (Skyrim slots {m.get('slots')})" for m in meshes], sep="\n  ")
    for x in o.get("skipped", []):
        print(f"  outfit item without wearable armor (skipped): {x}")
    body = [read(os_convert.SKYRIM_BODY[female])]
    for p in SKYRIM_LIMBS[female]:
        data = sky._read(bsa.norm(p))
        if data is None:
            print("not in Skyrim's archives (skipped):", p)
        else:
            body.append(data)
    gear_bytes = [read(m["mesh"]) for m in meshes]
    textures, double = {}, set()
    for gb in gear_bytes:
        textures.update(shape_textures(gb))
        double |= double_sided_shapes(gb)
    shapes, binds, rep = run(gear_bytes, body, sf_data,
                             female, [x.strip() for x in a.skip.split(",") if x.strip()], a.gap,
                             () if a.keep_skin else sorted(skin_shapes(textures)), a.size_feet, a.tessellate,
                             sky._read(bsa.norm(SKY_HEADS[female])),
                             () if a.no_skin_piece else sorted(body_skin_shapes(textures)), a.head_weights)
    os.makedirs(a.out, exist_ok=True)
    body_pts = rep.pop("_body_pts")
    dbg = rep.pop("_debug", None)
    skin_used = rep.pop("_skin_used", None)
    broken = {n: r for n, r in rep["shapes"].items() if r["not_finite"] or r["far_outside"]}
    if broken:
        with open(os.path.join(a.out, "gear_fit.json"), "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=1, default=str)
        for n, r in broken.items():
            print(f"  {n}: {r['not_finite']} vertices not finite, {r['far_outside']} far outside the body, "
                  f"box {r['box_m']}")
        print("nothing written: broken shapes (report in gear_fit.json)")
        return 1
    skin_sh = next((sh for sh in shapes if sh.name == SKIN_SHAPE), None)
    shapes = [sh for sh in shapes if sh.name != SKIN_SHAPE]
    names = [sh.name.decode("latin-1") for sh in shapes]
    mats, conv, staging = {}, None, None
    if not a.no_textures:
        texconv = find_texconv(a.texconv)
        cr = a.content_resources or os.path.join(a.starfield, "Tools", "ContentResources.zip")
        if not texconv:
            print("textures: SKIPPED, texconv.exe not found (pass --texconv)")
        elif not os.path.isfile(cr):
            print(f"textures: SKIPPED, ContentResources.zip not found: {cr} (pass --content-resources)")
        else:
            import shutil
            from fo4sf import skyrimconvert
            staging = os.path.join(a.out, "_staging")
            shutil.rmtree(staging, ignore_errors=True)
            conv = skyrimconvert.SkyrimConverter(sky, staging, texconv, cr, collision_template=None, prefix="s2s")
            for gb in gear_bytes:
                mats.update(shape_materials(conv, gb))
    doubled = set(names) if a.back_faces == "all" else (double & set(names) if a.back_faces == "auto" else set())
    sp = rep.get("skin_piece")
    if sp:
        mats[SKIN_SHAPE.decode()] = sp["material"]
    slots = None if (a.no_skin_piece or not sp) else HIDE_BODY_SLOTS
    if a.one_nif:
        files, _recs, prep, material, _model = os_export.write_armor(
            sf_data, a.out, a.name, a.full or a.name.replace("_", " "), shapes, binds,
            back_faces=[n in doubled for n in names], materials=[mats.get(n) for n in names], slots=slots,
            skin_shape=skin_sh if slots else None, skin_material=(sp or {}).get("material"))
        nifs = {n: f"S2S\\{a.name}.nif" for n in names}
        if skin_sh is not None and slots:
            nifs[SKIN_SHAPE.decode()] = f"S2S\\{a.name}_Skin.nif"
    else:
        piece_slots = slots_by_shape(gear_bytes, meshes)
        parts = [{"shape": sh, "material": mats.get(n), "back": n in doubled, "slots": piece_slots.get(n)}
                 for sh, n in zip(shapes, names)]
        if skin_sh is not None and slots:
            parts.append({"shape": skin_sh, "material": sp["material"], "skin": True})
        body_folder = ""
        if a.morph_test and not a.no_morphs:
            mp, _bm = find_body_morph(sf_data, len(body_pts), female)
            if mp:
                body_folder = "\\".join(w.capitalize() for w in mp.rsplit("/", 1)[0].split("/"))
        files, _recs, prep, material, nifs = os_export.write_armor_parts(
            sf_data, a.out, a.name, a.full or a.name.replace("_", " "), parts, binds, variants=a.test_variants,
            morph_test=body_folder)
        print(f"one addon + morph record per shape (template model {prep.get('template_vertices')} vertices):")
        for r in prep["parts"]:
            print(f"  {r['shape']}: ARMA {r['ARMA']} slots {r['slots']} -> {r['model']}; MRPH {r['MRPH']} "
                  f"MOBC {r.get('MOBC_template')} -> {r.get('MOBC')}")
        for t in prep.get("tests", []):
            print(f"test armor \"{t['name']}\": player.additem xx{int(t['ARMO'], 16) & 0xFFFFFF:06X} 1   "
                  f"(morph folders: {', '.join(r.get('morph_folder', '-') for r in t['parts'])})")
        for v in prep.get("variants", []):
            print(f"test armor \"{v['name']}\": player.additem xx{int(v['ARMO'], 16) & 0xFFFFFF:06X} 1")
    if sp:
        print(f"skin piece: {sp['vertices']} Starfield body vertices where {', '.join(sp['from'])} lies, "
              f"material {sp['material']}; armor slots {slots} (naked body hidden)")
    if conv is not None:
        import shutil
        import hair_pack
        base = os.path.splitext(os_export.PLUGIN)[0]
        packed = hair_pack.pack(staging, a.out, a.starfield, a.archive2 or None, f"{base} - Main.ba2",
                                f"{base} - Textures.ba2")
        shutil.rmtree(staging, ignore_errors=True)
        rep["materials"] = {"by_shape": {n: mats.get(n) for n in names}, "packed": packed,
                            "errors": conv.material_errors}
        for n in names:
            print(f"material {n}: {mats.get(n) or 'FALLBACK (nightwear)'}")
        print("texture files:", packed)
        for k, e in conv.material_errors.items():
            print(f"  material error {k}: {e}")
    print("double-sided in Skyrim:", ", ".join(sorted(double)) or "none",
          "| written with back faces:", ", ".join(sorted(doubled)) or "none")
    morphs = {}
    if not a.no_morphs:
        mpath, body_morph = find_body_morph(sf_data, len(body_pts), female)
        if body_morph is None:
            print("no body morph.dat with the body's vertex count found: no slider morphs written")
        else:
            worn = shapes + ([skin_sh] if skin_sh is not None and slots else [])
            mstats = {}
            for sh in worn:
                morphs.update(morph_files([sh], nifs[sh.name.decode("latin-1")], body_pts, body_morph, doubled,
                                          skin_used, mstats))
            rep["morph_stats"] = mstats
            for n_, st in mstats.items():
                print(f"  morph {n_}: " + ", ".join(f"{k} {v['vertices']} v max {v['max_mm']} mm"
                                                    + (f" ({v['over_cap']} over cap)" if v['over_cap'] else "")
                                                    + (f" ({v['not_finite']} NOT FINITE)" if v['not_finite'] else "")
                                                    for k, v in st.items()))
            tpl_morph = next((r.get("template_morph_folder") for r in prep.get("parts", [])
                              if r.get("template_morph_folder")), None)
            if tpl_morph:
                try:
                    tm = sfmorph.parse(hkx_to_af.vanilla_file(tpl_morph.replace("\\", "/").lower() + "/morph.dat",
                                                              sf_data)[0])
                    rep["template_morph"] = {"folder": tpl_morph, "keys": tm.keys, **tm.layout}
                    print(f"  template morph {tpl_morph}: keys {tm.keys}, {tm.num_vertices} v, empty entries "
                          f"first 0: {tm.layout['empty_entries_first_0']}, running: "
                          f"{tm.layout['empty_entries_first_running']}")
                except (SystemExit, Exception) as e:          # report only
                    print(f"  template morph {tpl_morph}: not read ({e})")
            if prep.get("tests"):
                morphs.update(test_morph_files(prep["tests"], morphs, mpath, sf_data))
            for rel, data in morphs.items():
                dst = os.path.join(a.out, *rel.split("/"))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as fh:
                    fh.write(data)
            rep["body_morph"] = mpath
            print(f"slider morphs from {mpath} ({', '.join(body_morph.keys)}): {len(morphs)} files")
    rep["textures"] = textures
    for n, t in textures.items():
        print(f"textures {n}: {t[0] if t else '-'}")
    if a.debug_dir and dbg is not None:
        frame = np.array(rep["frame"], float)
        print("debug meshes:", debug_meshes(a.debug_dir, shapes, frame, *dbg))
    rep.update(npc=a.npc, meshes=meshes, records=prep, material=material, files=sorted(files) + sorted(morphs))
    with open(os.path.join(a.out, "gear_fit.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1, default=str)
    if rep.get("neck_squash"):
        print(f"neck: gear around it squashed in height to {rep['neck_squash']['ratio']} above the clavicles "
              f"({rep['neck_squash']['clavicle_height_m']} m)")
    for b in ("NPC Neck [Neck]", "NPC Head [Head]"):
        info = rep.get("bones", {}).get(b, {})
        if info:
            print(f"{b}: height {info.get('height_mm')} mm, neck height ratio {info.get('neck_height_ratio', '-')}")
    if rep.get("shoulder_drop_mm"):
        d = rep["shoulder_drop_mm"]
        n = len(d)
        print(f"shoulders: Starfield's vs the fitted Skyrim body round the neck (mm): front {d[0]}, left {d[n // 4]}, "
              f"back {d[n // 2]}, right {d[3 * n // 4]}; gear near the neck moved by that")
    print(f"skeletons: joint rms {rep['joint_rms_m'] * 1000:.0f} mm after the overall fit, "
          f"scale {rep['global_scale']:.4f}")
    b = rep.get("body", {})
    print(f"body: {b.get('matched')} of {b.get('points')} Skyrim body points matched, "
          f"median gap {b.get('median_depth_mm') or 0:.1f} mm")
    for n, r in rep["shapes"].items():
        print(f"  {n}: {r['vertices']} v, {'skin piece, ' if r['skin_piece'] else ''}pushed out {r['pushed_out']}, "
              f"body shift up to {r['max_body_shift_mm']:.0f} mm, {len(r['bones'])} bones, "
              f"z {r['box_m'][0][2]:.2f}..{r['box_m'][1][2]:.2f} m, "
              f"{r['unweighted']} unweighted, {r.get('body_weighted', 0)} on body weights, "
              f"{r.get('pulled_in', 0)} pulled in to Skyrim's gap, {r.get('covered', 0)} moved to cover the body"
              + (f", {r['chin_lowered']} lowered under the chin (up to {r['chin_drop_mm']} mm)"
                 if r.get('chin_lowered') else "")
              + (f", {r['neck_wrapped']} wrapped round the neck (up to {r['neck_wrap_mm']} mm)"
                 if r.get('neck_wrapped') else "")
              + (f", {r['buried']} kept inside the neck as in Skyrim" if r.get('buried') else "")
              + (f", {r['skirt_vertices']} on skirt bones (hips + thighs)" if r.get('skirt_vertices') else "")
              + (f", {r['skirt_hung']} hung round the legs" if r.get('skirt_hung') else "")
              + (f", {r['draped']} laid on the shoulders as in Skyrim (up to {r['drape_mm']} mm)"
                 if r.get('draped') else ""))
        if r.get("top_bones") and not r.get("skin_piece"):
            print("     top tenth follows:", ", ".join(f"{b} {w:.2f}" for b, w in r["top_bones"].items()))
        for part, g in (r.get("gaps_mm") or {}).items():
            print(f"     gap to the body ({part}, {g['vertices']} v): Skyrim {g['skyrim']} mm, now {g['starfield']} mm")
    if rep.get("skipped"):
        print("left out:", ", ".join(rep["skipped"]))
    for n, (v0, v1) in (rep.get("tessellated") or {}).items():
        print(f"tessellated {n}: {v0} -> {v1} vertices")
    print("hands in the push-out surface:", rep.get("hands") or "NOT FOUND")
    print("head in the surface:", rep.get("head"), "| Skyrim head:", "yes" if rep.get("skyrim_head") else "NOT FOUND")
    if rep.get("dropped_skin_pieces"):
        print("bare-skin shapes left out (Skyrim skin textures):", ", ".join(rep["dropped_skin_pieces"]))
    feet = rep.get("feet") or {}
    for side, f in feet.items():
        print(f"foot {side}: boot foot scaled {f['scale']} to Starfield's foot")
    if not feet and a.size_feet:
        print("foot sizing: SKIPPED (no Skyrim or Starfield foot region found)")
    print(f"{os_export.PLUGIN}: ARMO {prep['ARMO']} (S2S_{a.name}); material {material}")
    print(f"in game: player.additem xx{int(prep['ARMO'], 16) & 0xFFFFFF:06X} 1   (xx: S2SArmorTest.esm's load order "
          f"index; or find them all with: help \"S2S_{a.name}\" 4)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
