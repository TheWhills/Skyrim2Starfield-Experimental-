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
    return [tuple(map(float, x)) for x in uv], mat, m


HIDE_BODY_SLOTS = [3, 5, 7]   # as vanilla outfits: 3 hides the naked body (nightwear upper body 3 + 5, lower 7)
SKIN_REACH = 0.03       # m: Starfield body vertices this close to a fitted Skyrim bare-skin piece show as skin
SKIN_SHAPE = b"S2S_Skin"


COVER_DEPTH = 0.06      # m: a body point with gear this close straight out from it counts as covered
SKIN_UNDER_DEPTH = 0.012   # m: for the whole-body skin piece: skin is dropped only under gear this tight; under
#                            looser gear it is kept (2026-11-07, Ralof from behind: the arm stopped short of the
#                            looser back of the sleeve and the gap showed; with 3.5 cm)
FEET_BONES = ("Foot", "Toe", "Ankle")    # Starfield bone name parts: the feet Skyrim shows under a robe
UNDER_SKIN = 0.015      # m: gear this close under the skin also hides it
COVER_MARGIN_M = 0.05   # m: and at most this far from the visible skin (2 cm left a bare gap under Ralof's sleeve
#                         hems; the shoulder diamonds that 2 cm was for were dips, fixed by push_faces_out)
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
        along = np.einsum("ij,ij->i", dirn, body_nrm[cand])
        # also gear just under the skin (2026-11-07, Farengar: the neckline is brought down into the body on
        # purpose; the whole-body skin piece then showed over the beige trim)
        hit = ((dist < depth) & (along > 0.5)) | ((dist < UNDER_SKIN) & (along < -0.5))
        out[cand[hit]] = True
    return out


def skin_piece(body_skel: np.ndarray, body_tris, body_uvs, body_w, sources: np.ndarray, reach: float = SKIN_REACH,
               gear=(), margin: int = COVER_MARGIN, whole: bool = False, depth: float = COVER_DEPTH, extra=None):
    """(HairShape in skeleton space, kept body vertex indices) of the Starfield body where Skyrim's bare-skin pieces
    lie after the fit (2026-11-06, owner: Skyrim's bare arm runs up under the sleeve, Starfield's skin starts lower):
    the body vertices within `reach` of them and the triangles among them, plus `extra` (the feet when the Skyrim
    armour does not cover them: Skyrim shows its own naked feet there). None when nothing is kept. whole: the
    whole body instead (2026-11-07, owner: the body armour hides the naked body, so everything it does not cover must
    come with it: feet without boots, and Hadvar's thighs under the skirt showed holes); gear: the pieces whose
    cover removes skin (the body armour's own, not boots or gauntlets, which may be taken off)."""
    from fo4sf import skyrimhair
    extra = np.zeros(len(body_skel), bool) if extra is None else np.asarray(extra, bool)
    if not len(sources) and not extra.any() and not whole:
        return None, []
    if len(sources):
        zero = np.tile([0.0, 0.0, 1.0], (len(sources), 1))
        _d, dist, _i = skyrimhair.nearest_surface(body_skel, sources, zero)
    else:
        dist = np.full(len(body_skel), np.inf)
    keep = np.ones(len(body_skel), bool) if whole else (dist < reach) | extra
    t = np.asarray(body_tris, int).reshape(-1, 3)
    if len(gear):
        # only the skin that shows, plus a narrow overlap under the gear's edges (2026-11-06: under the cowl the skin
        # piece grew past the cowl on heavier bodies and showed through on the chest)
        bn = skyrimhair._vertex_face_normals(body_skel, t)
        bn /= np.maximum(np.linalg.norm(bn, axis=1, keepdims=True), 1e-12)
        cov = covered_by(body_skel, bn, gear, depth) & keep
        visible = keep & ~cov
        grow = visible.copy()
        ring1 = None
        for _ in range(margin):
            touch = np.zeros(len(body_skel), bool)
            on = grow[t].any(1)
            touch[t[on].reshape(-1)] = True
            grow |= touch & keep
            if ring1 is None:
                ring1 = grow.copy()          # always one ring: the edge triangles stay whole
        if visible.any():
            # the overlap also limited by distance (2026-11-07, Farengar: on the large triangles of the shoulders,
            # five rings of overlap from the neck reached the shoulder tops, which then showed through the robe)
            vis_p = body_skel[visible]
            near = np.zeros(len(body_skel), bool)
            cand = np.nonzero(grow & ~visible)[0]
            for c0 in range(0, len(cand), 512):
                q = body_skel[cand[c0:c0 + 512]]
                d2 = ((q[:, None, :] - vis_p[None, :, :]) ** 2).sum(-1).min(1)
                near[cand[c0:c0 + 512]] = d2 < COVER_MARGIN_M ** 2
            grow = visible | near | (ring1 if ring1 is not None else visible)
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


