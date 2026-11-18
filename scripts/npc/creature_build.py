"""The first creature test (docs/npc/creatures.md): Skyrim's chicken in Starfield's CritterRace place, as loose files
at the critter's own paths in a mod folder (no plugin: the files replace the vanilla ones, so the animation index stays
valid). Any trilobite critter then shows the chicken: `player.placeatme 2C180F` (Traits_Critter_Trilobite).

Writes, under --out:
  meshes\\actors\\critter\\characterassets\\skeleton.nif   the critter's shell, COM moved to the chicken's (creature.py)
  meshes\\actors\\critter\\characterassets\\skeleton.rig   the chicken's 32 bones (its root folded into COM)
  meshes\\actors\\critter\\animations\\<critter file>.af/.afx  the chicken's clips under the critter's names (CLIP_MAP)
  meshes\\actors\\critter\\mesh\\critter_trilobite\\critter_trilobite.nif + geometries\\...\\.mesh  the chicken's body
  materials\\, textures\\ (with --texconv: the chicken's own texture; else the trilobite's material)
  creature_build.json (what was written, and checks: bind pose vs rig, clip frames)
Side effects of the test (disable the mod after): the other critters sharing the rig (trident, thorn, spaceroach) lose
their bones; the critter clips not in CLIP_MAP (right turns, deaths, staggers, attacks) stay the critter's and move
no chicken bone (the chicken holds its rest pose in them).

    python -I scripts\\npc\\creature_build.py --skyrim-data "$sky" --starfield-data "$sf\\Data" --calumi $calumi --out "$mods\\S2S Chicken Test"
"""
import argparse
import json
import os
import posixpath
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "scripts", "armor"))

import numpy as np  # noqa: E402

CHICKEN = {"folder": "meshes\\actors\\ambient\\chicken\\",
           "skeleton": "meshes\\actors\\ambient\\chicken\\character assets\\skeleton.hkx",
           "model": "meshes\\actors\\ambient\\chicken\\character assets\\chicken.nif",
           "com": "Pelvis", "project": "ChickenProject"}
CRITTER = {"skeleton": "meshes/actors/critter/characterassets/skeleton.nif",
           "rig": "meshes/actors/critter/characterassets/skeleton.rig",
           "anims": "meshes/actors/critter/animations/",
           "model": "meshes/actors/critter/mesh/critter_trilobite/critter_trilobite.nif",
           "npc": "2C180F"}
# critter descriptor (Actors\Critter\Animations\<x>.afx) <- Skyrim chicken clip; docs/npc/creatures.md for the reasons
CLIP_MAP = [("idle", "MT_Idle"), ("walkforward", "WalkForward"), ("jogforward", "RunForward"),
            ("runforward", "RunForward"), ("turninplace_left90", "TurnLCannedL90"),
            ("turninplace_left180", "TurnLCannedL180"), ("turninplace_left30", "TurnLCannedL90"),
            ("rundeparture_left180", "TurnCannedFleeL180"), ("warn", "AggroWarning1"),
            ("idle_flavor01", "Idle_Fulbody1"), ("idle_flavor02", "Idle_Fulbody2"),
            ("idle_flavor03", "Idle_Fulbody3"), ("idle_flavor04", "Idle_Head1"),
            ("getup_front", "GETUP"), ("getup_back", "GETUP")]


def find_clip(names, folder: str, clip: str):
    """The Skyrim archive path of <clip>.hkx anywhere under folder (names: bsa-normalised, lower case)."""
    want = "\\" + clip.lower() + ".hkx"
    hits = sorted(n for n in names if n.startswith(folder.lower()) and n.endswith(want))
    return hits[0] if hits else None


def plan_clips(sky_names, sf_names, clip_map=CLIP_MAP, folder=CHICKEN["folder"], anims=CRITTER["anims"]):
    """[(critter .afx key, Skyrim .hkx path)] for the pairs both games have, and [missing descriptions]."""
    plan, missing = [], []
    for afx, clip in clip_map:
        key = anims + afx + ".afx"
        src = find_clip(sky_names, folder, clip)
        if key not in sf_names:
            missing.append(f"Starfield {key}")
        elif src is None:
            missing.append(f"Skyrim {clip}.hkx")
        else:
            plan.append((key, src))
    return plan, missing


def material_of(nif_bytes: bytes):
    """The first .mat path a Starfield model names (its shader's), or None."""
    from fo4sf import nif as nifmod
    n = nifmod.parse(nif_bytes)
    return next((s.decode("latin-1") for s in n.strings if s.lower().endswith(b".mat")), None)


