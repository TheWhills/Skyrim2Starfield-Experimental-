"""Retarget a decoded Skyrim clip (skyrimhkx.decode_clip) onto the Starfield human skeleton (skeletonmap table).

Method (world-space rotation deltas): for every frame, each Skyrim bone's world rotation relative to its own rest
world rotation (the delta D = W(f) * W_rest^-1) is applied to the mapped Starfield bone's rest world rotation; Starfield
local rotations follow from the parents. Bone lengths stay Starfield's (local translations = Starfield rest), so
proportions never stretch; only COM / Root move, by the Skyrim COM's offset from rest scaled by the leg-length ratio.
The two rest poses face the same way (both A-poses, +Y forward, +Z up, left = -X; verified on BodySlide's reference
skeletons), so world deltas transfer directly.

Conventions (verified 2026-10-19): quaternions (x, y, z, w); world = parent_world * local (t rotated by the parent);
Skyrim .hkx reference pose FK reproduces the Skyrim .nif skeleton's joints within 4e-5 units; .nif rotation matrices,
used as stored (v' = R v), equal the .hkx reference quaternions within 5e-5.

SPLIT (Skyrim Spine1 -> C_Spine1 + C_Spine2): cumulative weights blend from the nearest driven ancestor's delta to the
source's. WORLD bones (WEAPON, WeaponLeft, hand IK targets): keep their rest offset from the Starfield wrist, turned by
the Skyrim source bone's delta. DERIVED / REST / unmapped: Starfield rest local transform.
"""
import math
import struct
from typing import Dict, List, Optional

import numpy as np

from . import nif, skeletonmap as M

SKYRIM_M_PER_UNIT = 0.0142875


# ------------------------------------------------------------------------------------------------- quaternions
def qmul(a, b):
    ax, ay, az, aw = np.moveaxis(a, -1, 0)
    bx, by, bz, bw = np.moveaxis(b, -1, 0)
    return np.stack([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz], axis=-1)


def qinv(q):
    return q * np.array([-1.0, -1.0, -1.0, 1.0])


def qrot(q, v):
    u, w = q[..., :3], q[..., 3:4]
    return v + 2.0 * np.cross(u, np.cross(u, v) + w * v)


def qslerp(a, b, t: float):
    d = np.sum(a * b, axis=-1, keepdims=True)
    b = np.where(d < 0, -b, b)
    d = np.abs(d)
    lin = d > 0.9995
    th = np.arccos(np.clip(d, -1.0, 1.0))
    s = np.sin(th)
    s = np.where(s == 0, 1.0, s)
    wa = np.where(lin, 1.0 - t, np.sin((1.0 - t) * th) / s)
    wb = np.where(lin, t, np.sin(t * th) / s)
    out = wa * a + wb * b
    return out / np.linalg.norm(out, axis=-1, keepdims=True)