FLAP_ABOVE_NECK = 0.05   # m: head-mesh vertices below the neck joint + this join the surface (the chest / back flap)


def is_underwear(name) -> bool:
    """A Skyrim body NIF's underwear shape (MaleUnderwear_1, FemaleUnderwear), not the body (FemaleUnderwearBody)."""
    n = (name.decode("latin-1", "replace") if isinstance(name, bytes) else str(name)).lower()
    return "underwear" in n and "body" not in n


def neck_part(points, tris, weights, neck_bones, share: float = NECK_SHARE, low_z=None):
    """The neck of a head mesh: vertices with >= share of their weight on neck / chest bones, and the triangles
    among them (2026-11-06: with the whole head in the surface, the cover step pushed Ralof's cowl out over the chin and
    jaw). weights: per vertex [(bone name, w)]. Returns (points, triangles, weights, kept vertex count)."""
    keep = np.array([sum(w for b, w in vw if b in neck_bones) >= share for vw in weights], bool)
    if low_z is not None:
        # also the head mesh's flap over the upper chest and back (2026-11-07, Saadia / Ysolda: Starfield's female
        # head reaches down over them; straps fitted to the body only went under it)
        keep |= np.asarray(points, float)[:, 2] < low_z
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


def merged_morph(body, head, n_body: int):
    """One Morph over body vertices then head vertices (index + n_body), with the body's keys."""
    keys = list(body.keys)
    d = {k: dict(body.deltas.get(k, {})) for k in keys}
    e = {k: dict(body.extra.get(k, {})) for k in keys}
    for k in keys:
        for v, x in head.deltas.get(k, {}).items():
            d[k][v + n_body] = x
        for v, x in head.extra.get(k, {}).items():
            e[k][v + n_body] = x
    return sfmorph.Morph(body.version, n_body + head.num_vertices, keys, d, e)


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


CURVE = 0.6           # Phong-tessellation share for --curved (0: flat)
CURVE_CAP = 0.12      # its bulge at most this share of the triangle's longest edge


def flat_subdivide(points, normals, uvs, tris, weights, n: int, curve: float = 0.0):
    """Every triangle split n x n on its own flat plane (no curved patch: on Ralof's cowl the PN patches ballooned
    the folds and opened the chest, 2026-11-06). Points on shared edges are shared (same position and UV); UVs,
    normals and weights {bone index: w} interpolated. Returns (points, normals, uvs, tris, weights)."""
    P, N, U = np.asarray(points, float), np.asarray(normals, float), np.asarray(uvs, float)
    W = [dict(vw) for vw in weights]
    pos, nrm, uv, wts, index = [], [], [], [], {}
    if curve > 0:
        # curved (2026-11-08, owner: Saadia's bust "jagged and not rounded": flat splits keep Skyrim's low-poly
        # outline): Phong tessellation on normals averaged over vertices at one position (no cracks at UV seams),
        # the bulge capped so folds do not balloon as PN patches did on Ralof's cowl
        key_ = np.round(P, 5)
        _u, inv_ = np.unique(key_, axis=0, return_inverse=True)
        inv_ = inv_.reshape(-1)
        acc = np.zeros((len(_u), 3))
        np.add.at(acc, inv_, N)
        Ns = acc[inv_] / np.maximum(np.linalg.norm(acc[inv_], axis=1, keepdims=True), 1e-12)

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
        if curve > 0 and len(corners) > 1:
            proj = sum(w * (p_ - np.dot(p_ - P[x], Ns[x]) * Ns[x]) for x, w in ((a, ba), (b, bb), (c, bc)))
            d_ = (proj - p_) * curve
            cap = CURVE_CAP * max(np.linalg.norm(P[a] - P[b]), np.linalg.norm(P[b] - P[c]),
                                  np.linalg.norm(P[c] - P[a]))
            m_ = np.linalg.norm(d_)
            p_ = p_ + (d_ * (cap / m_) if m_ > cap else d_)
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


