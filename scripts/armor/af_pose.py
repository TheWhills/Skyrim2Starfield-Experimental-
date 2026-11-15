"""Where a .af clip puts the body (read-only): joint world positions at a frame, read back the game's way (CALUMI,
rest-relative keys composed with the rig), side by side for several clips. For a pose that looks wrong in game:
is the clip itself wrong (conversion), or is the game moving the body after it (graph, IK, additive layers)?

2026-11-13 (owner): Skyrim's seated idle on our benches plays with the arms pulled back and twisted inward, hands by the
hips; Skyrim's own has them forward. Compare our Idle with Starfield's chair Idle:

    python -I scripts\\armor\\af_pose.py --calumi "<CALUMI.Animation.dll>" --starfield-data "$sf\\Data"
        --af "$mods\\S2S Furniture Anims\\meshes\\actors\\human\\animations\\furniture\\s2s_sit\\Idle.af"
        --af meshes\\actors\\human\\animations\\furniture\\chair\\Idle.af

A --af that is not a file on disk is read from Starfield's archives. Prints, per clip, the arm / leg / spine joints
(metres, the actor's frame: x right, y forward, z up, as Starfield's rig) and the hands relative to the pelvis.

2026-11-14 (owner): with hand IK gone the seated hands rest forward but sink into the thighs. Each clip now also
prints where each hand sits over its thigh (hands_on_thighs); compare our Idle's height above the hip-knee line with
Starfield's chair Idle to see how far the hands must come up.
"""
import argparse
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

JOINT_RE = re.compile(r"pelvis|spine|chest|neck|head|clav|upperarm|arm|elbow|forearm|hand$|wrist|thigh|calf|knee|"
                      r"foot$|ankle|com$", re.I)


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz])


def qrot(q, v):
    x, y, z, w = q
    u = np.array([x, y, z])
    return v + 2.0 * np.cross(u, np.cross(u, v) + w * v)


def at_frame(keys, f, rest):
    """The key value at frame f (nearest key at or before it; the rest value when the bone has no keys)."""
    if not keys:
        return np.array(rest, dtype=np.float64)
    best = keys[0][1]
    for fr, v in keys:
        if fr <= f:
            best = v
        else:
            break
    return np.array(best, dtype=np.float64)


def world_pose(rig, rb, frame):
    """{bone: world position} for frame `frame` of a read-back clip (absolute local keys) on `rig` (load_rig)."""
    n = len(rig["names"])
    wq = [None] * n
    wt = [None] * n
    for i in range(n):                                   # parents come before children in the rig
        name = rig["names"][i]
        lq = at_frame(rb["rotations"].get(name), frame, rig["q"][i])
        lq = lq / (np.linalg.norm(lq) or 1.0)
        lt = at_frame(rb["translations"].get(name), frame, rig["t"][i])
        p = rig["parents"][i]
        if p < 0:
            wq[i], wt[i] = lq, lt
        else:
            wq[i] = qmul(wq[p], lq)
            wt[i] = wt[p] + qrot(wq[p], lt)
    return {rig["names"][i]: wt[i] for i in range(n)}


def joints(names):
    return [n for n in names if JOINT_RE.search(n)]


def _side_bone(pose, side, pattern):
    rx = re.compile(rf"^{side}_({pattern})$", re.I)
    return next((n for n in pose if rx.match(n)), None)


def hands_on_thighs(pose):
    """Where each hand sits over its thigh: {side: (t, up, out)}. t is how far along the thigh (0 at the hip joint,
    1 at the knee), up the hand's height above the hip-knee line there, out how far it is to the outside of it
    (metres). The thigh's surface sits some way above that line, so compare `up` with a clip whose hands rest on the
    thighs in game (Starfield's chair Idle): a smaller `up` means the hands sink into the legs."""
    out = {}
    for side, sign in (("L", -1.0), ("R", 1.0)):
        hip, knee = _side_bone(pose, side, "thigh"), _side_bone(pose, side, "calf|knee")
        hand = _side_bone(pose, side, "wrist") or _side_bone(pose, side, "hand")
        if not (hip and knee and hand):
            continue
        a, b, h = pose[hip], pose[knee], pose[hand]
        ab = b - a
        t = float(np.clip(np.dot(h - a, ab) / (np.dot(ab, ab) or 1.0), 0.0, 1.0))
        d = h - (a + t * ab)
        out[side] = (round(t, 3) + 0.0, round(float(d[2]), 3) + 0.0, round(float(d[0]) * sign, 3) + 0.0)
    return out


