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

2026-11-15 (owner): the male player's hands go into the body for a moment as he sits down. --gaps body_profiles.json
checks every clip over all its frames: each hand's smallest distance to the body's surface and when it is inside.
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


PALM = 0.08     # metres past the wrist joint, along the forearm, where the palm's middle is (roughly)


def hand_gaps(pose, profiles):
    """{side: (gap, segment, point)}: how far each hand is outside the nearest body part's surface (metres, negative =
    inside), checked at the wrist joint and the palm (PALM past it). Body parts: bodyprofile's segments for Starfield
    (hips, belly, chest, thighs, calves, the OTHER arm), posed by their two joints in this frame; the surface radius is
    the mean around the axis at that point, so the twist of the part does not matter (a check, not the retarget's
    exact surface). 2026-11-15, owner: the hands go into the body for a moment as the (male) player sits down."""
    from fo4sf import bodyprofile as BP
    out = {}
    for side in ("L", "R"):
        wrist, fore = pose.get(f"{side}_Wrist"), pose.get(f"{side}_Forearm")
        if wrist is None or fore is None:
            continue
        d = wrist - fore
        palm = wrist + d / (np.linalg.norm(d) or 1.0) * PALM
        best = None
        for name, _sa, _sb, a_n, b_n in BP.SEGMENTS:
            if name.startswith(f"{side}_") and ("arm" in name):
                continue                                             # its own arm
            pr = profiles.get(name)
            if pr is None or a_n not in pose or b_n not in pose:
                continue
            a, b = pose[a_n], pose[b_n]
            ab = b - a
            length2 = float(ab @ ab) or 1e-12
            ring = np.asarray(pr["radius"], float).mean(axis=1)               # per t bin, mean around the axis
            for label, pt in (("wrist", wrist), ("palm", palm)):
                t = float((pt - a) @ ab / length2)
                tc = min(max(t, 0.0), 1.0)
                axis_d = float(np.linalg.norm(pt - (a + tc * ab)))
                r = float(np.interp(tc * BP.T_BINS - 0.5, np.arange(BP.T_BINS), ring))
                gap = axis_d - r if 0.0 <= t <= 1.0 else axis_d - r * 0.5   # past an end: half the radius (rounded cap)
                if best is None or gap < best[0]:
                    best = (round(gap, 3) + 0.0, name, label)
        if best is not None:
            out[side] = best
    return out


def gap_report(label, rig, rb, profiles, samples=120):
    """Lines: per hand, its smallest gap over the clip (frame, body part) and the frames where it is inside."""
    n = rb["frames"]
    frames = sorted({round(k * (n - 1) / (samples - 1)) for k in range(samples)}) if n > 1 else [0]
    rows = {"L": [], "R": []}
    for f in frames:
        for side, g in hand_gaps(world_pose(rig, rb, f), profiles).items():
            rows[side].append((f, *g))
    lines = [f"== {label}: hands against the body over {len(frames)} of {n} frames (negative = inside)"]
    for side, rs in rows.items():
        if not rs:
            continue
        f, gap, seg, pt = min(rs, key=lambda r: r[1])
        inside = [r[0] for r in rs if r[1] < 0]
        span = f"frames {inside[0]}-{inside[-1]} ({len(inside)} sampled)" if inside else "never"
        lines.append(f"  {side} hand: closest {gap:+.3f} m ({pt} at {seg}, frame {f}); inside the body: {span}")
    return lines


# the joints a stick figure needs (Starfield rig names); the dump keeps only these
DUMP_JOINTS = ("C_Hips", "C_Spine", "C_Chest", "C_Neck", "C_Head", "L_Clavicle", "R_Clavicle", "L_Biceps", "R_Biceps",
               "L_Forearm", "R_Forearm", "L_Wrist", "R_Wrist", "L_Thigh", "R_Thigh", "L_Calf", "R_Calf", "L_Foot",
               "R_Foot", "L_Toe", "R_Toe")
DUMP_BONES = (("C_Hips", "C_Spine"), ("C_Spine", "C_Chest"), ("C_Chest", "C_Neck"), ("C_Neck", "C_Head"),
              ("C_Neck", "L_Clavicle"), ("C_Neck", "R_Clavicle"), ("L_Clavicle", "L_Biceps"),
              ("R_Clavicle", "R_Biceps"), ("L_Biceps", "L_Forearm"), ("R_Biceps", "R_Forearm"),
              ("L_Forearm", "L_Wrist"), ("R_Forearm", "R_Wrist"), ("C_Hips", "L_Thigh"), ("C_Hips", "R_Thigh"),
              ("L_Thigh", "L_Calf"), ("R_Thigh", "R_Calf"), ("L_Calf", "L_Foot"), ("R_Calf", "R_Foot"),
              ("L_Foot", "L_Toe"), ("R_Foot", "R_Toe"))