def tessellate_shapes(gear, n: int = TESSELLATE, below: int = TESSELLATE_BELOW, skip=(), curve: float = 0.0):
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
        p, nr, uv, tr, w = flat_subdivide(s.points, s.normals, s.uvs, s.triangles, s.weights, n, curve)
        out.append(gearfit.SkyShape(s.name, p, nr, uv, tr, list(s.bones), w, s.joints))
        rep[name] = [len(s.points), len(p)]
    return out, rep


def write_obj(path: str, pts, tris, uvs=None) -> None:
    """OBJ with optional per-vertex UVs (vt, v flipped to OBJ's bottom-up convention)."""
    pts = np.asarray(pts, float)
    uv = None if uvs is None or len(uvs) != len(pts) else np.asarray(uvs, float).reshape(-1, 2)
    with open(path, "w", encoding="utf-8") as fh:
        for p in pts:
            fh.write(f"v {p[0]:.5f} {p[1]:.5f} {p[2]:.5f}\n")
        if uv is not None:
            for u, v in uv:
                fh.write(f"vt {u:.5f} {1.0 - v:.5f}\n")
        for t in np.asarray(tris, int).reshape(-1, 3):
            a, b, c = (int(x) + 1 for x in t)
            fh.write(f"f {a}/{a} {b}/{b} {c}/{c}\n" if uv is not None else f"f {a} {b} {c}\n")