def bind_vs_rig(shape, cr) -> dict:
    """How far the mesh's bind pose is from the rig's rest pose, per bone (metres / degrees): the mesh is drawn at
    rig_world * inverse(bind_world), so 0 means it sits at rest exactly as in Skyrim's bind."""
    from fo4sf import creature
    names = creature.bone_name_map(shape.bones, cr.names, CHICKEN["com"])
    wt, wq = cr.rig().rest_world()
    out = {}
    for b, w in shape.joints.items():
        if b not in names:
            continue
        i = cr.names.index(names[b])
        d = float(np.linalg.norm(w[:3, 3] - wt[i]))
        from fo4sf.retarget import mat_to_quat, qmul
        q = np.array(mat_to_quat(tuple(w[:3, :3].reshape(9))))
        ref = wq[i]
        if names[b] == creature.COM and cr.level is not None:
            ref = qmul(wq[i], cr.level)          # COM rests level: the Skyrim bone's pitch is in `level` (fix 4)
        ang = float(np.degrees(2 * np.arccos(min(1.0, abs(float(np.dot(q, ref)))))))
        out[names[b]] = (round(d, 4), round(ang, 2))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield-data", required=True)
    ap.add_argument("--calumi", required=True, help="CALUMI.Animation.dll (writes the rig and clips)")
    ap.add_argument("--out", required=True, help="the test mod folder (MO2 mod)")
    ap.add_argument("--texconv", default="", help="texconv.exe: the chicken's own texture (else the trilobite's material)")
    ap.add_argument("--content-resources", default="", help="ContentResources.zip (default: Starfield\\Tools)")
    ap.add_argument("--work", default="", help="scratch folder (default: <out>\\_work, removed after)")
    ap.add_argument("--double-sided", choices=("auto", "on", "off"), default="auto",
                    help="add back faces: auto = when Skyrim's shader sets SLSF2_Double_Sided")
    ap.add_argument("--no-rig-fields", action="store_true",
                    help="leave CALUMI's empty per-bone mirror / level / weight fields (the old rig, freezes afar)")
    ap.add_argument("--no-rig-package", action="store_true",
                    help="build the rig without the vanilla critter rig's package settings (the old rig)")
    ap.add_argument("--body-lods", type=int, default=4, choices=(1, 2, 3, 4),
                    help="LOD slots the body mesh fills (vanilla creatures: 4; 1 = LOD0 only, the old build)")
    ap.add_argument("--opaque", action="store_true",
                    help="the chicken's material without the alpha cutout (to rule the cutout out)")
    ap.add_argument("--vanilla-material", action="store_true",
                    help="give the chicken the trilobite's own material (rules the converted material out)")
    a = ap.parse_args(argv)

    from fo4sf import af_writer, bsa, creature, gearfit, nif as nifmod, retarget, skyrimhkx, skyrimnif, skyrimskin
    import sf_anim_survey as SAS
    out = os.path.abspath(a.out)
    work = os.path.abspath(a.work or os.path.join(out, "_work"))
    os.makedirs(out, exist_ok=True)
    rep = {"written": [], "notes": []}

    def put(rel, data):
        p = os.path.join(out, *rel.replace("\\", "/").split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)
        rep["written"].append(rel)

    sky = bsa.SkyrimArchives(a.skyrim_data, loose=False)
    sky_names = {bsa.norm(n) for ar in sky.archives for n in ar.names}
    index = {}
    for _label, ar in SAS.archives(a.starfield_data):
        for i, n in enumerate(ar.names):
            index.setdefault(SAS.norm(n), (ar, i))

    def sf_read(key):
        ar, i = index[key]
        return ar.read(i)

    # 1. the rig
    d = skyrimhkx.describe(sky._read(CHICKEN["skeleton"]))
    sk_desc = max(d["skeletons"], key=lambda s: len(s["bones"]))
    sk = retarget.rig_from_hkx_skeleton(sk_desc)
    cr = creature.creature_rig(sk, CHICKEN["com"])
    ci = cr.com_index
    rep["rig"] = {"bones": cr.names, "com_rest_m": [round(float(v), 4) for v in cr.t[ci]],
                  "com_level_q": [round(float(v), 4) for v in (cr.level if cr.level is not None else (0, 0, 0, 1))]}

    # 2. the shell
    put(CRITTER["skeleton"], creature.shell_skeleton(sf_read(CRITTER["skeleton"]), "Critter_mrRigRoot", cr.t[ci],
                                                     cr.q[ci]))

    # 3. the body
    model = sky._read(CHICKEN["model"])
    src = nifmod.parse(model)
    shapes = skyrimskin.skinned_shapes(src)
    if len(shapes) != 1:
        rep["notes"].append(f"{len(shapes)} skinned shapes in the chicken model; the first is used")
    s = shapes[0]
    shape = gearfit.from_skyrim(s)
    rep["bind_vs_rig_m_deg"] = bind_vs_rig(shape, cr)
    material = None
    texconv = gearfit_find_texconv(a.texconv)
    cr_zip = a.content_resources or os.path.join(os.path.dirname(os.path.abspath(a.starfield_data)), "Tools",
                                                 "ContentResources.zip")
    if texconv and os.path.isfile(cr_zip) and not a.vanilla_material:
        from fo4sf import skyrimconvert
        conv = skyrimconvert.SkyrimConverter(sky, os.path.join(work, "staging"), texconv, cr_zip, prefix="s2s")
        if a.opaque:
            tex = skyrimnif.texture_set(src, s.shader_ref) or []
            material = conv.skyrim_material(tex[0] if tex else "", tex[1] if len(tex) > 1 else "", False, False, 128)
        else:
            material = conv._shape_material(src, s)
        if material == conv.neutral:
            material = None
        staging = os.path.join(work, "staging")
        for top in ("materials", "textures"):
            if os.path.isdir(os.path.join(staging, top)):
                shutil.copytree(os.path.join(staging, top), os.path.join(out, top), dirs_exist_ok=True)
                rep["written"].append(top + "\\ (converted)")
        rep["material_errors"] = dict(conv.material_errors)
    if material is None:
        material = material_of(sf_read(CRITTER["model"]))
        rep["notes"].append(f"material: the trilobite's own ({material}); pass --texconv for the chicken's texture")
    test, blend, ref = skyrimnif.alpha_test(src, s.alpha_ref)
    two_sided = skyrimnif.double_sided(src, s.shader_ref)
    rep["skyrim_shader"] = {"double_sided": two_sided, "alpha_test": test, "alpha_blend": blend, "alpha_ref": ref,
                            "material": material, "opaque_forced": bool(a.opaque)}
    tangents = None
    if s.tangents and len(s.tangents) == len(shape.points):
        from fo4sf.skyrimhair import skin_to_model
        _to_model, rot = skin_to_model(s)
        tangents = [rot(t) for t in s.tangents]
    else:
        rep["notes"].append("no tangents in the Skyrim mesh: none written")
    if a.double_sided == "on" or (a.double_sided == "auto" and two_sided):
        shape, tangents = creature.with_back_faces(shape, tangents)
        rep["skyrim_shader"]["back_faces_added"] = True
    files = creature.skinned_files(shape, material, CRITTER["model"][len("meshes/"):-len(".nif")], CHICKEN["com"],
                                   cr, tangents, lods=a.body_lods)
    rep["body_lods"] = a.body_lods
    for rel, data in files.items():
        put(rel, data)

    # 4. clips (+ the rig), with Skyrim's root motion on Root and in the header (as the critter's moving clips)
    from fo4sf import rootmotion
    motion = motion_blocks(sky, CHICKEN["folder"], CHICKEN["project"], rep)
    plan, missing = plan_clips(sky_names, set(index))
    rep["clips_missing"] = missing
    anim_out = os.path.join(work, "anims")
    from fo4sf import agx

    def prepared(key, src_clip):
        clip = retarget.resample(skyrimhkx.decode_clip(sky._read(src_clip), sk_desc["bones"]))
        lt, lq = creature.clip_locals(clip, sk, cr)
        clip_stem = posixpath.basename(src_clip.replace("\\", "/"))[:-len(".hkx")].lower()
        rt, rq = root_motion(motion.get(clip_stem), lt.shape[0], rootmotion)
        moving = rt is not None and rootmotion.moves(rt, rq)
        if moving:
            lt[:, 0], lq[:, 0] = rt, rq
        vafx = sf_read(key)
        stem = os.path.splitext(agx.read_descriptor(vafx)["filename"] or posixpath.basename(key))[0]
        return lt, lq, rt, rq, moving, vafx, stem

    # The rig first: CALUMI writes it with the first clip; its per-bone mirror / level / weight fields are set
    # (creature.set_rig_fields) before any clip is written against it. Without them the whole creature froze a few
    # feet off (owner, 2026-11-17: the vanilla rig copied by CALUMI froze the trilobite; restoring them fixed it).
    rig_file = None
    if plan:
        lt, lq, _rt, _rq, moving, vafx, stem = prepared(*plan[0])
        # the vanilla critter rig lends its rig package (Root / COM bone-map keys, precision, mannequin flag): the
        # sf_animation_io add-on maps at least Root when it exports a rig; ours had none (whole chicken froze afar)
        vanilla_rig = os.path.join(work, "critter_vanilla.rig")
        os.makedirs(work, exist_ok=True)
        with open(vanilla_rig, "wb") as fh:
            fh.write(sf_read(CRITTER["rig"]))
        r = af_writer.write(a.calumi, os.path.join(work, "rig"), stem, cr.names, cr.parents, cr.t, cr.q, lt, lq,
                            rig_name="S2SChicken", like_afx=vafx, file_name=stem,
                            omit=() if moving else (creature.ROOT,),
                            package_like=None if a.no_rig_package else vanilla_rig)
        rep["rig"]["package_keys"] = r.get("package_keys", {})
        rig_file = r["rig"]
        with open(rig_file, "rb") as fh:
            rig_bytes = fh.read()
        if not a.no_rig_fields:
            mirror, level, weight = creature.rig_fields(cr)
            try:
                rig_bytes = creature.set_rig_fields(rig_bytes, mirror, level, weight)
                rep["rig"]["fields"] = {n: [cr.names[m], lv, w] for n, m, lv, w in zip(cr.names, mirror, level, weight)}
                with open(rig_file, "wb") as fh:
                    fh.write(rig_bytes)
            except ValueError as e:
                rep["notes"].append(f"rig fields not set: {e}")
        put(CRITTER["rig"], rig_bytes)
    rep["clips"] = []
    for key, src_clip in plan:
        lt, lq, rt, rq, moving, vafx, stem = prepared(key, src_clip)
        r = af_writer.write(a.calumi, anim_out, stem, cr.names, cr.parents, cr.t, cr.q, lt, lq, rig_path=rig_file,
                            rig_name="S2SChicken", like_afx=vafx, file_name=stem,
                            omit=() if moving else (creature.ROOT,))
        if moving:
            rootmotion.patch_header(os.path.join(anim_out, stem + ".af"), rt[-1], rq[-1])
        for ext in (".af", ".afx"):
            with open(os.path.join(anim_out, stem + ext), "rb") as fh:
                put(CRITTER["anims"] + stem + ext, fh.read())
        rep["clips"].append({"critter": key, "skyrim": src_clip, "frames": r["frames"], "keys": r["keys"],
                             "root_motion_m_deg": None if not moving else
                             [round(float(v), 3) for v in rt[-1]] + [round(rootmotion.yaw_degrees(rq[-1]), 1)]})
    shutil.rmtree(work, ignore_errors=True)
    with open(os.path.join(out, "creature_build.json"), "w") as fh:
        json.dump(rep, fh, indent=1)
    print(f"wrote {len(rep['written'])} files to {out}; clips {len(rep['clips'])}, missing {missing}")
    print(f"in game: enable the mod, then  player.placeatme {CRITTER['npc']}")
    return 0