def mat_to_quat(m) -> tuple:
    m = np.asarray(m, dtype=float).reshape(3, 3)
    tr = m.trace()
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        return ((m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s)
    i = int(np.argmax(np.diag(m)))
    if i == 0:
        s = math.sqrt(1 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        return (0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s)
    if i == 1:
        s = math.sqrt(1 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        return ((m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s)
    s = math.sqrt(1 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
    return ((m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s)


# ------------------------------------------------------------------------------------------------- rigs
class Rig:
    """names, parents (index, -1 = root; parents come before children), rest local t (B, 3) and q (B, 4)."""

    def __init__(self, names: List[str], parents: List[int], t, q):
        order = _topological(parents)
        if order != list(range(len(names))):                 # renumber so parents precede children
            remap = {old: new for new, old in enumerate(order)}
            names = [names[i] for i in order]
            parents = [remap[parents[i]] if parents[i] >= 0 else -1 for i in order]
            t = np.asarray(t, float)[order]
            q = np.asarray(q, float)[order]
        self.names, self.parents = list(names), list(parents)
        self.t, self.q = np.asarray(t, float), np.asarray(q, float)
        self.index = {n: i for i, n in enumerate(self.names)}

    def fk(self, lt, lq):
        """World (t, q) from local arrays shaped (..., B, 3) / (..., B, 4)."""
        wt, wq = np.empty_like(lt), np.empty_like(lq)
        for i, p in enumerate(self.parents):
            if p < 0:
                wt[..., i, :], wq[..., i, :] = lt[..., i, :], lq[..., i, :]
            else:
                wq[..., i, :] = qmul(wq[..., p, :], lq[..., i, :])
                wt[..., i, :] = wt[..., p, :] + qrot(wq[..., p, :], lt[..., i, :])
        return wt, wq

    def rest_world(self):
        return self.fk(self.t, self.q)


def _topological(parents):
    done, order = set(), []

    def visit(i, depth=0):
        if i in done or depth > 512:
            return
        if parents[i] >= 0:
            visit(parents[i], depth + 1)
        done.add(i)
        order.append(i)
    for i in range(len(parents)):
        visit(i)
    return order


def rig_from_hkx_skeleton(sk: dict) -> Rig:
    """A Rig from skyrimhkx.describe()["skeletons"][k] (Havok units)."""
    pose = sk["reference_pose"]
    return Rig(sk["bones"], sk["parents"], [p["t"] for p in pose], [p["q"] for p in pose])


def rig_from_nif(data: bytes, node_types=("NiNode", "BSFadeNode", "BSLeafAnimNode")) -> Rig:
    """A Rig from a skeleton NIF (units as stored: Starfield metres, Skyrim game units)."""
    f = nif.parse(data)
    nodes = [i for i in range(len(f.blocks)) if f.type_of(i) in node_types]
    parent = {}
    for i in nodes:
        for c in nif.node_children(f, i):
            parent[c] = i
    pos = {b: k for k, b in enumerate(nodes)}
    names, parents, ts, qs = [], [], [], []
    for i in nodes:
        si, = struct.unpack_from("<i", f.blocks[i], 0)
        names.append(f.strings[si].decode("latin-1") if 0 <= si < len(f.strings) else "")
        parents.append(pos[parent[i]] if i in parent and parent[i] in pos else -1)
        t, r, _s = nif._av_transform(f.blocks[i])
        ts.append(t)
        qs.append(mat_to_quat(r))
    return Rig(names, parents, ts, qs)


# ------------------------------------------------------------------------------------------------- retarget
def skyrim_locals(clip: dict, sk: Rig):
    """(F, B, 3) / (F, B, 4) Skyrim local transforms: rest everywhere, clip tracks where the clip has them."""
    F = clip["frames"]
    lt = np.repeat(sk.t[None], F, axis=0)
    lq = np.repeat(sk.q[None], F, axis=0)
    for k, name in enumerate(clip["bones"]):
        i = sk.index.get(name)
        if i is None:
            continue
        tr = clip["tracks"][k]
        lt[:, i, :] = [f[0] for f in tr]
        lq[:, i, :] = [f[1] for f in tr]
    return lt, lq


def retarget(clip: dict, sk: Rig, sf: Rig, unit: float = SKYRIM_M_PER_UNIT) -> Dict:
    """{"bones", "parents", "fps", "frames", "t" (F, B, 3) metres, "q" (F, B, 4), "world_t" (F, B, 3)} on sf."""
    lt, lq = skyrim_locals(clip, sk)
    wt_sk, wq_sk = sk.fk(lt, lq)
    rt_sk, rq_sk = sk.rest_world()
    delta = qmul(wq_sk, qinv(rq_sk)[None])                             # (F, B, 4) world delta per Skyrim bone
    F, B = lq.shape[0], len(sf.names)
    rt_sf, rq_sf = sf.rest_world()
    # which Skyrim delta drives each Starfield bone
    drive: Dict[int, list] = {}
    for a, b in M.MAP.items():
        if a in sk.index and b in sf.index:
            drive[sf.index[b]] = [("full", sk.index[a])]
    for a, parts in M.SPLIT.items():
        if a not in sk.index:
            continue
        acc = 0.0
        for b, w in parts:
            acc += w
            if b in sf.index:
                drive[sf.index[b]] = [("split", sk.index[a], acc)]
    world_src = {sf.index[b]: sk.index[a] for b, a in M.WORLD.items() if b in sf.index and a in sk.index}
    # COM movement scale: leg length (thigh joint -> ankle, both legs), so a crouch bends the knees as far as in
    # Skyrim and the feet stay on the ground (hip height overshoots: Starfield's thigh joint sits 11 cm below C_Hips)
    def leg(rig, rt, thigh, foot):
        if thigh in rig.index and foot in rig.index:
            return float(np.linalg.norm(rt[rig.index[thigh]] - rt[rig.index[foot]]))
        return None
    ls = [leg(sk, rt_sk, f"NPC {s} Thigh [{s}Thg]", f"NPC {s} Foot [{s}ft ]") for s in "LR"]
    lf = [leg(sf, rt_sf, f"{s}_Thigh", f"{s}_Foot") for s in "LR"]
    scale = (sum(lf) / (sum(ls) * unit)) if all(ls) and all(lf) else 1.0
    out_t = np.repeat(sf.t[None], F, axis=0)
    out_q = np.repeat(sf.q[None], F, axis=0)
    wt = np.zeros((F, B, 3))
    wq = np.zeros((F, B, 4))
    dsf = np.zeros((F, B, 4))                                          # Starfield world delta per bone
    dsf[..., 3] = 1.0
    for i, p in enumerate(sf.parents):
        pw_t = wt[:, p, :] if p >= 0 else np.zeros((F, 3))
        pw_q = wq[:, p, :] if p >= 0 else np.tile([0.0, 0.0, 0.0, 1.0], (F, 1))
        pd = dsf[:, p, :] if p >= 0 else np.tile([0.0, 0.0, 0.0, 1.0], (F, 1))
        rule = drive.get(i)
        target_q, target_t = None, None
        if rule and rule[0][0] == "full":
            d = delta[:, rule[0][1], :]
            target_q = qmul(d, rq_sf[i][None])
            dsf[:, i, :] = d
        elif rule and rule[0][0] == "split":
            _k, src, w = rule[0]
            d = qslerp(pd, delta[:, src, :], w)
            target_q = qmul(d, rq_sf[i][None])
            dsf[:, i, :] = d
        elif i in world_src:
            d = delta[:, world_src[i], :]
            hand = "R_Wrist" if not sf.names[i].startswith(("L_", "WeaponLeft")) else "L_Wrist"
            hi = sf.index.get(hand)
            target_q = qmul(d, rq_sf[i][None])
            if hi is not None and hi < i:
                off = rt_sf[i] - rt_sf[hi]
                target_t = wt[:, hi, :] + qrot(d, np.broadcast_to(off, (F, 3)))
            dsf[:, i, :] = d
        else:
            dsf[:, i, :] = pd
        name = sf.names[i]
        if name in ("COM", "Root") and name in M.MAP.values():
            src = sk.index[[a for a, b in M.MAP.items() if b == name][0]]
            move = (wt_sk[:, src, :] - rt_sk[src][None]) * unit * scale
            target_t = rt_sf[i][None] + move
        if target_q is not None:
            out_q[:, i, :] = qmul(qinv(pw_q), target_q)
        if target_t is not None:
            out_t[:, i, :] = qrot(qinv(pw_q), target_t - pw_t)
        wq[:, i, :] = qmul(pw_q, out_q[:, i, :])
        wt[:, i, :] = pw_t + qrot(pw_q, out_t[:, i, :])
    return {"bones": sf.names, "parents": sf.parents, "fps": clip.get("fps"), "frames": F, "t": out_t, "q": out_q,
            "world_t": wt, "height_scale": scale}


def _from_to(a, b):
    """(F, 4) quaternions turning vectors a onto b (F, 3)."""
    a = a / np.linalg.norm(a, axis=-1, keepdims=True)
    b = b / np.linalg.norm(b, axis=-1, keepdims=True)
    c = np.cross(a, b)
    d = np.sum(a * b, axis=-1, keepdims=True)
    q = np.concatenate([c, 1.0 + d], axis=-1)
    flip = (d[..., 0] < -0.999999)                                     # opposite: any perpendicular axis
    if np.any(flip):
        perp = np.cross(a[flip], np.array([1.0, 0.0, 0.0]))
        small = np.linalg.norm(perp, axis=-1) < 1e-6
        perp[small] = np.cross(a[flip][small], np.array([0.0, 1.0, 0.0]))
        q[flip] = np.concatenate([perp, np.zeros((perp.shape[0], 1))], axis=-1)
    return q / np.linalg.norm(q, axis=-1, keepdims=True)


LEGS = [("NPC L Foot [Lft ]", "L_Thigh", "L_Calf", "L_Foot"), ("NPC R Foot [Rft ]", "R_Thigh", "R_Calf", "R_Foot")]


def plant_feet(clip: dict, sk: Rig, sf: Rig, res: dict, unit: float = SKYRIM_M_PER_UNIT) -> Dict:
    """Foot planting: a two-bone IK per leg so each Starfield ankle sits as far above (or below) its own rest height as
    Skyrim's ankle does above its rest height, scaled like the COM (leg-length ratio); ankle x / y stay where the
    retarget put them, the knee keeps its bend plane, the foot keeps its world rotation. Returns res with "t", "q",
    "world_t" updated and "feet_planted": the largest ankle correction (m)."""
    lt, lq = skyrim_locals(clip, sk)
    wt_sk, _ = sk.fk(lt, lq)
    rt_sk, _ = sk.rest_world()
    rt_sf, _ = sf.rest_world()
    out_q = res["q"].copy()
    wt, wq = sf.fk(res["t"], out_q)
    scale = res.get("height_scale", 1.0)
    moved = 0.0
    for skf, th, ca, fo in LEGS:
        if not all(n in sf.index for n in (th, ca, fo)) or skf not in sk.index:
            continue
        i0, i1, i2, s = sf.index[th], sf.index[ca], sf.index[fo], sk.index[skf]
        A, B, C = wt[:, i0], wt[:, i1], wt[:, i2]
        T = C.copy()
        T[:, 2] = rt_sf[i2, 2] + (wt_sk[:, s, 2] - rt_sk[s, 2]) * unit * scale
        moved = max(moved, float(np.max(np.abs(T[:, 2] - C[:, 2]))))
        l1 = np.linalg.norm(B - A, axis=-1)
        l2 = np.linalg.norm(C - B, axis=-1)
        AT = T - A
        d = np.clip(np.linalg.norm(AT, axis=-1), np.abs(l1 - l2) + 1e-6, l1 + l2 - 1e-6)
        u = AT / np.linalg.norm(AT, axis=-1, keepdims=True)
        v = (B - A) - np.sum((B - A) * u, axis=-1, keepdims=True) * u          # knee direction off the A-T line
        vn = np.linalg.norm(v, axis=-1, keepdims=True)
        v = np.where(vn > 1e-9, v / np.where(vn > 1e-9, vn, 1.0), np.array([0.0, 1.0, 0.0]))
        cos_a = np.clip((l1 ** 2 + d ** 2 - l2 ** 2) / (2 * l1 * d), -1, 1)
        Bn = A + l1[:, None] * (cos_a[:, None] * u + np.sqrt(1 - cos_a ** 2)[:, None] * v)
        Tn = A + d[:, None] * u
        q1 = _from_to(B - A, Bn - A)
        thigh_w = qmul(q1, wq[:, i0])
        calf_vec = qrot(q1, C - B)
        q2 = _from_to(calf_vec, Tn - Bn)
        calf_w = qmul(q2, qmul(q1, wq[:, i1]))
        foot_w = wq[:, i2]                                                    # keep the foot's world rotation
        p0 = sf.parents[i0]
        parent_w = wq[:, p0] if p0 >= 0 else np.tile([0.0, 0.0, 0.0, 1.0], (len(A), 1))
        out_q[:, i0] = qmul(qinv(parent_w), thigh_w)
        # the calf / foot may hang off helper bones in between; walk up the actual parents
        def world_of(i, thigh_w=thigh_w, calf_w=calf_w):
            return {i0: thigh_w, i1: calf_w}.get(i)
        pc = sf.parents[i1]
        out_q[:, i1] = qmul(qinv(world_of(pc) if world_of(pc) is not None else wq[:, pc]), calf_w)
        pf = sf.parents[i2]
        out_q[:, i2] = qmul(qinv(world_of(pf) if world_of(pf) is not None else wq[:, pf]), foot_w)
        wt, wq = sf.fk(res["t"], out_q)
    res = dict(res)
    res["q"], res["world_t"], res["feet_planted"] = out_q, wt, round(moved, 4)
    return res


def check(clip: dict, sk: Rig, sf: Rig, res: dict, unit: float = SKYRIM_M_PER_UNIT) -> Dict:
    """Numbers that tell a good retarget from a broken one:
    segment_angle_change_deg: per mapped limb segment, how far the angle between the Skyrim and Starfield segment
      directions moves away from its rest value over the clip (0 = the limb turns exactly as in Skyrim);
    foot_lowest_m: lowest foot / toe height over the clip, Skyrim (scaled) vs Starfield (ground contact)."""
    lt, lq = skyrim_locals(clip, sk)
    wt_sk, _ = sk.fk(lt, lq)
    rt_sk, _ = sk.rest_world()
    rt_sf, _ = sf.rest_world()
    wt_sf = res["world_t"]
    segs = [("NPC L UpperArm [LUar]", "NPC L Forearm [LLar]"), ("NPC L Forearm [LLar]", "NPC L Hand [LHnd]"),
            ("NPC R UpperArm [RUar]", "NPC R Forearm [RLar]"), ("NPC R Forearm [RLar]", "NPC R Hand [RHnd]"),
            ("NPC L Thigh [LThg]", "NPC L Calf [LClf]"), ("NPC L Calf [LClf]", "NPC L Foot [Lft ]"),
            ("NPC R Thigh [RThg]", "NPC R Calf [RClf]"), ("NPC R Calf [RClf]", "NPC R Foot [Rft ]"),
            ("NPC Neck [Neck]", "NPC Head [Head]")]
    out = {}

    def ang(a, b):
        a = a / np.linalg.norm(a, axis=-1, keepdims=True)
        b = b / np.linalg.norm(b, axis=-1, keepdims=True)
        return np.degrees(np.arccos(np.clip(np.sum(a * b, axis=-1), -1, 1)))
    for a, b in segs:
        if not all(x in sk.index and M.MAP.get(x) in sf.index for x in (a, b)):
            continue
        ia, ib, ja, jb = sk.index[a], sk.index[b], sf.index[M.MAP[a]], sf.index[M.MAP[b]]
        rest = ang(rt_sk[ib] - rt_sk[ia], rt_sf[jb] - rt_sf[ja])
        cur = ang(wt_sk[:, ib] - wt_sk[:, ia], wt_sf[:, jb] - wt_sf[:, ja])
        out[f"{M.MAP[a]}->{M.MAP[b]}"] = round(float(np.max(np.abs(cur - rest))), 2)
    feet = [n for n in ("NPC L Toe0 [LToe]", "NPC R Toe0 [RToe]", "NPC L Foot [Lft ]", "NPC R Foot [Rft ]")
            if n in sk.index and M.MAP.get(n) in sf.index]
    sky = min(float(np.min(wt_sk[:, sk.index[n], 2])) for n in feet) * unit
    star = min(float(np.min(wt_sf[:, sf.index[M.MAP[n]], 2])) for n in feet)
    return {"segment_angle_change_deg": out, "foot_lowest_m": {"skyrim": round(sky, 3), "starfield": round(star, 3)}}