def safe_name(n: str) -> str:
    """A file name part without characters Windows refuses (':' in 'MaleUnderwearBody:0' wrote an empty file)."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in n)


def debug_textures(folder: str, textures: dict, read, texconv: str) -> list:
    """Each gear shape's diffuse texture as tex_<shape>.png in folder (via texconv), for textured looks at the fit
    from outside the game (2026-11-07, owner: stretch shows in the texture, e.g. Farengar's beige collar trim).
    Returns the file names written."""
    import subprocess
    import tempfile
    out = []
    if not texconv:
        return out
    with tempfile.TemporaryDirectory() as tmp:
        for n, t in textures.items():
            if not t:
                continue
            data = read(t[0])
            if not data:
                continue
            src = os.path.join(tmp, "tex_" + safe_name(n) + ".dds")
            with open(src, "wb") as fh:
                fh.write(data)
            r = subprocess.run([texconv, "-nologo", "-y", "-ft", "png", "-f", "R8G8B8A8_UNORM", "-o", folder, src],
                               capture_output=True, text=True)
            png = "tex_" + safe_name(n) + ".png"
            if r.returncode == 0 and os.path.isfile(os.path.join(folder, png)):
                out.append(png)
    return out


def armor_by_edid(inv: dict, edids) -> tuple:
    """([ARMO FormIDs], [not found]) of Skyrim armor records by EditorID (case-insensitive)."""
    by = {a["edid"].lower(): fid for fid, a in inv["armo"].items() if a.get("edid")}
    found = [by[e.lower()] for e in edids if e.lower() in by]
    missing = [f"{e}: no ARMO with this EditorID" for e in edids if e.lower() not in by]
    if missing and not found:
        sys.exit("; ".join(missing))
    return found, missing


def shifted(points, deltas: dict) -> np.ndarray:
    """Points moved by a {vertex: (dx, dy, dz)} morph."""
    p = np.asarray(points, float).copy()
    for i, x in deltas.items():
        if i < len(p):
            p[i] += x
    return p


def debug_meshes(folder: str, shapes, frame, surf_pts, surf_tris, sky_gear, sky_body, sky_head=None,
                 sf_head=None, extra=()) -> str:
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
        write_obj(os.path.join(folder, n), p, sh.triangles, sh.uvs)
        names.append(n)
    for tag, group in (("sky_", sky_gear), ("skybody_", sky_body)):
        for s in group:
            n = tag + safe_name(s.name.decode("latin-1", "replace")) + ".obj"
            write_obj(os.path.join(folder, n), s.points, s.triangles, s.uvs)
            names.append(n)
    names += [n for n in extra if os.path.isfile(os.path.join(folder, n))]
    z = os.path.join(folder, "fit_debug.zip")
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for n in names:
            zf.write(os.path.join(folder, n), n)
    return z


def run(gear_nifs, body_nif, sf_data: str, female: bool, skip=(), gap: float = gearfit.GAP, skin_names=(),
        size_feet: bool = False, tessellate: int = TESSELLATE, sky_head: bytes = None, body_skin_names=(),
        head_weights: bool = False, body_piece_names=None, feet_skin: bool = False, whole_skin: bool = False,
        round_bust: bool = False, strap_gap: float = gearfit.STRAP_GAP, curved: bool = False,
        conform: bool = False):
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
        if len(h_w) == len(h_pts):
            # weights also from the whole head: the collar's top takes the head's own neck-skin weights (2026-11-06:
            # with only the neck-weighted part, the collar had no C_Head and stayed facing forward when the head turned)
            weight_src = (np.concatenate([surf_pts, h_pts]), np.concatenate([surf_tris, h_tris + len(surf_pts)]),
                          list(surf_w) + list(h_w))
        low_z = (world["C_Neck"][2, 3] + FLAP_ABOVE_NECK) if "C_Neck" in world else None
        h_pts, h_tris, h_w, h_n = neck_part(h_pts, h_tris, h_w, NECK_BONES_SF, low_z=low_z)
        head_path += f" (neck: {h_n} vertices)"
        surf_tris = np.concatenate([surf_tris, h_tris + len(surf_pts)])
        surf_pts = np.concatenate([surf_pts, h_pts])
        surf_w += h_w
    except (SystemExit, Exception) as e:            # report, keep going without the head
        head_path = f"NOT FOUND ({e})"
    gear = [s for nb in gear_nifs for s in sky_shapes(nb)]
    skipped = [s.name.decode("latin-1") for s in gear if s.name.decode("latin-1").lower() in {x.lower() for x in skip}]
    gear = [s for s in gear if s.name.decode("latin-1") not in skipped]
    gear, tess = tessellate_shapes(gear, tessellate, skip=set(skin_names), curve=CURVE if curved else 0.0)
    body_nifs = body_nif if isinstance(body_nif, (list, tuple)) else [body_nif]
    # not the underwear shapes (2026-11-07, verified on Ysolda's / Saadia's debug meshes: the dresses' chest panels,
    # 3-31 mm inside Skyrim's breasts, read as outside the separate bra shape, so they were not kept hidden and showed
    # as brown patches; Starfield's body has no underwear in the surface either)
    sky_body = [s for nb in body_nifs for s in sky_shapes(nb) if not is_underwear(s.name)]
    sky_head_full = None
    if sky_head:
        sky_body += skyrim_head_shapes(sky_head)
        sky_head_full = skyrim_head_mesh(sky_head)
    if weight_src is not None and len(weight_src[2]) != len(weight_src[0]):
        weight_src = None
    sky_only = [sh for sh in sky_body if sh.name.decode("latin-1", "replace") not in
                {h.name.decode("latin-1", "replace") for h in (skyrim_head_shapes(sky_head) if sky_head else [])}]
    sky_join, sky_tj, base = [], [], 0
    for sh in sky_only:
        sky_join.append(np.asarray(sh.points, float))
        sky_tj.append(np.asarray(sh.triangles, int).reshape(-1, 3) + base)
        base += len(sh.points)
    c_sky = gearfit.neck_rim_centre(np.concatenate(sky_join), np.concatenate(sky_tj)) if sky_join else None
    c_sf = gearfit.neck_rim_centre(skel_pts, tris)
    collar_anchor = (c_sky, c_sf) if c_sky is not None and c_sf is not None else None
    res = gearfit.fit(gear, sky_body, world, surf_pts, surf_tris, gap, sf_body_weights=surf_w, size_feet=size_feet,
                      collar_anchor=collar_anchor, head_weights_all=head_weights, round_bust=round_bust,
                      strap_gap=strap_gap, conform=conform,
                      weight_src=weight_src,
                      heads=(sky_head_full, sf_head_full) if sky_head_full and sf_head_full else None)
    skin = None
    if body_skin_names or feet_skin:          # our own skin piece where Skyrim's body-skin pieces lie
        src = [np.asarray(sh.positions) for sh in res.shapes if sh.name.decode("latin-1", "replace")
               in set(body_skin_names)]
        if src or feet_skin:
            src = src or [np.zeros((0, 3))]
            feet = np.array([sum(x for b, x in vw if any(k in b for k in FEET_BONES)) >= 0.5 for vw in body_w], bool) \
                if feet_skin else None
            uvs, mat, body_mesh = starfield_body_skin(sf_data, female)
            skel_body = pts @ frame[:3, :3].T + frame[:3, 3]
            gear_fit_shapes = [sh for sh in res.shapes if sh.name.decode("latin-1", "replace") not in set(skin_names)
                               and (body_piece_names is None or sh.name.decode("latin-1", "replace")
                                    in set(body_piece_names))]
            skin, used = skin_piece(skel_body, tris, uvs, body_w, np.concatenate(src), gear=gear_fit_shapes,
                                    whole=whole_skin, depth=SKIN_UNDER_DEPTH, extra=feet)
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
        if sh.name == SKIN_SHAPE and skin is not None and res.report.get("_skin_used") is not None:
            # the skin piece is the vanilla body itself: its own packed positions, normals and tangents, bit for bit
            # (2026-11-07, Ysolda / Saadia: low necklines showed a thin seam where Starfield's head mesh ends on the
            # chest and back; our re-encoded positions and recomputed normals did not match the body's under it)
            used = res.report["_skin_used"]
            sh.raw = (body_mesh.scale, [body_mesh.positions[k] for k in used],
                      [body_mesh.normals[k] for k in used] if body_mesh.normals else None,
                      [body_mesh.tangents[k] for k in used] if body_mesh.tangents else None)
        shapes[i] = sh
    bones = sorted({b for sh in shapes for vw in sh.weights for b, _w in vw} | {"C_Chest"})
    binds = gearfit.skeleton_binds(bones, world, frame, shapes)
    res.report.update(skipped=skipped, frame=frame.round(6).tolist(), hands=hand_path, tessellated=tess,
                      head=head_path, skyrim_head=bool(sky_head))
    res.report["_body_pts"] = pts
    res.report["_body_tris"] = tris
    if sf_head_full is not None:
        res.report["_head_tris"] = np.asarray(sf_head_full[1], int).reshape(-1, 3)
    res.report["_body_binds"] = body_binds
    if sf_head_full is not None:      # the head too: collar parts next to it do not shrink under Thin
        res.report["_head_pts"] = (np.asarray(sf_head_full[0]) - frame[:3, 3]) @ np.linalg.inv(frame[:3, :3]).T
    if hand_pts is not None:          # the hands in the body mesh's space, for the morphs
        res.report["_hand_pts"] = (np.asarray(hand_pts) - frame[:3, 3]) @ np.linalg.inv(frame[:3, :3]).T
    res.report["collar_anchor_m"] = None if collar_anchor is None else [np.round(c, 3).tolist() for c in collar_anchor]
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


HAND_KEEP = (0.03, 0.08)   # m from the hands mesh: no body-slider move inside the first, full by the second


def near_hands_factor(points: np.ndarray, hand_pts) -> np.ndarray:
    """Per point 0..1: how much of the body-slider move to keep near the hands (2026-11-07, owner: on the thinnest
    body the robe's cuffs shrank with the forearm onto the hands, which do not shrink, and the hands came through)."""
    if hand_pts is None or not len(hand_pts):
        return np.ones(len(points))
    h = np.asarray(hand_pts, float)
    out = np.empty(len(points))
    for c0 in range(0, len(points), 512):
        q = np.asarray(points[c0:c0 + 512], float)
        d = np.sqrt(((q[:, None, :] - h[None, :, :]) ** 2).sum(-1).min(1))
        out[c0:c0 + 512] = np.clip((d - HAND_KEEP[0]) / (HAND_KEEP[1] - HAND_KEEP[0]), 0.0, 1.0)
    return out


SLIDER_GAP = 0.002     # m: gear visible at default stays this far outside the body / head at each slider's extreme


def slider_clearance(points, tris, deltas: dict, body_pts, body_tris, body_morph, gap: float = SLIDER_GAP):
    """deltas ({key: {vertex: delta}}) raised where, with one slider at its extreme, gear that is outside the body
    and head at default would sink in (2026-11-07, owner: Saadia's straps clipped on heavy and thin bodies, fine at
    default). Per key: body + its deltas, gear + its deltas; a vertex under gap gets the shortfall along the morphed
    surface's normal added to its delta. Returns (deltas, {key: (vertices raised, largest raise m)})."""
    from fo4sf import gearfit
    p0 = np.asarray(points, float)
    bp = np.asarray(body_pts, float)
    bt = np.asarray(body_tris, int).reshape(-1, 3)
    _c, d0, dist0 = gearfit.closest_on_mesh(p0, *gearfit.with_normals(bp, bt))
    outside = (d0 > 0.0005) & (dist0 < 0.15)
    out, rep = {}, {}
    for key, dv in deltas.items():
        bd = np.zeros_like(bp)
        for v, x in body_morph.deltas.get(key, {}).items():
            if v < len(bp):
                bd[v] = x
        gd = np.zeros_like(p0)
        for v, x in dv.items():
            gd[v] = x
        mb = gearfit.with_normals(bp + bd, bt)
        _c, dk, distk, nk = gearfit.closest_on_mesh(p0 + gd, *mb, with_normals=True)
        need = np.where(outside & (dk < gap) & (distk < 0.15), gap - dk, 0.0)
        fix = nk * need[:, None]
        if tris is not None and len(tris) and (need > 0).any():
            st, canon = gearfit.seam_tris(p0, tris)
            soft = gearfit.with_seams(gearfit.smooth_moves(np.zeros_like(fix), gearfit.with_seams(fix, canon), st,
                                                           rounds=2), canon)
            fix = np.where((np.linalg.norm(fix, axis=1) > np.linalg.norm(soft, axis=1))[:, None], fix, soft)
        gd = gd + fix
        out[key] = {int(v): tuple(map(float, gd[v])) for v in np.nonzero(np.abs(gd).max(1) > 1e-5)[0]}
        rep[key] = (int((need > 0).sum()), float(np.linalg.norm(fix, axis=1).max()) if len(fix) else 0.0)
    return out, rep


def morph_files(shapes, nif_rel: str, body_pts, body_morph, doubled=(), skin_used=None, stats=None,
                hand_pts=None, head_pts=None, body_tris=None) -> dict:
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
            f = near_hands_factor(np.asarray(sh.positions), hand_pts)
            if (f < 1).any():
                d = {k: {i: tuple(np.asarray(x) * f[i]) for i, x in v.items()} for k, v in d.items()}
            fh = near_hands_factor(np.asarray(sh.positions), head_pts)
            if (fh < 1).any() and "Thin" in d:
                # next to the head (neck) no Thin shrink (2026-11-07, owner: on the thinnest body Farengar's neck
                # skin came through the collar trim; the head mesh's neck does not shrink with the body's Thin)
                d["Thin"] = {i: tuple(np.asarray(x) * fh[i]) for i, x in d["Thin"].items()}
        if body_tris is not None and sh.name != SKIN_SHAPE:
            d, raised = slider_clearance(np.asarray(sh.positions), sh.triangles, d, body_pts, body_tris, body_morph)
            for k, v in d.items():                     # packed words for vertices newly given a delta
                for i in v:
                    extra.setdefault(k, {}).setdefault(i, (0, 0, 0))
            if stats is not None:
                stats[name + " slider clearance"] = {k: {"vertices": n, "max_mm": round(m * 1000, 1), "not_finite": 0,
                                                         "over_cap": 0} for k, (n, m) in raised.items()}
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
    ap.add_argument("--npc", required=True, help="Skyrim NPC EditorID (its default outfit is converted; with --armor "
                                                 "only its race and sex are used)")
    ap.add_argument("--armor", action="append", default=[],
                    help="Skyrim armor EditorID to convert instead of the NPC's outfit (repeatable), e.g. "
                         "ArmorIronCuirass")
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
    ap.add_argument("--add", action="store_true",
                    help="keep the other outfits already in S2SArmorTest.esm (and their textures); this --name's "
                         "own records are replaced")
    ap.add_argument("--whole-skin", action="store_true",
                    help="skin piece = the whole body minus what the armour covers (default: Skyrim's own bare-skin "
                         "parts, plus the feet when the armour does not cover them, as Skyrim shows them)")
    ap.add_argument("--strap-gap", type=float, default=None,
                    help=f"metres off the skin for visible gear round the neck and shoulders (default: "
                         f"{gearfit.STRAP_GAP} on female outfits, off on male ones; 0 = the normal --gap)")
    ap.add_argument("--debug-steps", action="store_true",
                    help="with --debug-dir: also the gear after each group of fit steps (fit_<shape>@step<n>.obj)")
    ap.add_argument("--conform", action="store_true",
                    help="new fit: bend the whole outfit by a smooth field of the body's change, then push it out of "
                         "the body smoothly (keeps Skyrim's folds and edges); the collar steps and the rest stay")
    ap.add_argument("--curved", action="store_true",
                    help="split low-poly gear into a rounded surface (Phong tessellation) instead of flat triangles")
    ap.add_argument("--round-bust", action="store_true",
                    help="the front of the chest keeps Skyrim's rounder shape where it stands off Starfield's bust")
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
    inv = skyrimarmor.read_armor(esm)
    if a.armor:
        # given armor pieces, worn by the NPC's race and sex, instead of its outfit (2026-11-08, owner: "lets try an
        # armor now, the iron armor")
        o["armor"], o["skipped"] = armor_by_edid(inv, a.armor)
    meshes = os_convert.worn_meshes(inv, o["armor"], o["race"], female)
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
                             () if a.no_skin_piece else sorted(body_skin_shapes(textures)), a.head_weights,
                             [n for n, sl in slots_by_shape(gear_bytes, meshes).items() if 3 in sl],
                             feet_skin=any(32 in (m.get("slots") or []) and 37 not in (m.get("slots") or [])
                                           for m in meshes),
                             whole_skin=a.whole_skin, round_bust=a.round_bust and female,
                             strap_gap=(a.strap_gap if a.strap_gap is not None else
                                        (gearfit.STRAP_GAP if female else 0.0)), curved=a.curved,
                             conform=a.conform)
    os.makedirs(a.out, exist_ok=True)
    body_pts = rep.pop("_body_pts")
    dbg = rep.pop("_debug", None)
    skin_used = rep.pop("_skin_used", None)
    hand_mesh_pts = rep.pop("_hand_pts", None)
    body_binds_v = rep.pop("_body_binds", None)
    head_mesh_pts = rep.pop("_head_pts", None)
    body_tris_v = rep.pop("_body_tris", None)
    head_tris_v = rep.pop("_head_tris", None)
    fit_steps = rep.pop("_steps", {})
    body_posed = rep.pop("_body_posed", None)
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
            if not a.add:                 # --add: earlier outfits' converted textures stay and are packed again
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
            parts.append({"shape": skin_sh, "material": sp["material"], "skin": True,
                          "binds": body_binds_v if body_binds_v and all(
                              b in body_binds_v for vw in skin_sh.weights for b, _w in vw) else None})
        body_folder = ""
        if a.morph_test and not a.no_morphs:
            mp, _bm = find_body_morph(sf_data, len(body_pts), female)
            if mp:
                body_folder = "\\".join(w.capitalize() for w in mp.rsplit("/", 1)[0].split("/"))
        files, _recs, prep, material, nifs = os_export.write_armor_parts(
            sf_data, a.out, a.name, a.full or a.name.replace("_", " "), parts, binds, variants=a.test_variants,
            morph_test=body_folder, add=a.add)
        if prep.get("kept_from_plugin"):
            print(f"kept {prep['kept_from_plugin']} records of other outfits already in {os_export.PLUGIN} (--add)")
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
        # the converted textures stay in _staging for later --add runs (packed into the archives each time)
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
    slider_objs = []
    if not a.no_morphs:
        mpath, body_morph = find_body_morph(sf_data, len(body_pts), female)
        if body_morph is None:
            print("no body morph.dat with the body's vertex count found: no slider morphs written")
        else:
            worn = shapes + ([skin_sh] if skin_sh is not None and slots else [])
            # the head mesh's own slider deltas too (2026-11-07, owner: Saadia's halter straps sank into the skin on
            # heavier and thinner bodies, fine at default: they lie over the female head mesh's neck / chest flap,
            # which follows the head's morph, not the body's)
            src_pts, src_morph = body_pts, body_morph
            src_tris = body_tris_v
            if head_mesh_pts is not None:
                hpath, head_morph = find_body_morph(sf_data, len(head_mesh_pts), female)
                if head_morph is not None:
                    if head_tris_v is not None and body_tris_v is not None:
                        src_tris = np.concatenate([body_tris_v, head_tris_v + len(body_pts)])
                    src_pts = np.concatenate([body_pts, head_mesh_pts])
                    src_morph = merged_morph(body_morph, head_morph, len(body_pts))
                    print(f"  slider deltas near the head from {hpath}")
                    head_mesh_pts = None          # its own deltas now: no Thin hold near it
            mstats = {}
            for sh in worn:
                morphs.update(morph_files([sh], nifs[sh.name.decode("latin-1")], src_pts, src_morph, doubled,
                                          skin_used, mstats, hand_mesh_pts, head_mesh_pts,
                                          src_tris if sh.name != SKIN_SHAPE else None))
            rep["morph_stats"] = mstats
            if a.debug_dir:
                # every worn shape and the head at each slider's full extreme, to look for skin coming through
                # outside the game (2026-11-08, owner: "do we need to model these at the different size extremes")
                for sh in worn:
                    rel = gearfit.morph_path(nifs[sh.name.decode("latin-1")], sh.name.decode("latin-1"))
                    if rel in morphs:
                        m_ = sfmorph.parse(morphs[rel])
                        for k in m_.keys:
                            slider_objs.append((f"fit_{safe_name(sh.name.decode('latin-1', 'replace'))}@{k}.obj",
                                                shifted(sh.positions, m_.deltas.get(k, {})), sh.triangles, sh.uvs))
                if len(src_pts) > len(body_pts) and head_tris_v is not None:
                    hp = src_pts[len(body_pts):]
                    for k in src_morph.keys:
                        d_ = {i - len(body_pts): x for i, x in src_morph.deltas.get(k, {}).items() if i >= len(body_pts)}
                        slider_objs.append((f"sf_head@{k}.obj", shifted(hp, d_), head_tris_v, None))
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
        os.makedirs(a.debug_dir, exist_ok=True)
        pngs = debug_textures(a.debug_dir, textures, lambda p: sky._read(bsa.norm(p)), find_texconv(a.texconv))
        if a.debug_steps:
            # the points after each group of fit steps (Starfield skeleton space), to see which step does what
            for sh in shapes:
                nm = sh.name.decode("latin-1", "replace")
                for step, p_ in fit_steps.get(nm, {}).items():
                    if len(p_) == len(sh.positions):
                        slider_objs.append((f"fit_{safe_name(nm)}@step{step}.obj", p_, sh.triangles, sh.uvs, True))
        if a.debug_steps and body_posed is not None:
            # Skyrim's body on Starfield's skeleton and its offsets to Starfield's body (points, skeleton space)
            bp_, off_ = body_posed
            slider_objs.append(("skybody_posed.obj", bp_, np.zeros((0, 3), int), None, True))
            slider_objs.append(("skybody_posed_to_sf.obj", bp_ + off_, np.zeros((0, 3), int), None, True))
        for n_, p_, t_, uv_, *raw_ in slider_objs:
            if raw_:
                write_obj(os.path.join(a.debug_dir, n_), p_, t_, uv_)
                continue
            write_obj(os.path.join(a.debug_dir, n_), np.asarray(p_) @ frame[:3, :3].T + frame[:3, 3], t_, uv_)
        print("debug meshes:", debug_meshes(a.debug_dir, shapes + ([skin_sh] if skin_sh is not None else []),
                                            frame, *dbg, extra=pngs + [o[0] for o in slider_objs]),
              f"({len(pngs)} textures)")
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
    if rep.get("collar_anchor_m"):
        print(f"neck openings (Skyrim, Starfield): {rep['collar_anchor_m'][0]} / {rep['collar_anchor_m'][1]} m")
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
              + (f", {r['inside_neck']} inside the neck line as in Skyrim" if r.get('inside_neck') else "")
              + (f", {r['collar_transplanted']} round the neck copied from Skyrim" if r.get('collar_transplanted') else "")
              + (f", {r['faces_lifted']} lifted so no face dips into the body" if r.get('faces_lifted') else "")
              + (f", {r['rehidden']} put back inside the body as in Skyrim" if r.get('rehidden') else "")
              + (f", {r['strapped']} round the neck / shoulders lifted to the strap gap" if r.get('strapped') else "")
              + (f", {r['tucked']} hidden as in Skyrim drawn back in" if r.get('tucked') else "")
              + (f", collar brought down by {min(r['collar_drop_mm'])}..{max(r['collar_drop_mm'])} mm"
                 if r.get('collar_drop_mm') else "")
              + (f", {r['skirt_vertices']} on skirt bones (hips + thighs)" if r.get('skirt_vertices') else "")
              + (f", {r['skirt_hung']} hung round the legs" if r.get('skirt_hung') else "")
              + (f", {r['draped']} laid on the shoulders as in Skyrim (up to {r['drape_mm']} mm)"
                 if r.get('draped') else ""))
        if r.get("neck_steps") and not r.get("skin_piece") and r["box_m"] and r["box_m"][1][2] > 1.35:
            print("     neck steps:", ", ".join(f"{k} {v}" for k, v in r["neck_steps"].items()))
            if r.get("neck_stretch"):
                print("     above the clavicles, edge length vs Skyrim (10/50/90 %):", r["neck_stretch"])
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