def shoulders(pose):
    """Each shoulder joint (the upper arm's root, Biceps) relative to the neck joint: {side: (down, out, slope)},
    down = metres below the neck, out = metres to the side, slope = the clavicle's angle below level, degrees
    (2026-11-15, owner: "all animations seem to cause the shoulders to go down": compare with a Starfield clip)."""
    neck = next((pose[n] for n in pose if re.fullmatch(r"C_Neck", n, re.I)), None)
    out = {}
    for side in ("L", "R"):
        clav, arm = _side_bone(pose, side, "clavicle"), _side_bone(pose, side, "biceps|upperarm")
        if neck is None or not (clav and arm):
            continue
        d = pose[arm] - neck
        c = pose[arm] - pose[clav]
        slope = float(np.degrees(np.arctan2(-c[2], np.hypot(c[0], c[1]))))
        out[side] = (round(float(-d[2]), 3) + 0.0, round(float(abs(d[0])), 3) + 0.0, round(slope, 1) + 0.0)
    return out


def report(label, pose, keyed):
    pel = next((pose[n] for n in pose if re.search(r"pelvis", n, re.I)), None)
    lines = [f"== {label}"]
    for n in joints(pose):
        p = np.round(pose[n], 3) + 0.0                     # no "-0.000"
        rel = "" if pel is None else "  rel pelvis " + " ".join(f"{v:+.3f}" for v in (np.round(p - pel, 3) + 0.0))
        lines.append(f"  {n:24s} {p[0]:+.3f} {p[1]:+.3f} {p[2]:+.3f}{rel}{'' if n in keyed else '  (not keyed)'}")
    for side, (t, up, out) in hands_on_thighs(pose).items():
        lines.append(f"  hand over {side} thigh: {t:.2f} of the way to the knee, {up:+.3f} m above the hip-knee line,"
                     f" {out:+.3f} m outside it")
    for side, (down, out, slope) in shoulders(pose).items():
        lines.append(f"  {side} shoulder: {down:+.3f} m below the neck, {out:.3f} m out, clavicle {slope:+.1f} deg below level")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--calumi", required=True)
    ap.add_argument("--starfield-data", required=True, help="Starfield's Data folder (the rig, archive clips)")
    ap.add_argument("--rig", help="the .rig to read against (default: the game's human skeleton.rig)")
    ap.add_argument("--af", action="append", required=True, help=".af on disk, or an archive path")
    ap.add_argument("--frame", type=float, default=0.5, help="frame, or a fraction of the clip (< 1): default middle")
    ap.add_argument("--work", default=os.path.join(os.environ.get("TEMP", "/tmp"), "af_pose"))
    a = ap.parse_args(argv)
    import hkx_to_af
    from fo4sf import af_writer
    os.makedirs(a.work, exist_ok=True)
    rig_path = a.rig
    if not rig_path:
        name, data = hkx_to_af.starfield_find(a.starfield_data, hkx_to_af.SF_RIG_RX, ("starfield - animations",))
        if data is None:
            sys.exit("Starfield human skeleton.rig not found")
        rig_path = os.path.join(a.work, "skeleton.rig")
        with open(rig_path, "wb") as fh:
            fh.write(data)
    rig = af_writer.load_rig(a.calumi, rig_path)
    for src in a.af:
        path = src
        if not os.path.isfile(src):
            data, rel = hkx_to_af.vanilla_file(src, a.starfield_data)
            path = os.path.join(a.work, os.path.basename(rel))
            with open(path, "wb") as fh:
                fh.write(data)
        rb = af_writer.read_back(a.calumi, path, rig_path)
        f = a.frame * max(rb["frames"] - 1, 0) if a.frame < 1 else a.frame
        pose = world_pose(rig, rb, f)
        print(report(f"{src} (frame {f:.0f} of {rb['frames']}, {len(rb['bones'])} bones keyed)", pose,
                     set(rb["bones"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