def motion_blocks(sky, folder: str, project: str, rep: dict) -> dict:
    """{clip file stem: motion block} of a Skyrim creature project (animationdatasinglefile, mapped to clip files
    through the project's behaviours; creature_probe --motion printed the chicken's: walk 0.50 m/s, run 3.6 m/s,
    canned turns +90 / +180 deg, flee turns that also move). {} when the file is not in the archives."""
    from fo4sf import animdata, bsa, skyrimbehavior
    try:
        text = sky._read("meshes\\animationdatasinglefile.txt")
    except Exception:                                    # noqa: BLE001
        text = None
    if not text:
        rep["notes"].append("animationdatasinglefile.txt not found: clips without root motion")
        return {}
    projects = animdata.parse(text.decode("latin-1"))
    proj = next((p for k, p in projects.items() if k.lower() == project.lower()), None)
    if proj is None:
        rep["notes"].append(f"motion: project {project} not found")
        return {}
    behaviors = []
    for ar in sky.archives:
        for n in ar.names:
            k = bsa.norm(n)
            if k.startswith(folder) and "\\behaviors\\" in k and k.endswith(".hkx"):
                try:
                    behaviors.append(skyrimbehavior.read(sky._read(k)))
                except Exception:                        # noqa: BLE001
                    pass
    return animdata.clip_motion(proj, animdata.clip_generators(behaviors))


def root_motion(block, frames: int, rootmotion, fps: float = 30.0):
    """(F, 3) metres / (F, 4) Root track of a motion block over a clip of `frames` at fps, or (None, None)."""
    from fo4sf.retarget import SKYRIM_M_PER_UNIT
    if not block:
        return None, None
    m = rootmotion.from_annotations(rootmotion.motion_annotations(block), frames, fps)
    if m is None:
        return None, None
    return rootmotion.root_track(m, SKYRIM_M_PER_UNIT)


def gearfit_find_texconv(given):
    import gear_fit
    return gear_fit.find_texconv(given)


if __name__ == "__main__":
    sys.exit(main())
