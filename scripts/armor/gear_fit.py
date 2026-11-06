"""A Skyrim NPC's outfit fitted onto Starfield's body by the skeleton and body shape (fo4sf.gearfit), without Outfit
Studio (2026-11-06: Outfit Studio's fit left the collar over the face, the gloves following the hips and the coat
folded; owner: "fit the Starfield body the way it does on Skyrim's").

Reads the NPC's default outfit and the Skyrim body from Skyrim's archives, Starfield's body and skeleton from the
game's archives, fits (gearfit.fit), and writes the armor mod as os_export does (meshes\\S2S\\<name>.nif, its .mesh
files, S2SArmorTest.esm with ARMA / ARMO / OTFT; the 1 mm anchor shape first). gear_fit.json holds the report.

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


HAND_BONES = ("L_Wrist", "R_Wrist", "L_Index", "R_Index")


def sex_ok(base: str, female: bool) -> bool:
    """Whether a file name can be for this sex (names without a sex mark count for both)."""
    is_f = "female" in base or "_f." in base or "_f_" in base
    is_m = ("male" in base and "female" not in base) or "_m." in base or "_m_" in base
    return not is_m if female else not is_f


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


def skin_shapes(textures: dict) -> set:
    """Names of shapes textured with Skyrim's own skin (bare body parts: Starfield's body shows there instead;
    2026-11-06, Ralof: MaleBodyStormcloak = MaleBody_1.dds, HandMale_Big1stperson = MaleHands_1.dds)."""
    return {n for n, t in textures.items() if t and t[0].lower().replace("/", "\\").startswith(SKIN_TEXTURES)}


def run(gear_nifs, body_nif, sf_data: str, female: bool, skip=(), gap: float = gearfit.GAP, skin_names=()):
    """(shapes in mesh space with tangents, binds, report)."""
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
    gear = [s for nb in gear_nifs for s in sky_shapes(nb)]
    skipped = [s.name.decode("latin-1") for s in gear if s.name.decode("latin-1").lower() in {x.lower() for x in skip}]
    gear = [s for s in gear if s.name.decode("latin-1") not in skipped]
    body_nifs = body_nif if isinstance(body_nif, (list, tuple)) else [body_nif]
    sky_body = [s for nb in body_nifs for s in sky_shapes(nb)]
    res = gearfit.fit(gear, sky_body, world, surf_pts, surf_tris, gap, sf_body_weights=surf_w)
    if skin_names:                           # Skyrim's bare-skin pieces
        drop = {n for n in res.report["shapes"] if n in set(skin_names)}
        res.shapes = [sh for sh in res.shapes if sh.name.decode("latin-1", "replace") not in drop]
        res.report["dropped_skin_pieces"] = sorted(drop)
    shapes = gearfit.to_mesh_space(res.shapes, frame)
    for i, sh in enumerate(shapes):
        sh.tangents = os_export.tangents(np.asarray(sh.positions), np.asarray(sh.normals), sh.uvs, sh.triangles)
        shapes[i] = sh
    bones = sorted({b for sh in shapes for vw in sh.weights for b, _w in vw} | {"C_Chest"})
    binds = gearfit.skeleton_binds(bones, world, frame, shapes)
    res.report.update(skipped=skipped, frame=frame.round(6).tolist(), hands=hand_path)
    res.report["_body_pts"] = pts
    return shapes, binds, res.report


def morph_files(shapes, nif_rel: str, body_pts, body_morph, doubled=()) -> dict:
    """{path: morph.dat bytes} per shape: its vertices move with the nearest body vertices under the sliders. A shape
    written with back faces has its vertices twice (copies after the originals): the copies get the same deltas."""
    out = {}
    for sh in shapes:
        name = sh.name.decode("latin-1")
        n = len(sh.positions)
        d, extra = gearfit.morph_deltas(np.asarray(sh.positions), body_pts, body_morph)
        total = n
        if name in doubled:
            d = {k: {**v, **{i + n: x for i, x in v.items()}} for k, v in d.items()}
            extra = {k: {**v, **{i + n: x for i, x in v.items()}} for k, v in extra.items()}
            total = 2 * n
        out[gearfit.morph_path(nif_rel, name)] = sfmorph.build(total, list(body_morph.keys), d, extra)
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
    ap.add_argument("--back-faces", choices=("auto", "all", "none"), default="auto",
                    help="add back faces: to Skyrim's double-sided shapes (auto), to every shape, or none")
    ap.add_argument("--no-morphs", action="store_true", help="write no body-slider morph.dat files")
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
          *[f"{m['armor']} {m['mesh']}" for m in meshes], sep="\n  ")
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
                             () if a.keep_skin else sorted(skin_shapes(textures)))
    os.makedirs(a.out, exist_ok=True)
    body_pts = rep.pop("_body_pts")
    broken = {n: r for n, r in rep["shapes"].items() if r["not_finite"] or r["far_outside"]}
    if broken:
        with open(os.path.join(a.out, "gear_fit.json"), "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=1, default=str)
        for n, r in broken.items():
            print(f"  {n}: {r['not_finite']} vertices not finite, {r['far_outside']} far outside the body, "
                  f"box {r['box_m']}")
        print("nothing written: broken shapes (report in gear_fit.json)")
        return 1
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
    files, _recs, prep, material, _model = os_export.write_armor(
        sf_data, a.out, a.name, a.full or a.name.replace("_", " "), shapes, binds,
        back_faces=[n in doubled for n in names], materials=[mats.get(n) for n in names])
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
            morphs = morph_files(shapes, f"S2S\\{a.name}.nif", body_pts, body_morph, doubled)
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
    rep.update(npc=a.npc, meshes=meshes, records=prep, material=material, files=sorted(files) + sorted(morphs))
    with open(os.path.join(a.out, "gear_fit.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1, default=str)
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
              f"{r.get('covered', 0)} moved to cover the body")
    if rep.get("skipped"):
        print("left out:", ", ".join(rep["skipped"]))
    print("hands in the push-out surface:", rep.get("hands") or "NOT FOUND")
    if rep.get("dropped_skin_pieces"):
        print("bare-skin shapes left out (Skyrim skin textures):", ", ".join(rep["dropped_skin_pieces"]))
    feet = rep.get("feet") or {}
    for side, f in feet.items():
        print(f"foot {side}: boot foot scaled {f['scale']} to Starfield's foot")
    if not feet:
        print("foot sizing: SKIPPED (no Skyrim or Starfield foot region found)")
    print(f"{os_export.PLUGIN}: ARMO {prep['ARMO']} (S2S_{a.name}); material {material}")
    print(f"in game: player.additem xx{int(prep['ARMO'], 16) & 0xFFFFFF:06X} 1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
