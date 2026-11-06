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

from fo4sf import bsa, facefit, gearfit, sfmesh, skyrimarmor, skyrimskin  # noqa: E402
from fo4sf import nif as nifmod  # noqa: E402
import hkx_to_af  # noqa: E402
import npc_hair  # noqa: E402
import os_convert  # noqa: E402
import os_export  # noqa: E402


def sky_shapes(nif_bytes: bytes):
    return [gearfit.from_skyrim(s) for s in skyrimskin.skinned_shapes(nifmod.parse(nif_bytes))]


def starfield_body(sf_data: str, female: bool):
    """(points mesh space, triangles, body binds {bone: bind}) of the game's naked body."""
    nif, _ = hkx_to_af.vanilla_file(os_convert.SF_BODY[female], sf_data)
    paths, skin = facefit.starfield_head_parts(nif)
    m = sfmesh.parse(hkx_to_af.vanilla_file("geometries/" + paths[0].replace("\\", "/") + ".mesh", sf_data)[0])
    pts, _w = facefit.mesh_arrays(m)
    tris = np.array([tuple(t) for t in m.triangles], int).reshape(-1, 3)
    binds = dict(zip([b.decode("latin-1") for b in skin.get("bones", [])], skin.get("binds", [])))
    return pts, tris, binds


def run(gear_nifs, body_nif, sf_data: str, female: bool, skip=(), gap: float = gearfit.GAP):
    """(shapes in mesh space with tangents, binds, report)."""
    world = npc_hair.skeleton_world(hkx_to_af.vanilla_file(npc_hair.SF_SKELETON, sf_data)[0])
    pts, tris, body_binds = starfield_body(sf_data, female)
    frame = gearfit.mesh_frame(body_binds, world)
    skel_pts = pts @ frame[:3, :3].T + frame[:3, 3]
    gear = [s for nb in gear_nifs for s in sky_shapes(nb)]
    skipped = [s.name.decode("latin-1") for s in gear if s.name.decode("latin-1").lower() in {x.lower() for x in skip}]
    gear = [s for s in gear if s.name.decode("latin-1") not in skipped]
    res = gearfit.fit(gear, sky_shapes(body_nif), world, skel_pts, tris, gap)
    shapes = gearfit.to_mesh_space(res.shapes, frame)
    for i, sh in enumerate(shapes):
        sh.tangents = os_export.tangents(np.asarray(sh.positions), np.asarray(sh.normals), sh.uvs, sh.triangles)
        shapes[i] = sh
    bones = sorted({b for sh in shapes for vw in sh.weights for b, _w in vw} | {"C_Chest"})
    binds = gearfit.skeleton_binds(bones, world, frame, shapes)
    res.report.update(skipped=skipped, frame=frame.round(6).tolist())
    return shapes, binds, res.report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--npc", required=True, help="Skyrim NPC EditorID (its default outfit is converted)")
    ap.add_argument("--name", required=True, help="file / record name, e.g. Ralof_outfit")
    ap.add_argument("--full", default=None, help="the armor's in-game name")
    ap.add_argument("--out", required=True, help="the mod folder (outside the repository)")
    ap.add_argument("--skip", default="", help="comma-separated shape names to leave out")
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
    shapes, binds, rep = run([read(m["mesh"]) for m in meshes], read(os_convert.SKYRIM_BODY[female]), sf_data,
                             female, [x.strip() for x in a.skip.split(",") if x.strip()], a.gap)
    os.makedirs(a.out, exist_ok=True)
    broken = {n: r for n, r in rep["shapes"].items() if r["not_finite"] or r["far_outside"]}
    if broken:
        with open(os.path.join(a.out, "gear_fit.json"), "w", encoding="utf-8") as fh:
            json.dump(rep, fh, indent=1, default=str)
        for n, r in broken.items():
            print(f"  {n}: {r['not_finite']} vertices not finite, {r['far_outside']} far outside the body, "
                  f"box {r['box_m']}")
        print("nothing written: broken shapes (report in gear_fit.json)")
        return 1
    files, _recs, prep, material, _model = os_export.write_armor(
        sf_data, a.out, a.name, a.full or a.name.replace("_", " "), shapes, binds)
    rep.update(npc=a.npc, meshes=meshes, records=prep, material=material, files=sorted(files))
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
              f"{r['unweighted']} unweighted")
    if rep.get("skipped"):
        print("left out:", ", ".join(rep["skipped"]))
    print(f"{os_export.PLUGIN}: ARMO {prep['ARMO']} (S2S_{a.name}); material {material}")
    print(f"in game: player.additem xx{int(prep['ARMO'], 16) & 0xFFFFFF:06X} 1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