def dump_clip(label, rig, rb, joints=DUMP_JOINTS):
    """{name, fps, joints, bones, frames: [[x, y, z] per joint]} of every frame (metres, 3 decimals); joints the rig
    lacks are left out."""
    n = max(int(rb.get("frames") or 1), 1)
    names = [j for j in joints if j in rig["names"]]
    frames = []
    for f in range(n):
        pose = world_pose(rig, rb, f)
        frames.append([[round(float(v), 3) + 0.0 for v in pose[j]] for j in names])
    return {"name": label, "fps": rb.get("fps") or 30, "joints": names,
            "bones": [b for b in DUMP_BONES if b[0] in names and b[1] in names], "frames": frames}


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
    ap.add_argument("--calibrate-shoulders", metavar="JSON",
                    help="with two --af (ours, then a Starfield clip doing the same thing): write the clavicle turn "
                         "that puts our shoulders where Starfield's are (retarget.shoulder_calibration), averaged over "
                         "the clips' frames; hkx_to_af / furniture_anim_pack --shoulder-calibration apply it")
    ap.add_argument("--dump", metavar="JSON",
                    help="write every frame's joint world positions of each --af (the skeleton's main joints) to JSON, "
                         "for a viewer (2026-11-15: watch a whole converted clip, not one frame)")
    ap.add_argument("--gaps", metavar="BODY_PROFILES_JSON",
                    help="body_profiles.json (scripts/armor/body_profiles.py): per clip, how close each hand comes to "
                         "the body over the whole clip and the frames where it is inside (hand_gaps)")
    a = ap.parse_args(argv)
    profiles = None
    if a.gaps:
        import json
        with open(a.gaps, encoding="utf-8") as fh:
            profiles = json.load(fh).get("starfield") or {}
    if a.calibrate_shoulders and len(a.af) != 2:
        sys.exit("--calibrate-shoulders takes exactly two --af: ours, then the Starfield reference")
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
    dirs, dumps = [], []
    for src in a.af:
        path = src
        if not os.path.isfile(src):
            data, rel = hkx_to_af.vanilla_file(src, a.starfield_data)
            path = os.path.join(a.work, os.path.basename(rel))
            with open(path, "wb") as fh:
                fh.write(data)
        rb = af_writer.read_back(a.calumi, path, rig_path)
        if a.calibrate_shoulders:
            from fo4sf import retarget
            n = rb["frames"]
            frames = sorted({round(k * (n - 1) / 39) for k in range(40)}) if n > 1 else [0]
            poses = [world_pose(rig, rb, fr) for fr in frames]
            names = list(retarget.SHOULDER_BONES.values())
            missing = [m for m in names if m not in poses[0]]
            if missing:
                sys.exit(f"{src}: no {missing} in the pose")
            dirs.append(retarget.clavicle_dirs({m: np.array([p[m] for p in poses]) for m in names}))
        if a.dump:
            dumps.append(dump_clip(src, rig, rb))
            continue
        if profiles is not None:
            print("\n".join(gap_report(src, rig, rb, profiles)))
            continue
        f = a.frame * max(rb["frames"] - 1, 0) if a.frame < 1 else a.frame
        pose = world_pose(rig, rb, f)
        print(report(f"{src} (frame {f:.0f} of {rb['frames']}, {len(rb['bones'])} bones keyed)", pose,
                     set(rb["bones"])))
    if a.dump:
        import json
        with open(a.dump, "w", encoding="utf-8") as fh:
            json.dump({"clips": dumps}, fh)
        print(f"{len(dumps)} clips, {sum(len(c['frames']) for c in dumps)} frames -> {a.dump}")
    if a.calibrate_shoulders:
        import json
        from fo4sf import retarget
        cal = retarget.shoulder_calibration(dirs[0], dirs[1])
        for side, q in cal.items():
            ang = float(np.degrees(2 * np.arccos(min(1.0, abs(q[3])))))
            print(f"shoulder calibration {side}: turn {ang:.1f} deg {q}")
        with open(a.calibrate_shoulders, "w", encoding="utf-8") as fh:
            json.dump({**cal, "ours": a.af[0], "reference": a.af[1]}, fh, indent=1)
        print("->", a.calibrate_shoulders)
    return 0


if __name__ == "__main__":
    sys.exit(main())
