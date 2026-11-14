"""Measure how thick each body part is around its bone, for Skyrim's and Starfield's male bodies (read-only): the
radius grids fo4sf.bodyprofile uses to keep a hand's contact with the body when a Skyrim clip plays on Starfield's.

    python -I scripts\\armor\\body_profiles.py --skyrim-data "$sky" --starfield $sf --out C:\\Modding\\work\\body_profiles

Writes <out>\\body_profiles.json ({"skyrim": {segment: profile}, "starfield": {...}, "summary": [...]}) and prints
each segment's mean radius in both bodies, Skyrim's also at Starfield's height (the retarget scales Skyrim's motion by
the skeletons' height ratio). Skyrim: malebody_1 + hands + feet in their bind pose, joints from the
skins (the skeleton NIF for joints no skin has). Starfield: the naked body and the hands in skeleton space, joints from
the skeleton NIF.
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

from fo4sf import bodyprofile as BP  # noqa: E402

SKYRIM_SKELETON = "meshes\\actors\\character\\character assets\\skeleton.nif"


def skyrim_side(sky_data: str):
    """(points (N, 3) metres, joints {name: (3,)}) of Skyrim's male body in its bind pose."""
    import gear_fit
    import os_convert
    from fo4sf import bsa, gearfit, skyrimhair
    from fo4sf import nif as nifmod
    sky = bsa.SkyrimArchives(sky_data)
    pts, joints = [], {}
    for p in [os_convert.SKYRIM_BODY[False]] + gear_fit.SKYRIM_LIMBS[False]:
        data = sky._read(bsa.norm(p))
        if data is None:
            print("not in Skyrim's archives (skipped):", p)
            continue
        for sh in gear_fit.sky_shapes(data):
            if gear_fit.is_underwear(sh.name):
                continue
            pts.append(BP.sample_surface(sh.points, sh.triangles, 20000))
            for n, w in sh.joints.items():
                joints.setdefault(n, np.asarray(w)[:3, 3])
    skel = sky._read(bsa.norm(SKYRIM_SKELETON))
    if skel is not None:                                  # joints no skin carries (the neck when the body lacks it)
        nodes, _par = skyrimhair.node_worlds(nifmod.parse(skel))
        for n, w in nodes.items():
            joints.setdefault(n, np.asarray(w)[:3, 3] * gearfit.UNIT)
    if not pts:
        sys.exit("Skyrim's male body not found in the archives")
    return np.concatenate(pts), joints


def starfield_side(sf_data: str):
    """(points (N, 3) metres, joints) of Starfield's male naked body + hands in skeleton space."""
    import gear_fit
    import hkx_to_af
    import npc_hair
    from fo4sf import gearfit
    world = npc_hair.skeleton_world(hkx_to_af.vanilla_file(npc_hair.SF_SKELETON, sf_data)[0])
    pts, tris, binds, _w = gear_fit.starfield_body(sf_data, False)
    frame = gearfit.mesh_frame(binds, world)
    body = BP.sample_surface(pts @ frame[:3, :3].T + frame[:3, 3], tris, 60000)
    _p, hand_pts, hand_tris, _hw = gear_fit.find_hands(sf_data, False, world)
    if hand_pts is not None:
        body = np.concatenate([body, BP.sample_surface(hand_pts, hand_tris, 20000)])
    return body, {n: np.asarray(w)[:3, 3] for n, w in world.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True, help="Skyrim SE's Data folder")
    ap.add_argument("--starfield", required=True, help="Starfield's game folder")
    ap.add_argument("--out", required=True, help="a folder outside the repository")
    a = ap.parse_args(argv)
    if os.path.abspath(a.out).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    sf_data = os.path.join(a.starfield, "Data") if os.path.isdir(os.path.join(a.starfield, "Data")) else a.starfield
    sky_pts, sky_j = skyrim_side(a.skyrim_data)
    sf_pts, sf_j = starfield_side(sf_data)
    sky = BP.measure(sky_j, sky_pts, BP.segments_for("skyrim"))
    sf = BP.measure(sf_j, sf_pts, BP.segments_for("starfield"))
    missing = {"skyrim": [s[0] for s in BP.SEGMENTS if s[0] not in sky],
               "starfield": [s[0] for s in BP.SEGMENTS if s[0] not in sf]}
    rows = BP.summary(sky, sf)
    h_sky, h_sf = BP.height(sky_j, "skyrim"), BP.height(sf_j, "starfield")
    scale = h_sf / h_sky if h_sky and h_sf else 1.0
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "body_profiles.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"skyrim": sky, "starfield": sf, "summary": rows, "missing": missing, "height_scale": scale,
                   "points": {"skyrim": len(sky_pts), "starfield": len(sf_pts)}}, fh, indent=1)
    print(f"Skyrim body {len(sky_pts)} points, Starfield body {len(sf_pts)} points")
    for r in rows:
        print(f"  {r['segment']:12s} Skyrim {r['skyrim_m']:.3f} m (at Starfield's height {r['skyrim_m'] * scale:.3f})"
              f"  Starfield {r['starfield_m']:.3f} m  x{r['ratio'] / scale:.2f}")
    print(f"height: Skyrim {h_sky:.3f} m, Starfield {h_sf:.3f} m (x{scale:.3f}), neck joint over the feet")
    if missing["skyrim"] or missing["starfield"]:
        print("missing segments:", missing)
    print("->", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
