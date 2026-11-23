"""Read-only: where the head points, frame by frame, in a Skyrim clip and in its conversion (no CALUMI, nothing written
but the report).

    python -I scripts\\armor\\head_turn_probe.py --skyrim-data "$sky" --starfield-data "$sf\\Data" --clip <StepDodgeForward.hkx>
        [--shoulder-calibration C:\\Modding\\work\\shoulders.json]

Why (docs/ai/decisions.md 2026-11-23): in the converted forward dodge the head turns right, not in Skyrim, and switching
the game's head tracking off did not change it (LookAtHeadingVar still 2.4-2.7 rad mid-dodge). This tells whether the
turn is in the converted clip: per frame, the yaw / pitch (degrees) of the head's facing relative to the chest's,
in Skyrim (NPC Head vs NPC Spine2) and after retargeting (C_Head vs C_Chest), plus the Starfield head and DirectAt
facing in character space. Facing = the bone's world rotation applied to the character's forward (+Y) through its rest
pose, so both skeletons are measured the same way: 0 / 0 at rest, yaw > 0 = turned to the character's left.
"""
import argparse
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf.retarget import qinv, qmul, qrot  # noqa: E402

SKY_PAIR = ("NPC Head [Head]", "NPC Spine2 [Spn2]")
SF_PAIR = ("C_Head", "C_Chest")
FORWARD = np.array([0.0, 1.0, 0.0])


def facing(wq, rest_wq) -> np.ndarray:
    """(F, 3) the character's forward carried by the bone's turn from its rest pose (world rotation * rest inverse)."""
    d = qmul(wq, qinv(rest_wq)[None])
    return qrot(d, np.broadcast_to(FORWARD, d.shape[:-1] + (3,)))


def yaw_pitch(v) -> np.ndarray:
    """(F, 2) degrees: yaw about +Z from +Y (left positive), pitch above the horizontal."""
    v = np.asarray(v, float)
    yaw = np.degrees(np.arctan2(-v[..., 0], v[..., 1]))
    pitch = np.degrees(np.arctan2(v[..., 2], np.hypot(v[..., 0], v[..., 1])))
    return np.stack([yaw, pitch], axis=-1)


def relative(head_f, chest_f) -> np.ndarray:
    """(F, 2) the head's yaw / pitch minus the chest's (wrapped to -180..180)."""
    d = yaw_pitch(head_f) - yaw_pitch(chest_f)
    d[..., 0] = (d[..., 0] + 180.0) % 360.0 - 180.0
    return d


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield-data", required=True)
    ap.add_argument("--clip", required=True, help="the Skyrim .hkx (file or archive path)")
    ap.add_argument("--shoulder-calibration", metavar="JSON")
    ap.add_argument("--out", help="also write the per-frame table as JSON here (outside the repository)")
    a = ap.parse_args(argv)
    import hkx_to_af
    from fo4sf import bsa, retarget, skyrimhkx
    sky = bsa.SkyrimArchives(a.skyrim_data)
    sk_desc = skyrimhkx.describe(hkx_to_af.read_any(hkx_to_af.SKY_SKELETON, sky))
    sk = retarget.rig_from_hkx_skeleton(next(s for s in sk_desc["skeletons"] if len(s["bones"]) > 20))
    _name, sf_nif = hkx_to_af.starfield_find(a.starfield_data, hkx_to_af.SF_SKELETON_RX)
    if sf_nif is None:
        sys.exit("Starfield human skeleton.nif not found in the Meshes archives")
    sf = retarget.rig_from_nif(sf_nif)
    clip = skyrimhkx.decode_clip(hkx_to_af.read_any(a.clip, sky), sk.names)
    if clip.get("fps") and abs(clip["fps"] - hkx_to_af.FPS) > 0.01:
        clip = retarget.resample(clip, hkx_to_af.FPS)
    shoulders = None
    if a.shoulder_calibration:
        with open(a.shoulder_calibration, encoding="utf-8") as fh:
            shoulders = {k: v for k, v in json.load(fh).items() if k in ("L", "R")}
    res = retarget.retarget(clip, sk, sf, weapon_in_hand=True, shoulder_offsets=shoulders)
    lt, lq = retarget.skyrim_locals(clip, sk)
    _wt, wq_sk = sk.fk(lt, lq)
    _rt, rq_sk = sk.rest_world()
    _wt2, wq_sf = sf.fk(res["t"], res["q"])
    _rt2, rq_sf = sf.rest_world()
    f = {}
    for rig, wq, rq, names, tag in ((sk, wq_sk, rq_sk, SKY_PAIR, "skyrim"), (sf, wq_sf, rq_sf, SF_PAIR, "starfield")):
        missing = [n for n in names if n not in rig.index]
        if missing:
            sys.exit(f"{tag} skeleton has no {missing}")
        h, c = (rig.index[n] for n in names)
        f[tag] = (facing(wq[:, h], rq[h]), facing(wq[:, c], rq[c]))
    sky_rel = relative(*f["skyrim"])
    sf_rel = relative(*f["starfield"])
    sf_head = yaw_pitch(f["starfield"][0])
    da = sf.index.get("DirectAt")
    sf_da = yaw_pitch(facing(wq_sf[:, da], rq_sf[da])) if da is not None else np.full_like(sf_head, math.nan)
    print(f"{os.path.basename(a.clip)}: {len(sky_rel)} frames; degrees, head relative to chest (yaw left +, pitch up +)")
    print(" frame | Skyrim yaw pitch | converted yaw pitch | diff yaw pitch | SF head yaw pitch | DirectAt yaw pitch")
    rows = []
    for i in range(len(sky_rel)):
        d = sf_rel[i] - sky_rel[i]
        print(f" {i:5d} | {sky_rel[i, 0]:7.1f} {sky_rel[i, 1]:6.1f} | {sf_rel[i, 0]:9.1f} {sf_rel[i, 1]:6.1f} | "
              f"{d[0]:6.1f} {d[1]:6.1f} | {sf_head[i, 0]:8.1f} {sf_head[i, 1]:6.1f} | {sf_da[i, 0]:7.1f} "
              f"{sf_da[i, 1]:6.1f}")
        rows.append({"frame": i, "skyrim": sky_rel[i].round(2).tolist(), "converted": sf_rel[i].round(2).tolist(),
                     "head": sf_head[i].round(2).tolist(), "directat": sf_da[i].round(2).tolist()})
    worst = np.abs(sf_rel - sky_rel).max(axis=0)
    print(f"largest difference: yaw {worst[0]:.1f} deg, pitch {worst[1]:.1f} deg")
    if a.out:
        if os.path.abspath(a.out).lower().startswith(os.path.abspath(REPO).lower()):
            sys.exit("--out must be outside the repository")
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump({"clip": a.clip, "rows": rows, "largest_diff_deg": worst.round(2).tolist()}, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
