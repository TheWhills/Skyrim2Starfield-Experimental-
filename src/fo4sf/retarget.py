"""Retarget a decoded Skyrim clip (skyrimhkx.decode_clip) onto the Starfield human skeleton (skeletonmap table).

Method (world-space rotation deltas): for every frame, each Skyrim bone's world rotation relative to its own rest
world rotation (the delta D = W(f) * W_rest^-1) is applied to the mapped Starfield bone's rest world rotation; Starfield
local rotations follow from the parents. Bone lengths stay Starfield's (local translations = Starfield rest), so
proportions never stretch; only COM / Root move, by the Skyrim COM's offset from rest scaled by the leg-length ratio.
The two rest poses face the same way (both A-poses, +Y forward, +Z up, left = -X; verified on BodySlide's reference
skeletons), but their limbs do not point the same way (upper arms 16 deg, fingers up to 46 deg apart, hands rolled 13.5
deg): each driven bone's Starfield rest is first swung onto the Skyrim bone's rest direction (rest_alignment; hands also
rolled by the knuckle line), so limbs point exactly where Skyrim's do (verified on 1hm_attackright: arm, forearm, hand,
finger directions within 0.02 deg every frame). The weapon is held with the vanilla Starfield grip (skeletonmap.GRIP).

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


def hold_rest_rotation(rig: "Rig", lt, lq, bones=()):
    """Locals in which the named bones keep their rest rotation relative to the root (character space) on every frame;
    every bone's world position and every other bone's world rotation are unchanged (their locals absorb the turn),
    so the pose looks the same. See skeletonmap.HOLD_REST_ROTATION."""
    lt, lq = np.asarray(lt, float), np.asarray(lq, float)
    hold = [rig.index[b] for b in bones if b in rig.index and rig.parents[rig.index[b]] >= 0]
    if not hold:
        return lt, lq
    wt, wq = rig.fk(lt, lq)
    rt, rq = rig.rest_world()
    root = next(i for i, p in enumerate(rig.parents) if p < 0)
    for i in hold:
        wq[:, i] = qmul(wq[:, root], np.broadcast_to(qmul(qinv(rq[root]), rq[i]), wq[:, root].shape))
    out_t, out_q = lt.copy(), lq.copy()
    for i, p in enumerate(rig.parents):
        if p >= 0:
            inv = qinv(wq[:, p])
            out_q[:, i] = qmul(inv, wq[:, i])
            out_t[:, i] = qrot(inv, wt[:, i] - wt[:, p])
    return out_t, out_q


def copy_world(rig: "Rig", lt, lq, pairs) -> tuple:
    """Locals in which each bone of pairs {bone: source} has the source's world transform on every frame; the bone's
    children keep their world transforms. See skeletonmap.WEAPON_FOLLOWERS."""
    lt, lq = np.asarray(lt, float), np.asarray(lq, float)
    todo = [(rig.index[b], rig.index[s]) for b, s in pairs.items() if b in rig.index and s in rig.index
            and rig.parents[rig.index[b]] >= 0]
    if not todo:
        return lt, lq
    wt, wq = rig.fk(lt, lq)
    for b, s in todo:
        wt[:, b], wq[:, b] = wt[:, s], wq[:, s]
    out_t, out_q = lt.copy(), lq.copy()
    changed = {b for b, _s in todo}
    for i, p in enumerate(rig.parents):
        if p >= 0 and (i in changed or p in changed):
            inv = qinv(wq[:, p])
            out_q[:, i] = qmul(inv, wq[:, i])
            out_t[:, i] = qrot(inv, wt[:, i] - wt[:, p])
    return out_t, out_q


def qmirror_x(q):
    """The rotation S R S for S = diag(-1, 1, 1): the same turn seen in a mirror across the YZ plane (left <-> right)."""
    return np.asarray(q, float) * np.array([1.0, -1.0, -1.0, 1.0])


def mirror_grip(t, q, right_rest_q, left_rest_q):
    """A grip (offset t, rotation q in the right hand's frame) mirrored onto the left hand: the left hand holds its
    object as the mirror image of the right hand's. The two hands' rest frames need not be mirror images of each other
    (Starfield's wrists are not: their local axes differ by a fixed turn F, L_rest = mirror(R_rest) * F, which is
    taken out). Returns (t, q) in the left hand's frame."""
    F = qmul(qinv(qmirror_x(right_rest_q)), np.asarray(left_rest_q, float))
    t_l = qrot(qinv(F), np.array(t, float) * np.array([-1.0, 1.0, 1.0]))
    q_l = qmul(qinv(F), qmirror_x(q))
    return t_l, q_l / np.linalg.norm(q_l)


def _rotation_between(a, b):
    """(F, 4) shortest rotations taking direction a onto direction b (both (F, 3))."""
    a = a / np.linalg.norm(a, axis=-1, keepdims=True)
    b = b / np.linalg.norm(b, axis=-1, keepdims=True)
    c = np.cross(a, b)
    d = np.sum(a * b, axis=-1, keepdims=True)
    q = np.concatenate([c, 1.0 + d], axis=-1)
    flip = (1.0 + d[..., 0]) < 1e-8                           # opposite: any axis perpendicular to a
    if np.any(flip):
        perp = np.cross(a[flip], np.array([1.0, 0.0, 0.0]))
        small = np.linalg.norm(perp, axis=-1) < 1e-6
        perp[small] = np.cross(a[flip][small], np.array([0.0, 1.0, 0.0]))
        q[flip] = np.concatenate([perp, np.zeros((perp.shape[0], 1))], axis=-1)
    return q / np.linalg.norm(q, axis=-1, keepdims=True)


def two_bone_ik(rig: "Rig", lt, lq, upper: str, lower: str, end: str, target):
    """Locals in which `end` (the wrist) reaches the world positions `target` (F, 3) by turning `upper` (upper arm)
    and `lower` (forearm), elbow kept in its current bend plane, the end bone's world rotation unchanged (the hand
    keeps its orientation) and every other bone untouched. Targets out of reach are approached as far as the arm goes.
    Returns (lt, lq, per-frame distance left in metres)."""
    lt, lq = np.asarray(lt, float).copy(), np.asarray(lq, float).copy()
    iu, il, ie = rig.index[upper], rig.index[lower], rig.index[end]
    wt, wq = rig.fk(lt, lq)
    a, b, c = wt[:, iu], wt[:, il], wt[:, ie]
    T = np.asarray(target, float)
    l1 = np.linalg.norm(b - a, axis=-1)
    l2 = np.linalg.norm(c - b, axis=-1)
    at = T - a
    d_raw = np.linalg.norm(at, axis=-1)
    d = np.clip(d_raw, np.abs(l1 - l2) + 1e-6, l1 + l2 - 1e-6)
    u = at / np.maximum(d_raw, 1e-9)[:, None]
    ab = b - a
    perp = ab - np.sum(ab * u, axis=-1, keepdims=True) * u          # keep the elbow on its side of the reach line
    pn = np.linalg.norm(perp, axis=-1)
    weak = pn < 1e-6
    if np.any(weak):
        alt = np.cross(u[weak], np.array([0.0, 0.0, 1.0]))
        perp[weak] = alt
        pn[weak] = np.linalg.norm(alt, axis=-1)
    perp = perp / np.maximum(pn, 1e-9)[:, None]
    x = (l1 ** 2 - l2 ** 2 + d ** 2) / (2 * d)
    h = np.sqrt(np.maximum(l1 ** 2 - x ** 2, 0.0))
    b_new = a + u * x[:, None] + perp * h[:, None]
    r1 = _rotation_between(b - a, b_new - a)
    q_upper = qmul(r1, wq[:, iu])
    c1 = a + qrot(r1, c - a)
    reach = a + u * d[:, None]
    r2 = _rotation_between(c1 - b_new, reach - b_new)
    q_lower = qmul(r2, qmul(r1, wq[:, il]))
    pu, pl = rig.parents[iu], rig.parents[il]
    pw_q = wq[:, pu] if pu >= 0 else np.tile([0.0, 0.0, 0.0, 1.0], (len(T), 1))
    lq[:, iu] = qmul(qinv(pw_q), q_upper)
    lq[:, il] = qmul(qinv(q_upper), q_lower) if pl == iu else qmul(qinv(rig.fk(lt, lq)[1][:, pl]), q_lower)
    wt2, wq2 = rig.fk(lt, lq)
    pe = rig.parents[ie]
    lq[:, ie] = qmul(qinv(wq2[:, pe]), wq[:, ie])                    # the hand keeps its world rotation
    wt3, _ = rig.fk(lt, lq)
    return lt, lq, np.linalg.norm(wt3[:, ie] - T, axis=-1)


def rehome(src: "Rig", lt, lq, names: List[str], parents: List[int], rest_t, rest_q):
    """Re-express a clip given as local (t, q) on `src` in another hierarchy (`names`, `parents`, rest locals), e.g.
    the game's skeleton.rig, whose bone order and parenting differ from the skeleton NIF's (Root at the top, twist bones
    under the limb, Weapon under C_Chest). Bones are matched by name, ignoring case (NIF WEAPON = rig Weapon); a bone
    the source lacks keeps its rest local transform under its (moving) parent. Returns local (t, q) shaped
    (F, len(names), 3 / 4). Parents must precede children."""
    wt, wq = src.fk(np.asarray(lt, float), np.asarray(lq, float))
    F = wt.shape[0]
    low = {n.lower(): i for i, n in enumerate(src.names)}
    rest_t, rest_q = np.asarray(rest_t, float), np.asarray(rest_q, float)
    D = len(names)
    ot, oq = np.empty((F, D, 3)), np.empty((F, D, 4))
    gt, gq = np.empty((F, D, 3)), np.empty((F, D, 4))
    for i, (n, p) in enumerate(zip(names, parents)):
        if p >= i:
            raise ValueError("parents must precede children")
        j = low.get(n.lower())
        if j is not None:
            gt[:, i], gq[:, i] = wt[:, j], wq[:, j]
            if p < 0:
                ot[:, i], oq[:, i] = gt[:, i], gq[:, i]
            else:
                inv = qinv(gq[:, p])
                oq[:, i] = qmul(inv, gq[:, i])
                ot[:, i] = qrot(inv, gt[:, i] - gt[:, p])
        else:
            ot[:, i], oq[:, i] = rest_t[i], rest_q[i]
            if p < 0:
                gt[:, i], gq[:, i] = ot[:, i], oq[:, i]
            else:
                gq[:, i] = qmul(gq[:, p], oq[:, i])
                gt[:, i] = gt[:, p] + qrot(gq[:, p], ot[:, i])
    return ot, oq


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
def play_speed(clip: dict, speed: float) -> dict:
    """The clip as played at `speed` (MCO_AttackSpeed 0.9 = 10 % slower): the same keys at fps * speed, duration and
    annotation times / speed. resample() then brings it to 30 fps."""
    if not speed or abs(speed - 1.0) < 1e-6:
        return clip
    fps = float(clip.get("fps") or 30.0)
    F = int(clip["frames"])
    dur = float(clip.get("duration") or 0.0) or (F - 1) / fps
    ann = [dict(a, time=float(a.get("time", 0.0)) / speed) for a in clip.get("annotations") or []]
    return dict(clip, fps=fps * speed, duration=dur / speed, annotations=ann, play_speed=speed)


def resample(clip: dict, fps: float = 30.0) -> dict:
    """The clip at `fps` (Starfield clips play at 30; Skyrim packs also ship 60 fps clips, e.g. BFCO_Attack1: 105
    frames over 1.75 s), same duration: translations / scales linear, rotations slerp. Annotations keep their times."""
    F = int(clip["frames"])
    src_fps = clip.get("fps")
    dur = float(clip.get("duration") or 0.0) or ((F - 1) / src_fps if src_fps else 0.0)
    if F < 2 or not dur or (src_fps and abs(src_fps - fps) < 0.01):
        return clip
    n = int(round(dur * fps)) + 1
    u = np.clip(np.arange(n) / fps / dur * (F - 1), 0, F - 1)
    i0 = np.minimum(np.floor(u).astype(int), F - 2)
    w = (u - i0)[:, None]
    tracks = []
    for tr in clip["tracks"]:
        t = np.array([f[0] for f in tr], float)
        q = np.array([f[1] for f in tr], float)
        sc = np.array([f[2] for f in tr], float).reshape(F, -1)
        tn = t[i0] * (1 - w) + t[i0 + 1] * w
        qn = qslerp(q[i0], q[i0 + 1], w)
        sn = sc[i0] * (1 - w) + sc[i0 + 1] * w
        tracks.append([(tuple(tn[k]), tuple(qn[k]), tuple(sn[k])) for k in range(n)])
    return dict(clip, tracks=tracks, frames=n, fps=float(fps), resampled_from=src_fps)


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


def retarget(clip: dict, sk: Rig, sf: Rig, unit: float = SKYRIM_M_PER_UNIT, weapon_in_hand: bool = False,
             left_weapon: bool = False, two_hand_grip: bool = False) -> Dict:
    """{"bones", "parents", "fps", "frames", "t" (F, B, 3) metres, "q" (F, B, 4), "world_t" (F, B, 3)} on sf.

    The weapon always sits in the fist at the vanilla grip (skeletonmap.GRIP). weapon_in_hand: also turn the gripping
    hand so that, held that way, the weapon points and faces as Skyrim's weapon node does (skeletonmap.WEAPON_AXES);
    the hand then differs from Skyrim's by a fixed ~20-30 deg, the blade not at all. Off, the hand follows Skyrim's
    hand and the blade differs by that angle instead.
    left_weapon (dual wield): WeaponLeft is held in the left fist at the mirror image of the right grip
    (skeletonmap.LEFT_GRIP) and, with weapon_in_hand, the left hand is turned so the left blade points as Skyrim's
    (the left weapon hangs rigidly off Skyrim's Shield node). Off, WeaponLeft keeps the WORLD rule.
    two_hand_grip (greatswords, battleaxes, warhammers): the left wrist is put back where Skyrim has it relative to
    the weapon on every frame (two-bone IK on the left arm), so the support hand stays on the handle; Starfield's arm
    proportions otherwise let it slide 3-6 cm (measured 2026-10-20 on Nordic Combat Animations' greatsword set)."""
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
    align = rest_alignment(sk, sf, rt_sk, rt_sf)                       # Starfield bone -> world swing onto Skyrim's rest
    low = {n.lower(): i for i, n in enumerate(sf.names)}
    grip_table = dict(M.GRIP)
    axes_table = dict(M.WEAPON_AXES)
    if left_weapon:
        grip_table.update(M.LEFT_GRIP)
        axes_table.update(M.LEFT_WEAPON_AXES)
    grips = {low[k]: (sf.index[h], np.array(t, float), np.array(q, float) / np.linalg.norm(q))
             for k, (h, t, q) in grip_table.items() if k in low and h in sf.index}
    targets = {low[k]: sf.index[h] for k, h in M.HAND_TARGETS.items() if k in low and h in sf.index}
    weapon_axes = {low[k]: (sk.index[src], np.array(q, float) / np.linalg.norm(q))
                   for k, (src, q) in axes_table.items() if k in low and src in sk.index}
    hand_follow = {}                                                   # gripping hand -> (Skyrim weapon, axes, grip q)
    if weapon_in_hand:
        for i, (h, _gt, gq) in grips.items():
            if i in weapon_axes and h < i:
                hand_follow[h] = (weapon_axes[i][0], weapon_axes[i][1], gq)
    # Hand-overs: some Skyrim clips move the weapon node out of its hand (Nordic's battleaxe power attacks swing the
    # axe with the left hand alone: the Weapon node leaves the right hand by 1.4 m). There the weapon follows Skyrim's
    # weapon node from the nearer Starfield hand instead of the grip, and the hand that let go stops aiming it.
    sk_of = {b: a for a, b in M.MAP.items()}
    sk_hands = [sk.index[n] for n in (M.SUPPORT_HAND_SKYRIM, "NPC R Hand [RHnd]") if n in sk.index]
    sf_hand_of = {sk.index[a]: sf.index[b] for a, b in M.MAP.items() if a in sk.index and b in sf.index}
    handover = {}                                                      # weapon -> (weight (F,), Skyrim weapon)
    hk_of_weapon = {}                                                  # weapon -> its Skyrim hand
    for i, (h, _gt, _gq) in grips.items():
        src = weapon_axes.get(i, (None,))[0]
        hk = sk.index.get(sk_of.get(sf.names[h], ""))
        if src is None or hk is None:
            continue
        rel_now = qrot(qinv(wq_sk[:, hk]), wt_sk[:, src] - wt_sk[:, hk])
        rel_rest = qrot(qinv(rq_sk[hk]), rt_sk[src] - rt_sk[hk])
        dev = np.linalg.norm(rel_now - rel_rest[None], axis=-1)
        u = np.clip((dev - M.HANDOVER_UNITS[0]) / (M.HANDOVER_UNITS[1] - M.HANDOVER_UNITS[0]), 0.0, 1.0)
        w = u * u * (3 - 2 * u)
        if np.any(w > 0):
            handover[i] = (w, src)
            hk_of_weapon[i] = hk
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
    # The extra world turn a hand_follow hand got (its aimed rotation against the one Skyrim's hand gives), carried to
    # the bones below it that follow Skyrim's own world deltas (the fingers): they keep their pose IN the hand.
    # Without it the left hand's dual-wield turn (~150 deg about the blade) left the fingers where Skyrim's were in the
    # world, splayed open (owner's run 2026-10-26: "the hand is still open").
    turn = np.zeros((F, B, 4))
    turn[..., 3] = 1.0
    for i, p in enumerate(sf.parents):
        pw_t = wt[:, p, :] if p >= 0 else np.zeros((F, 3))
        pw_q = wq[:, p, :] if p >= 0 else np.tile([0.0, 0.0, 0.0, 1.0], (F, 1))
        pd = dsf[:, p, :] if p >= 0 else np.tile([0.0, 0.0, 0.0, 1.0], (F, 1))
        rule = drive.get(i)
        target_q, target_t = None, None
        if i in grips and grips[i][0] < i:                             # weapon held as in vanilla clips
            h, gt, gq = grips[i]
            target_q = qmul(wq[:, h, :], np.broadcast_to(gq, (F, 4)))
            target_t = wt[:, h, :] + qrot(wq[:, h, :], np.broadcast_to(gt, (F, 3)))
            if i in handover:                                          # weapon out of its hand in Skyrim
                w, src = handover[i]
                dist = np.stack([np.linalg.norm(wt_sk[:, src] - wt_sk[:, k], axis=-1) for k in sk_hands], axis=1)
                near = np.array(sk_hands)[np.argmin(dist, axis=1)]
                anchor_sf = np.array([a if a < i else h for a in (sf_hand_of.get(k, h) for k in near)])
                near = np.where(anchor_sf == h, hk_of_weapon[i], near)     # (hands placed after the weapon: own)
                free_t = wt[np.arange(F), anchor_sf] + (wt_sk[:, src] - wt_sk[np.arange(F), near]) * unit
                aq = weapon_axes[i][1]
                free_q = qmul(wq_sk[:, src, :], np.broadcast_to(aq, (F, 4)))
                target_t = target_t + (free_t - target_t) * w[:, None]
                target_q = np.stack([qslerp(target_q[f], free_q[f], float(w[f])) for f in range(F)])
            dsf[:, i, :] = qmul(target_q, qinv(rq_sf[i])[None])
        elif i in targets and targets[i] < i:                          # IK targets on their hands
            h = targets[i]
            target_q, target_t = wq[:, h, :], wt[:, h, :]
            dsf[:, i, :] = qmul(target_q, qinv(rq_sf[i])[None])
        elif rule and rule[0][0] == "full":
            d = delta[:, rule[0][1], :]
            target_q = qmul(d, qmul(align.get(i, np.array([0.0, 0.0, 0.0, 1.0])), rq_sf[i])[None])
            if p >= 0 and i not in hand_follow:
                target_q = qmul(turn[:, p, :], target_q)
                turn[:, i, :] = turn[:, p, :]
            dsf[:, i, :] = d
        elif rule and rule[0][0] == "split":
            _k, src, w = rule[0]
            d = qslerp(pd, delta[:, src, :], w)
            target_q = qmul(d, rq_sf[i][None])
            if p >= 0 and i not in hand_follow:
                target_q = qmul(turn[:, p, :], target_q)
                turn[:, i, :] = turn[:, p, :]
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
        if i in hand_follow:                                           # hand turned so the grip aims the blade
            src, aq, gq = hand_follow[i]
            follow = qmul(qmul(wq_sk[:, src, :], np.broadcast_to(aq, (F, 4))), np.broadcast_to(qinv(gq), (F, 4)))
            w = next((hw for wi, (hw, _s) in handover.items() if grips[wi][0] == i), None)
            if w is not None and target_q is not None:                 # the hand let go: back to Skyrim's hand
                follow = np.stack([qslerp(follow[f], target_q[f], float(w[f])) for f in range(F)])
            if target_q is not None:
                turn[:, i, :] = qmul(follow, qinv(target_q))
            target_q = follow
            dsf[:, i, :] = qmul(target_q, qinv(rq_sf[i])[None])
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
    grip_report = None
    if two_hand_grip:
        out_t, out_q, wt, grip_report = _support_hand(sk, sf, out_t, out_q, wt_sk, wq_sk, unit, low, weapon_axes)
    return {"bones": sf.names, "parents": sf.parents, "fps": clip.get("fps"), "frames": F, "t": out_t, "q": out_q,
            "world_t": wt, "height_scale": scale, "two_hand_grip": grip_report}


def _support_hand(sk, sf, out_t, out_q, wt_sk, wq_sk, unit, low, weapon_axes):
    """Two-hand grip: the left wrist at Skyrim's left-hand offset from the weapon, in the weapon's frame (Skyrim
    Weapon frame -> Starfield WEAPON frame through skeletonmap.WEAPON_AXES), reached by two-bone IK on the left arm."""
    names = M.SUPPORT_ARM
    wi = low.get("weapon")
    hk, wk = sk.index.get(M.SUPPORT_HAND_SKYRIM), sk.index.get("Weapon")
    if wi is None or hk is None or wk is None or any(n not in sf.index for n in names):
        return out_t, out_q, sf.fk(out_t, out_q)[0], None
    _src, axes = weapon_axes.get(wi, (None, np.array([0.0, 0.0, 0.0, 1.0])))
    rel_u = qrot(qinv(wq_sk[:, wk]), wt_sk[:, hk] - wt_sk[:, wk])              # Skyrim weapon frame, units
    off_axis = np.sqrt(rel_u[:, 0] ** 2 + rel_u[:, 2] ** 2)                    # from the haft (+Y)
    lo, hi = M.SUPPORT_ON_GRIP_UNITS
    u = np.clip((hi - off_axis) / (hi - lo), 0.0, 1.0)
    w = u * u * (3 - 2 * u)                                                     # 1 on the grip, 0 once let go
    rel = qrot(np.broadcast_to(qinv(axes), rel_u.shape[:-1] + (4,)), rel_u * unit)   # Starfield weapon frame, m
    wt, wq = sf.fk(out_t, out_q)
    ideal = wt[:, wi] + qrot(wq[:, wi], rel)
    end = wt[:, sf.index[names[2]]]
    before = np.linalg.norm(end - ideal, axis=-1)
    target = end + (ideal - end) * w[:, None]
    out_t, out_q, left = two_bone_ik(sf, out_t, out_q, *names, target)
    wt, _ = sf.fk(out_t, out_q)
    on = w > 0.999
    return out_t, out_q, wt, {"before_m": round(float(np.max(before[on])) if on.any() else 0.0, 4),
                              "mean_before_m": round(float(np.mean(before[on])) if on.any() else 0.0, 4),
                              "after_m": round(float(np.max(left[on])) if on.any() else 0.0, 4),
                              "released_frames": int(np.sum(w < 0.001))}


def ease_out(lt, lq, frames: int):
    """The last `frames` frames re-timed so the clip comes to rest on its last pose instead of stopping dead: frame
    F-1-n+k shows the pose at time (F-1-n) + n*h(k/n), h(u) = u + u^2 - u^3 (speed unchanged where the tail starts,
    zero at the last frame; same first and last pose, same length). Skyrim attacks end mid-step (1hm_attackright's left
    foot moves 11 cm in its last frame); Skyrim's behaviour hides that, a Starfield clip end shows it as a foot that
    slides back and stops dead."""
    lt, lq = np.asarray(lt, float), np.asarray(lq, float)
    F = lt.shape[0]
    n = min(int(frames), F - 1)
    if n < 2:
        return lt, lq
    out_t, out_q = lt.copy(), lq.copy()
    a = F - 1 - n
    for k in range(1, n):
        u = k / n
        s = a + n * (u + u * u - u ** 3)
        i = min(int(np.floor(s)), F - 2)
        w = s - i
        out_t[a + k] = lt[i] * (1 - w) + lt[i + 1] * w
        out_q[a + k] = qslerp(lq[i], lq[i + 1], w)
    return out_t, out_q


def blade_peak(rig: "Rig", t, q, bone: str = "Weapon", tip=(0.0, 0.0, 0.6)) -> Optional[int]:
    """Frame where the weapon tip moves fastest (k: between frames k and k + 1), or None without the bone. On the
    vanilla one-handed attacks this is the HitFrame within 1 frame in 39 of 41 clips, 2-3 frames in the other two
    (verified 2026-10-19; Starfield blades run along Weapon +Z), so it stands in for the hit frame Skyrim keeps in
    its behaviour graph rather than in the clip."""
    if bone not in rig.index or len(t) < 2:
        return None
    wt, wq = rig.fk(np.asarray(t, float), np.asarray(q, float))
    i = rig.index[bone]
    tips = wt[:, i] + qrot(wq[:, i], np.broadcast_to(np.asarray(tip, float), (len(wt), 3)))
    return int(np.argmax(np.linalg.norm(np.diff(tips, axis=0), axis=1)))


def rest_alignment(sk: "Rig", sf: "Rig", rt_sk=None, rt_sf=None, unit: float = SKYRIM_M_PER_UNIT) -> Dict[int, np.ndarray]:
    """Per driven Starfield bone, the world rotation (swing only) that turns its rest direction (to its mapped child)
    onto the Skyrim bone's rest direction. The two rest poses differ more than first assumed (measured 2026-10-19 on
    BodySlide's skeletons: upper arms 16 deg, clavicles 37 deg, finger joints 11-46 deg), so plain world deltas left
    arms and fingers consistently off (owner, in game: stiff arms, sword not in the fist); with the swing applied to
    the Starfield rest the bone points where the Skyrim bone points. Bones with several mapped children use
    skeletonmap.DIRECTION_CHILD; the trunk (NO_ALIGN) stays as it is."""
    if rt_sk is None:
        rt_sk, _ = sk.rest_world()
    if rt_sf is None:
        rt_sf, _ = sf.rest_world()
    out = {}
    for a, b in M.MAP.items():
        if a in M.NO_ALIGN or a not in sk.index or b not in sf.index:
            continue
        c = M.DIRECTION_CHILD.get(a)
        if c is None:
            kids = [n for n in sk.names if sk.parents[sk.index[n]] == sk.index[a] and M.MAP.get(n) in sf.index]
            if len(kids) != 1:
                continue
            c = kids[0]
        if c not in sk.index or M.MAP.get(c) not in sf.index:
            continue
        v_sk = rt_sk[sk.index[c]] - rt_sk[sk.index[a]]
        v_sf = rt_sf[sf.index[M.MAP[c]]] - rt_sf[sf.index[b]]
        if np.linalg.norm(v_sk) < 1e-9 or np.linalg.norm(v_sf) < 1e-9:
            continue
        swing = _from_to(v_sf[None], v_sk[None])[0]
        ref = M.ROLL_REF.get(a)
        if ref and all(r in sk.index and M.MAP.get(r) in sf.index for r in ref):
            axis = v_sk / np.linalg.norm(v_sk)
            u_sk = rt_sk[sk.index[ref[1]]] - rt_sk[sk.index[ref[0]]]
            u_sf = qrot(swing, rt_sf[sf.index[M.MAP[ref[1]]]] - rt_sf[sf.index[M.MAP[ref[0]]]])
            u_sk, u_sf = u_sk - axis * np.dot(u_sk, axis), u_sf - axis * np.dot(u_sf, axis)
            if np.linalg.norm(u_sk) > 1e-9 and np.linalg.norm(u_sf) > 1e-9:
                twist = _from_to(u_sf[None], u_sk[None])[0]           # both lie in the plane normal to the axis
                swing = qmul(twist, swing)
        out[sf.index[b]] = swing
    # leaves (finger tips, toes) take their parent's swing, so a corrected curl carries on to the tip
    for a, b in M.MAP.items():
        if a in M.NO_ALIGN or a not in sk.index or b not in sf.index or sf.index[b] in out:
            continue
        pa = sk.parents[sk.index[a]]
        pb = M.MAP.get(sk.names[pa]) if pa >= 0 else None
        if pb in sf.index and sf.index[pb] in out:
            out[sf.index[b]] = out[sf.index[pb]]
    return out


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
