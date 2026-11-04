"""Skyrim HDT-SMP hair / wig -> Starfield: the visible mesh re-rigged onto Starfield's head (and chest) bones plus the
hair's simulated bone chains, and the chains' physics as Starfield cloth (src/fo4sf/smpcloth.py).

Placement (measured 2026-10-27, Skyrim SE male head vs Starfield male head, cranium points above the head bone,
similarity ICP without rotation, fo4sf.facefit.align_heads; rms 6.7 mm): Skyrim and Starfield model space share axes
(+Y forward, +Z up, +X the character's right: the toes and right foot of both reference skeletons), Skyrim units are
0.0142875 m, and a Skyrim skull is 0.93 x a Starfield one. So a point maps relative to the head bones:
    p_sf = C_Head_sf + HEAD_OFFSET + HEAD_SCALE * (p_sky * UNIT - NPC_Head_sky * UNIT)
Rotations carry over unchanged (same axes); the cloth skeleton's C_Head (the template's, i.e. the game's) is the
anchor. Female heads were not measured (supported hypothesis: the same ratio; both games' reference skeletons put the
female head bone where the male's is). --head-scale / --head-offset tune it.

SMP -> bones: bones the config simulates (mass > 0) become new Starfield bones (S2S_<name>) driven by the cloth;
kinematic chain roots (mass 0, hanging off the head) merge into their human host bone, as do any other non-skeleton
bones; human bones map by fo4sf.skeletonmap (first target of a split bone).
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import nif as nifmod
from . import skeletonmap, skyrimnif, skyrimskin, smpcloth
from . import smpconfig as smp

UNIT = 0.0142875
HEAD_SCALE = 0.9303
HEAD_OFFSET = (0.0001, -0.0199, -0.0051)
SKY_HEAD = "NPC Head [Head]"
SF_HEAD = "C_Head"
MAX_WEIGHTS = 4


class HairError(ValueError):
    pass


def bone_name(skyrim_name: str) -> str:
    """Starfield name of a simulated hair bone: S2S_ + the Skyrim name with runs of other characters as _."""
    return "S2S_" + re.sub(r"[^A-Za-z0-9]+", "_", skyrim_name).strip("_")


def node_worlds(n: nifmod.NifFile) -> Tuple[Dict[str, np.ndarray], Dict[str, str]]:
    """({node name: 4x4 world in Skyrim units}, {node name: parent node name})."""
    world = nifmod.world_transforms(n)
    names, parent = {}, {}
    for i in range(len(n.blocks)):
        if n.type_of(i).endswith("Node"):
            nm = skyrimnif._name(n, n.blocks[i])
            nm = nm.decode("latin-1") if isinstance(nm, bytes) else nm
            if nm:
                names[i] = nm
    for i in names:
        try:
            for c in nifmod.node_children(n, i):
                if c in names:
                    parent.setdefault(names[c], names[i])
        except Exception:                                          # noqa: BLE001 (odd block layouts: no parent)
            pass
    out = {}
    for i, nm in names.items():
        t, r, s = world(i)
        m = np.eye(4)
        m[:3, :3] = np.array(r, float).reshape(3, 3) * s
        m[:3, 3] = t
        out.setdefault(nm, m)
    return out, parent


@dataclass
class Placement:
    scale: float = HEAD_SCALE
    offset: Tuple[float, float, float] = HEAD_OFFSET
    sky_head: np.ndarray = field(default_factory=lambda: np.zeros(3))      # metres
    sf_head: np.ndarray = field(default_factory=lambda: np.zeros(3))

    def point(self, p_units) -> np.ndarray:
        return self.sf_head + np.array(self.offset) + self.scale * (np.asarray(p_units, float) * UNIT - self.sky_head)


@dataclass
class HairShape:
    name: bytes
    positions: np.ndarray            # (n, 3) Starfield model space, metres
    normals: np.ndarray
    tangents: np.ndarray
    uvs: list
    triangles: list
    weights: List[List[Tuple[str, float]]]      # per vertex, Starfield bone names
    shader_ref: int
    alpha_ref: int
    block: int


@dataclass
class Hair:
    shapes: List[HairShape]
    bones: List[smpcloth.ChainBone]
    host_of_root: Dict[str, str]
    report: Dict


def _limit(cfg: Dict, child: str, parent: str) -> float:
    """Largest angular limit (rad) of the constraints between a bone and its parent; free axes count as pi."""
    best = None
    for c in cfg["constraints"]:
        if {c["a"], c["b"]} != {child, parent}:
            continue
        lo, hi = c.get("angularLowerLimit"), c.get("angularUpperLimit")
        if lo is None or hi is None:
            if c["type"] == "conetwist-constraint":
                v = max(float(c.get("swingSpan1", 0.5) or 0.5), float(c.get("swingSpan2", 0.5) or 0.5))
            else:
                v = 0.5
        else:
            v = max(np.pi if a > b else max(abs(a), abs(b)) for a, b in zip(lo, hi))
        best = v if best is None else max(best, v)
    return 0.5 if best is None else float(best)


def _bind_world(s, k: int) -> np.ndarray:
    """A skin bone's world transform at bind time (Skyrim units, model space): inverse(bind @ skin transform), the
    frame the vertices were skinned in (NiSkinData: bind = skin -> bone, skin transform = model -> skin)."""
    def m4(t):
        m = np.eye(4)
        m[:3, :3] = np.array(t.rotation, float).reshape(3, 3) * t.scale
        m[:3, 3] = t.translation
        return m
    skin = m4(s.skin_transform) if s.skin_transform is not None else np.eye(4)
    return np.linalg.inv(m4(s.binds[k]) @ skin)


def skin_to_model(s):
    """(point map, direction map) from a Skyrim skinned shape's vertex space to model space (units): the inverse of
    its NiSkinData overall transform (identity without one). Vertices of skinned shapes are stored in skin space."""
    st = s.skin_transform
    if st is None:
        ident = lambda v: np.asarray(v, float)
        return ident, ident
    rs, ts = np.array(st.rotation, float).reshape(3, 3), np.array(st.translation, float)
    return (lambda v: ((np.asarray(v, float) - ts) @ rs) / st.scale), (lambda v: np.asarray(v, float) @ rs)


def head_anchor(n: nifmod.NifFile, nodes: Dict[str, np.ndarray]) -> np.ndarray:
    """Where the Skyrim head bone was when the mesh was skinned (units): from a shape's skin bind when one is skinned
    to it, else the NIF's node; 4x4. The nodes need not agree: in KS Amor / Kikyo the whole node tree sits 3.3 units
    above and 2.5 behind the skinning frame (verified 2026-10-27: every bone's bind equals its node re-anchored at the
    bind head), and the game draws vertices in the bind frame, so the bind is the truth."""
    for s in skyrimskin.skinned_shapes(n):
        names = [b.decode("latin-1") if isinstance(b, bytes) else b for b in s.bones]
        if SKY_HEAD in names and len(s.binds) == len(names):
            return _bind_world(s, names.index(SKY_HEAD))
    if SKY_HEAD in nodes:
        return nodes[SKY_HEAD]
    raise HairError(f"no {SKY_HEAD} in the hair NIF (neither a skin bone nor a node)")


def convert(nif_bytes: bytes, smp_bytes: Optional[bytes], sf_world: Dict[str, np.ndarray],
            scale: float = HEAD_SCALE, offset=HEAD_OFFSET) -> Hair:
    """sf_world: Starfield rest world transforms by bone name (the cloth template's skeleton, smpcloth.skeleton_world,
    or the game's skeleton). smp_bytes None: no physics (a vanilla Skyrim hair: rigid on its head / neck bones)."""
    n = nifmod.parse(nif_bytes)
    cfg = smp.parse(smp_bytes) if smp_bytes else {"bones": {}, "constraints": []}
    nodes, parent = node_worlds(n)
    if SF_HEAD not in sf_world:
        raise HairError(f"no {SF_HEAD} in the Starfield skeleton")
    anchor = head_anchor(n, nodes)
    if SKY_HEAD in nodes:                              # the node tree into the skinning frame (see head_anchor)
        corr = anchor @ np.linalg.inv(nodes[SKY_HEAD])
        nodes = {k: corr @ m for k, m in nodes.items()}
    place = Placement(scale, tuple(offset), anchor[:3, 3] * UNIT, sf_world[SF_HEAD][:3, 3])
    dynamic = {b for b, p in cfg["bones"].items() if p.get("dynamic") and b in nodes}
    report = {"config_dynamic_bones": sorted(b for b, p in cfg["bones"].items() if p.get("dynamic")),
              "missing_in_nif": sorted(b for b, p in cfg["bones"].items() if p.get("dynamic") and b not in nodes)}

    def host(sky: str, depth: int = 0) -> Optional[str]:
        """The Starfield skeleton bone a non-simulated Skyrim bone follows."""
        hits = skeletonmap.starfield_of(sky)
        for name, _w in sorted(hits, key=lambda x: -x[1]):
            if name in sf_world:
                return name
        p = parent.get(sky)
        if p is None or depth > 64:
            return None
        return host(p, depth + 1)

    def target(sky: str) -> Optional[str]:
        return bone_name(sky) if sky in dynamic else host(sky)

    # chain bones: rotation as in Skyrim (same axes), position placed, parent = chain bone or the host
    bones, host_of_root = [], {}
    for b in sorted(dynamic, key=lambda x: (x.count(" "), x)):
        w = nodes[b]
        r = w[:3, :3] / np.maximum(np.linalg.norm(w[:3, :3], axis=0), 1e-9)
        m = np.eye(4)
        m[:3, :3] = r
        m[:3, 3] = place.point(w[:3, 3])
        p = parent.get(b)
        if p in dynamic:
            par = bone_name(p)
        else:
            par = host(p) if p else None
            if par is None:
                raise HairError(f"simulated bone {b}: no host bone above it")
            host_of_root[bone_name(b)] = par
        props = cfg["bones"][b]
        bones.append(smpcloth.ChainBone(bone_name(b), par, m, float(props.get("mass", 0.2) or 0.2),
                                        _limit(cfg, b, p) if p else 0.5))
    # visible geometry
    shapes = []
    unmapped = set()
    for s in skyrimskin.skinned_shapes(n):
        to_model, rot = skin_to_model(s)
        pos = np.array([place.point(to_model(v)) for v in s.positions])
        nrm = np.array([rot(v) for v in s.normals]) if s.normals else np.zeros((0, 3))
        tan = np.array([rot(v) for v in s.tangents]) if s.tangents else np.zeros((0, 3))
        sc = np.broadcast_to(np.asarray(place.scale, float), (3,))
        if len(nrm) and not np.allclose(sc, sc[0]):        # a per-axis scale: normals by 1/s, tangents by s
            nrm = nrm / sc
            nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
            if len(tan):
                tan = tan * sc
                tan /= np.maximum(np.linalg.norm(tan, axis=1, keepdims=True), 1e-12)
        names = [b.decode("latin-1") if isinstance(b, bytes) else b for b in s.bones]
        tgt = []
        for nm in names:
            t = target(nm)
            if t is None:
                unmapped.add(nm)
            tgt.append(t)
        ws = []
        for vw in s.weights:
            acc: Dict[str, float] = {}
            for bi, w in vw:
                t = tgt[bi] if 0 <= bi < len(tgt) else None
                if t is not None and w > 0:
                    acc[t] = acc.get(t, 0.0) + w
            if not acc:
                acc = {SF_HEAD: 1.0}
            top = sorted(acc.items(), key=lambda kv: -kv[1])[:MAX_WEIGHTS]
            tot = sum(w for _b, w in top)
            ws.append([(b, w / tot) for b, w in top])
        shapes.append(HairShape(s.name, pos, nrm, tan, list(s.uvs), [tuple(t) for t in s.triangles], ws,
                                s.shader_ref, s.alpha_ref, s.block))
    if unmapped:
        report["unmapped_bones_to_head"] = sorted(unmapped)
    # tips of chain ends: as far along the last bone as the vertices that follow it reach
    kids = {b.parent for b in bones}
    for b in bones:
        if b.name in kids:
            continue
        o = b.world[:3, 3]
        par = next((x for x in bones if x.name == b.parent), None)
        pts = [sh.positions[i] for sh in shapes for i, vw in enumerate(sh.weights)
               if any(nm == b.name and w >= 0.5 for nm, w in vw)]
        if par is not None:
            d = o - par.world[:3, 3]
        elif pts:
            d = np.mean(pts, axis=0) - o
        else:
            d = np.array([0.0, 0.0, -1.0])
        d = d / (np.linalg.norm(d) or 1.0)
        reach = max([float((p - o) @ d) for p in pts] + [0.0])
        default = float(np.linalg.norm(o - par.world[:3, 3])) if par is not None else 0.05
        b.tip = o + d * max(reach, 0.5 * default, 0.01)
    report.update(chain_bones=[b.name for b in bones], hosts=sorted(set(host_of_root.values())),
                  shapes=[s.name.decode("latin-1") for s in shapes],
                  vertices=sum(len(s.positions) for s in shapes),
                  placement={"scale": scale, "offset": list(offset)})
    return Hair(shapes, bones, host_of_root, report)


def fit_head(sky_points: np.ndarray, sky_head: np.ndarray, sf_points: np.ndarray,
             sf_head: np.ndarray) -> Tuple[float, Tuple[float, float, float], float]:
    """(HEAD_SCALE, HEAD_OFFSET, rms m) for one pair of base heads, measured as the male constants were: the cranium
    (points above each head bone) of the Skyrim head (units, model space; sky_head its head bone 4x4 in units) fitted
    onto the Starfield head (metres; sf_head C_Head 4x4) by a similarity without rotation (fo4sf.facefit.align_heads),
    both relative to their head bones: p_sf - C_Head = scale * (p_sky - head_sky) * UNIT + offset."""
    from . import facefit
    q = (np.asarray(sky_points, float) - np.asarray(sky_head, float)[:3, 3]) * UNIT
    r = np.asarray(sf_points, float) - np.asarray(sf_head, float)[:3, 3]
    q, r = q[q[:, 2] > 0.0], r[r[:, 2] > 0.0]
    if len(q) < 50 or len(r) < 50:
        raise HairError(f"too few cranium points to fit ({len(q)} Skyrim, {len(r)} Starfield)")
    s, _R, t, rms = facefit.align_heads(q, r, rotate=False)
    return float(s), tuple(float(x) for x in t), float(rms)


def fit_head_axes(sky_points: np.ndarray, sky_head: np.ndarray, sf_points: np.ndarray, sf_head: np.ndarray,
                  iters: int = 30) -> Tuple[Tuple[float, float, float], Tuple[float, float, float], float]:
    """As fit_head but with a scale per model axis (width X, depth Y, height Z): the skulls differ in proportions, not
    only size (2026-11-02: after the uniform fit the owner saw the wigs too wide). Starts from the uniform fit, then
    alternates closest points both ways (as facefit.align_heads) with a least-squares scale and shift per axis."""
    from . import facefit
    s0, t0, _rms = fit_head(sky_points, sky_head, sf_points, sf_head)
    q = (np.asarray(sky_points, float) - np.asarray(sky_head, float)[:3, 3]) * UNIT
    r = np.asarray(sf_points, float) - np.asarray(sf_head, float)[:3, 3]
    q, r = q[q[:, 2] > 0.0], r[r[:, 2] > 0.0]
    sc, t = np.full(3, s0), np.asarray(t0, float)
    rms = float("inf")
    for _ in range(iters):
        moved = q * sc + t
        j, d = facefit._nearest(r, moved, 1)            # each Skyrim point -> its nearest Starfield point
        i, e = facefit._nearest(moved, r, 1)            # each Starfield point -> its nearest Skyrim point
        a = np.concatenate([q, q[i[:, 0]]])
        b = np.concatenate([r[j[:, 0]], r])
        for k in range(3):
            ak, bk = a[:, k] - a[:, k].mean(), b[:, k] - b[:, k].mean()
            sc[k] = float(np.sum(ak * bk) / np.sum(ak * ak))
            t[k] = float(b[:, k].mean() - sc[k] * a[:, k].mean())
        new = float(np.sqrt((np.sum(d ** 2) + np.sum(e ** 2)) / (len(d) + len(e))))
        if abs(rms - new) < 1e-7:
            rms = new
            break
        rms = new
    moved = q * sc + t
    _j, d = facefit._nearest(r, moved, 1)
    _i, e = facefit._nearest(moved, r, 1)
    rms = float(np.sqrt((np.sum(d ** 2) + np.sum(e ** 2)) / (len(d) + len(e))))
    return tuple(float(x) for x in sc), tuple(float(x) for x in t), rms


def nearest_surface(points: np.ndarray, head_pts: np.ndarray, head_nrm: np.ndarray, chunk: int = 512):
    """(signed depth, distance, nearest index) of each point against a head surface given as vertices with outward
    normals: depth = (p - nearest) . normal (negative = inside)."""
    points = np.asarray(points, float)
    hp = np.asarray(head_pts, float)
    hh = (hp * hp).sum(1)
    depth, dist, idx = np.empty(len(points)), np.empty(len(points)), np.empty(len(points), int)
    for c in range(0, len(points), chunk):
        p = points[c:c + chunk]
        d2 = (p * p).sum(1)[:, None] + hh[None, :] - 2.0 * p @ hp.T
        j = np.argmin(d2, axis=1)
        idx[c:c + chunk] = j
        dist[c:c + chunk] = np.sqrt(np.maximum(d2[np.arange(len(p)), j], 0.0))
        depth[c:c + chunk] = np.einsum("ij,ij->i", p - hp[j], np.asarray(head_nrm, float)[j])
    return depth, dist, idx


def judged(points: np.ndarray, head_pts: np.ndarray, dist: np.ndarray, reach: float = 0.03) -> np.ndarray:
    """Points the nearest-vertex test can judge: within `reach` of the head and above its lowest 2 cm (the head mesh
    ends at the neck; hair hanging below it would be judged against the cut edge)."""
    return (dist < reach) & (np.asarray(points, float)[:, 2] > float(np.min(np.asarray(head_pts)[:, 2])) + 0.02)


FOLLOW_SIGMA = 0.02          # m: follow_head's averaging: wide enough that the face's small hollows and ridges (eye
                            # socket, temple, brow ridge) are not printed into hanging strands (2026-11-02: 8 mm made
                            # the temple strand dip and bump in the owner's viewer; Skyrim's is one smooth strand)


def follow_head(hair: Hair, sky_pts: np.ndarray, head_pts: np.ndarray, head_nrm: np.ndarray, near: float = 0.03,
                far: float = 0.08, sigma: float = FOLLOW_SIGMA, chunk: int = 256) -> Tuple[Hair, Dict]:
    """The wig moved with the difference between the two skulls: KS made it to sit on Skyrim's female head
    (`sky_pts`, already placed on Starfield's by the head fit), and every point near that head moves the way the
    Skyrim head's surface around it must move to lie on Starfield's (`head_pts` / `head_nrm`): out where Starfield's
    brow / forehead stands further out, in where it lies further in. So the hair keeps the height above the skin it
    had in Skyrim, and its curve over the forehead follows Starfield's forehead instead of being pushed out only
    where it would clip (2026-11-02: owner saw Anna's hair go down over the forehead and then bump over the brow).
    Each Skyrim head point's move is along the nearest Starfield normal; a hair point takes a Gaussian (`sigma` m)
    average of the moves of the Skyrim head points around it, in full within `near` m of that head and fading to
    nothing at `far` (hanging hair below stays). push_out still runs after it for what is left."""
    sky = np.asarray(sky_pts, float)
    hn = np.asarray(head_nrm, float)
    d_sky, dist_sky, j_sky = nearest_surface(sky, head_pts, head_nrm)
    use = judged(sky, head_pts, dist_sky)
    sky, move = sky[use], (-d_sky[use])[:, None] * hn[j_sky[use]]
    if not len(sky):
        return hair, {"vertices_moved": 0}
    ss = (sky * sky).sum(1)
    shapes, moved, largest = [], 0, 0.0
    for sh in hair.shapes:
        pos = np.asarray(sh.positions, float)
        out = np.zeros_like(pos)
        for c in range(0, len(pos), chunk):
            p = pos[c:c + chunk]
            d2 = np.maximum((p * p).sum(1)[:, None] + ss[None, :] - 2.0 * p @ sky.T, 0.0)
            r = np.sqrt(d2.min(axis=1))
            w = np.exp(-(d2 - d2.min(axis=1, keepdims=True)) / (2.0 * sigma * sigma))   # relative to the nearest
            avg = (w @ move) / np.maximum(w.sum(axis=1, keepdims=True), 1e-12)
            out[c:c + chunk] = avg * (1.0 - _smooth((r - near) / (far - near)))[:, None]
        size = np.linalg.norm(out, axis=1)
        moved += int((size > 1e-4).sum())
        largest = max(largest, float(size.max()) if len(size) else 0.0)
        shapes.append(HairShape(sh.name, pos + out, sh.normals, sh.tangents, sh.uvs, sh.triangles, sh.weights,
                                sh.shader_ref, sh.alpha_ref, sh.block))
    return (Hair(shapes, hair.bones, hair.host_of_root, dict(hair.report, followed_head=True)),
            {"vertices_moved": moved, "largest_mm": round(1000 * largest, 1),
             "skull_difference_mm": {"out_max": round(1000 * float(-d_sky[use].min()), 1),
                                     "in_max": round(1000 * float(d_sky[use].max()), 1)}})


DRAPE_RADIUS = 0.05         # m: dips in the hair narrower than about this are bridged by drape() (30 mm left
                            # a shallow wave at eye level in the owner's viewer; 50 looked smooth, 2026-11-02)


def _disc_op(grid: np.ndarray, el_deg: np.ndarray, cell: float, radius_deg: float, op) -> np.ndarray:
    """max / min (op) of a (rows = elevation, cols = azimuth, wrapping) grid over a disc of `radius_deg` angular
    radius around every cell, NaN cells left out (NaN where the disc holds none)."""
    fill = -np.inf if op is np.fmax else np.inf
    g = np.where(np.isnan(grid), fill, grid)
    out = np.full_like(g, fill)
    k = int(np.ceil(radius_deg / cell))
    cos_el = np.maximum(np.cos(np.radians(np.minimum(np.abs(el_deg), 75.0))), 0.25)
    kx = int(np.ceil(k / cos_el.min()))
    nrow = len(el_deg)
    for dy in range(-k, k + 1):
        shifted_rows = np.full_like(g, fill)
        if dy >= 0:
            shifted_rows[:nrow - dy] = g[dy:]
        else:
            shifted_rows[-dy:] = g[:nrow + dy]
        for dx in range(-kx, kx + 1):
            inside = np.hypot(dx * cell * cos_el, dy * cell) <= radius_deg
            if not inside.any():
                continue
            cand = np.roll(shifted_rows, -dx, axis=1)
            out = np.where(inside[:, None], op(out, cand), out)
    return np.where(np.isinf(out), np.nan, out)


def _sphere_centre(pts: np.ndarray) -> np.ndarray:
    """Least-squares sphere centre of points (|p|^2 = 2 p.c + k, linear)."""
    p = np.asarray(pts, float)
    A = np.hstack([2.0 * p, np.ones((len(p), 1))])
    sol, *_ = np.linalg.lstsq(A, (p * p).sum(1), rcond=None)
    return sol[:3]


def drape(hair: Hair, head_pts: np.ndarray, head_nrm: np.ndarray, head: np.ndarray, radius: float = DRAPE_RADIUS,
          cell: float = 1.5, near: float = 0.03, far: float = 0.06, lowest: float = -35.0,
          zone_az=(75.0, 95.0), zone_el=(45.0, 60.0), keep=None) -> Tuple[Hair, Dict]:
    """Hair over a hollow of the head bridged instead of sinking into it: the wig's outer surface (largest distance
    from the cranium's centre per `cell`-degree direction) is closed (largest within `radius`, then smallest within
    `radius`: a morphological closing, which only ever raises), the rise smoothed and every point near the head moved
    out along its direction by it (full within `near` m of the head, none beyond `far`; directions below `lowest`
    degrees elevation and the 'Hairline' scalp tint left alone). Only the front and the temples: full within
    zone_az[0] degrees of the front fading out by zone_az[1] (the ears, where hair tucks behind them, and the back stay
    as they are) and below zone_el[0] degrees elevation fading out by zone_el[1] (the parting on top stays). Never
    moves a point in. 2026-11-02: owner's viewer,
    Anna's temple strand went in over the temple hollow and out over the brow; he drew the path he wants, one smooth
    convex arc from the crown past the brow."""
    keep = TINT_SHAPES if keep is None else keep
    h = np.asarray(head, float)[:3, 3]
    hp = np.asarray(head_pts, float)
    cranium = hp[hp[:, 2] > h[2] + 0.05]
    centre = _sphere_centre(cranium) if len(cranium) >= 4 else h    # radii from it vary little over the skull
    nrows = int(np.ceil((90.0 - lowest) / cell)) + 1
    ncols = int(round(360.0 / cell))
    el_axis = lowest + cell * np.arange(nrows)
    per, outer = [], np.full((nrows, ncols), np.nan)
    for sh in hair.shapes:
        pos = np.asarray(sh.positions, float)
        rel = pos - centre
        r = np.linalg.norm(rel, axis=1)
        el = np.degrees(np.arcsin(np.clip(rel[:, 2] / np.maximum(r, 1e-9), -1, 1)))
        az = np.degrees(np.arctan2(rel[:, 0], rel[:, 1])) % 360.0
        _d, dist, _j = nearest_surface(pos, head_pts, head_nrm)
        fade = 1.0 - _smooth((dist - near) / (far - near))
        tint = any(k in (sh.name or b"").lower() for k in keep)
        use = (el >= lowest) & (fade > 0) & (not tint)
        row = np.clip(np.rint((el - lowest) / cell).astype(int), 0, nrows - 1)
        col = np.rint(az / cell).astype(int) % ncols
        if use.any():
            sel = use & (dist < near)                    # the outer surface: hair lying on / by the head
            if sel.any():
                flat = np.full(nrows * ncols, -np.inf)
                np.maximum.at(flat, row[sel] * ncols + col[sel], r[sel])
                flat = flat.reshape(nrows, ncols)
                outer = np.where(np.isfinite(flat), np.fmax(outer, flat), outer)
        per.append((pos, rel, r, el, az, fade, use))
    if np.all(np.isnan(outer)):
        return hair, {"vertices_moved": 0}
    rad_deg = np.degrees(radius / max(float(np.nanmedian(outer)), 1e-3))
    closed = _disc_op(_disc_op(outer, el_axis, cell, rad_deg, np.fmax), el_axis, cell, rad_deg, np.fmin)
    known = ~(np.isnan(outer) | np.isnan(closed))
    rise = np.where(known, np.maximum(np.nan_to_num(closed) - np.nan_to_num(outer), 0.0), 0.0)
    weight = known.astype(float)

    def blur(g):                                         # [1 2 1] / 4 both ways
        g = (np.roll(g, 1, 1) + 2 * g + np.roll(g, -1, 1)) / 4.0
        return (np.vstack([g[:1], g[:-1]]) + 2 * g + np.vstack([g[1:], g[-1:]])) / 4.0
    for _ in range(3):                                   # smoothed over the cells that hold hair (normalised:
        rise, weight = blur(rise * weight), blur(weight)  # the empty cells between points neither dilute it
        rise = np.where(weight > 1e-6, rise / np.maximum(weight, 1e-6), 0.0)   # nor pull it to zero)
        weight = (weight > 1e-6).astype(float)
    shapes, moved, largest = [], 0, 0.0
    for sh, (pos, rel, r, el, az, fade, use) in zip(hair.shapes, per):
        fr = np.clip((el - lowest) / cell, 0, nrows - 1)
        fc = az / cell
        r0, c0 = np.floor(fr).astype(int), np.floor(fc).astype(int)
        r1, c1 = np.minimum(r0 + 1, nrows - 1), c0 + 1
        tr, tc = fr - r0, fc - c0
        c0, c1 = c0 % ncols, c1 % ncols
        val = ((1 - tr) * (1 - tc) * rise[r0, c0] + (1 - tr) * tc * rise[r0, c1]
               + tr * (1 - tc) * rise[r1, c0] + tr * tc * rise[r1, c1])
        side = np.minimum(az, 360.0 - az)                 # degrees from the front
        zone = _smooth((zone_az[1] - side) / (zone_az[1] - zone_az[0])) * \
            _smooth((zone_el[1] - el) / (zone_el[1] - zone_el[0]))
        amount = np.where(use, val * fade * zone, 0.0)
        moved += int((amount > 1e-4).sum())
        largest = max(largest, float(amount.max()) if len(amount) else 0.0)
        unit = rel / np.maximum(r, 1e-9)[:, None]
        shapes.append(HairShape(sh.name, pos + amount[:, None] * unit, sh.normals, sh.tangents, sh.uvs, sh.triangles,
                                sh.weights, sh.shader_ref, sh.alpha_ref, sh.block))
    return (Hair(shapes, hair.bones, hair.host_of_root, dict(hair.report, draped=True)),
            {"vertices_moved": moved, "largest_mm": round(1000 * largest, 1), "radius_mm": round(1000 * radius, 1)})


PUSH_BLEND = 0.06            # m: how far push_out eases its move off around the points it had to move (40 mm
                            # still left a bump on the temple strand in the owner's viewer, 2026-11-02)


def push_out(hair: Hair, head_pts: np.ndarray, head_nrm: np.ndarray, gap: float = 0.002,
             reach: float = 0.03, blend: float = PUSH_BLEND, chunk: int = 256) -> Tuple[Hair, Dict]:
    """Conform the wig to the head: every judged vertex closer than `gap` above the surface (or inside it) moves along
    the nearest head normal to `gap` above it. The Skyrim and Starfield female skulls differ in shape (2026-11-02,
    measured: after the best similarity a quarter of Skyrim's head lies over 2 mm inside Starfield's), so no scale /
    offset alone keeps a wig out.

    The move is one smooth field over the whole wig, not per vertex: each point moves by the largest of the needed
    moves around it, each eased off to nothing over `blend` m of distance (smoothstep), along its own nearest head
    normal. So every point still clears the head by `gap`, and the hair around a pushed patch rises with it in a
    curve (2026-11-02: owner saw a bump over Anna's brow where only the points inside Starfield's forehead had moved,
    half-spread to their mesh neighbours; Skyrim's hair curves smoothly there). One field for all shapes also moves
    neighbouring cards alike."""
    nrm_head = np.asarray(head_nrm, float)
    pos_all, need_all, idx_all = [], [], []
    for sh in hair.shapes:
        pos = np.asarray(sh.positions, float)
        depth, dist, idx = nearest_surface(pos, head_pts, head_nrm)
        ok = judged(pos, head_pts, dist, reach)
        pos_all.append(pos)
        need_all.append(np.where(ok & (depth < gap), gap - depth, 0.0))
        idx_all.append(idx)
    flat = np.concatenate(pos_all) if pos_all else np.zeros((0, 3))
    need = np.concatenate(need_all) if need_all else np.zeros(0)
    src = need > 0
    amount = need.copy()
    if src.any() and blend > 0:
        q, qn = flat[src], need[src]
        # one source per 4 mm cell (its largest need): the ease is 4 cm wide, and a wig has ~10k scalp points
        cell = np.floor(q / 0.004).astype(np.int64)
        order = np.argsort(-qn, kind="stable")
        _u, first = np.unique(cell[order], axis=0, return_index=True)
        q, qn = q[order[first]], qn[order[first]]
        qq = (q * q).sum(1)
        for c in range(0, len(flat), chunk):
            p = flat[c:c + chunk]
            d = np.sqrt(np.maximum((p * p).sum(1)[:, None] + qq[None, :] - 2.0 * p @ q.T, 0.0))
            ease = 1.0 - _smooth(d / blend)
            amount[c:c + chunk] = np.maximum(amount[c:c + chunk], (ease * qn[None, :]).max(axis=1))
    shapes, start = [], 0
    for sh, pos, idx in zip(hair.shapes, pos_all, idx_all):
        a = amount[start:start + len(pos)]
        start += len(pos)
        shapes.append(HairShape(sh.name, pos + a[:, None] * nrm_head[idx], sh.normals, sh.tangents, sh.uvs,
                                sh.triangles, sh.weights, sh.shader_ref, sh.alpha_ref, sh.block))
    moved = int(src.sum())
    report = {"vertices_moved": moved, "deepest_mm": round(1000 * float(need.max()), 1) if moved else 0.0,
              "vertices_eased": int((amount > need + 1e-4).sum()), "blend_mm": round(1000 * blend, 1)}
    return Hair(shapes, hair.bones, hair.host_of_root, dict(hair.report, pushed_out=moved)), report


TINT_SHAPES = (b"hairline",)   # KS's skin-tight scalp layer with a fading texture: not where the hair starts


def is_tint(sh: HairShape) -> bool:
    return any(k in (sh.name or b"").lower() for k in TINT_SHAPES)


def hair_points(hair: Hair) -> np.ndarray:
    """The points of the hair's own shapes, without the scalp tint layer (the measurements' input: the tint fades out
    lower on the forehead than the hair starts, 2026-11-02)."""
    pts = [np.asarray(sh.positions, float) for sh in hair.shapes if not is_tint(sh)]
    return np.concatenate(pts) if pts else np.zeros((0, 3))


def hairline(points: np.ndarray, head_pts: np.ndarray, head_nrm: np.ndarray, head: np.ndarray) -> Optional[float]:
    """Height of the hairline above C_Head at the middle of the forehead (m), or None: the lowest point lying on the
    head (within 1 cm of its surface) in a 3 cm wide band down the front of the face."""
    p = np.asarray(points, float)
    rel = p - np.asarray(head, float)[:3, 3]
    band = (np.abs(rel[:, 0]) < 0.015) & (rel[:, 1] > 0.04)
    if not band.any():
        return None
    depth, dist, _i = nearest_surface(p[band], head_pts, head_nrm)
    on = (dist < 0.03) & (depth < 0.01)
    return float(rel[band][on, 2].min()) if on.any() else None


VOLUME_MAX = 0.008          # m: the most add_volume adds by default (2026-11-02: 20 mm over a 3 cm rise read as a
                            # ridge above the forehead; 12 mm everywhere above the ears floated the sides off the head)
HAIRLINE_ANGLES = tuple(range(-70, 71, 10))       # degrees around the head from the front (+Y), + = the actor's right


def hairline_profile(points: np.ndarray, head_pts: np.ndarray, head_nrm: np.ndarray, head: np.ndarray,
                     angles=HAIRLINE_ANGLES) -> Dict[int, Optional[float]]:
    """{angle: hairline height above C_Head (m) or None}: as `hairline`, in a 3 cm wide vertical band through the head
    axis at each angle around the front (0 = the middle of the forehead, +-70 = the temples)."""
    p = np.asarray(points, float)
    rel = p - np.asarray(head, float)[:3, 3]
    depth, dist, _i = nearest_surface(p, head_pts, head_nrm)
    on = (dist < 0.03) & (depth < 0.01)
    out = {}
    for ang in angles:
        a = np.radians(ang)
        fwd, side = np.array([np.sin(a), np.cos(a)]), np.array([np.cos(a), -np.sin(a)])
        h = rel[:, :2]
        band = on & (np.abs(h @ side) < 0.015) & (h @ fwd > 0.04)
        out[int(ang)] = float(rel[band, 2].min()) if band.any() else None
    return out


def crown_height(points: np.ndarray, head: np.ndarray) -> Optional[float]:
    """Highest point of the hair within 3 cm of the head's vertical axis, above C_Head (m)."""
    rel = np.asarray(points, float) - np.asarray(head, float)[:3, 3]
    near = np.linalg.norm(rel[:, :2], axis=1) < 0.03
    return float(rel[near, 2].max()) if near.any() else None


def lift_profile(own: Dict[int, Optional[float]], target: Dict[int, Optional[float]],
                 limit: float = 0.03) -> Dict[int, float]:
    """{angle: lift (m)}: how far the wig's hairline is below the target's at each angle (0 where it is higher or a
    side is missing), clipped to `limit`, gaps filled from the neighbours, then smoothed over neighbouring angles."""
    angs = sorted(own)
    raw = {a: (min(max(target[a] - own[a], 0.0), limit) if own.get(a) is not None and target.get(a) is not None
               else None) for a in angs}
    known = [a for a in angs if raw[a] is not None]
    if not known:
        return {a: 0.0 for a in angs}
    filled = {a: raw[a] if raw[a] is not None else float(np.interp(a, known, [raw[k] for k in known])) for a in angs}
    return {a: float(np.mean([filled[b] for b in angs if abs(b - a) <= 10])) for a in angs}


def _smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def lift_hairline(hair: Hair, head_pts: np.ndarray, head_nrm: np.ndarray, head: np.ndarray, lift,
                  front=(0.02, 0.08), crown=(0.12, 0.16)) -> Hair:
    """The front of the wig raised by `lift` m: full at the forehead (C_Head-relative +Y beyond front[1]), fading to
    nothing toward the back (front[0]) and toward the top of the head (crown), so the crown and the back stay put.
    Points that lay on the head keep their height above its surface (moved back along the nearest normal after the
    lift). 2026-11-02 measured: Skyrim wigs start ~15 mm lower on the forehead than Starfield's own hair (Anna 83 mm
    above C_Head, vanilla bob 98): Skyrim faces have shorter foreheads, which the cranium fit cannot see."""
    h = np.asarray(head, float)[:3, 3]
    shapes = []
    for sh in hair.shapes:
        pos = np.asarray(sh.positions, float)
        rel = pos - h
        if isinstance(lift, dict):        # per angle around the head (lift_profile): the temples too
            angs = sorted(lift)
            ang = np.degrees(np.arctan2(rel[:, 0], rel[:, 1]))
            amount = np.interp(ang, angs, [lift[k] for k in angs])
            front_w = _smooth((np.abs(ang) - 90.0) / -20.0) * _smooth((np.hypot(rel[:, 0], rel[:, 1]) - 0.02) / 0.04)
        else:
            amount = np.full(len(pos), float(lift))
            front_w = _smooth((rel[:, 1] - front[0]) / (front[1] - front[0]))
        w = amount * front_w * _smooth((crown[1] - rel[:, 2]) / (crown[1] - crown[0]))
        d0, dist0, _i = nearest_surface(pos, head_pts, head_nrm)
        new = pos.copy()
        new[:, 2] += w
        on = judged(pos, head_pts, dist0) & (w > 0)
        if on.any():
            d1, _d, j = nearest_surface(new[on], head_pts, head_nrm)
            new[on] += (d0[on] - d1)[:, None] * np.asarray(head_nrm, float)[j]
        shapes.append(HairShape(sh.name, new, sh.normals, sh.tangents, sh.uvs, sh.triangles, sh.weights,
                                sh.shader_ref, sh.alpha_ref, sh.block))
    return Hair(shapes, hair.bones, hair.host_of_root, dict(hair.report, hairline_lift=True))


def _volume_share(pos, head_pts, head_nrm, h, low, high, edge, edge_fade):
    """(share 0..1 of the volume each point takes, its nearest head point's index): add_volume's fade."""
    known = sorted(k for k, v in (edge or {}).items() if v is not None)
    _d, dist, j = nearest_surface(pos, head_pts, head_nrm)
    rel = pos - h
    rel_z = rel[:, 2]
    w = _smooth((rel_z - low) / (high - low)) * _smooth((0.06 - dist) / 0.03)
    if known:
        ang = np.degrees(np.arctan2(rel[:, 0], rel[:, 1]))
        line = np.interp(np.clip(ang, known[0], known[-1]), known, [edge[k] for k in known])
        at_edge = np.abs(ang) <= 120.0
        w = np.where(at_edge, w * _smooth((rel_z - line) / edge_fade), w)
    return w, j


def _turn_z(v: np.ndarray, deg: np.ndarray) -> np.ndarray:
    """Vectors (n, 3) turned about the vertical by per-row angles (degrees)."""
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    return np.stack([c * v[:, 0] - s * v[:, 1], s * v[:, 0] + c * v[:, 1], v[:, 2]], axis=1)


def _sub_shape(sh: HairShape, name: bytes, pos, nrm, tan, keep_tri) -> Optional[HairShape]:
    """The triangles `keep_tri` of sh with its vertices renumbered (pos / nrm / tan per original vertex)."""
    tris = [t for t, k in zip(sh.triangles, keep_tri) if k]
    if not tris:
        return None
    used = sorted({v for t in tris for v in t})
    new = {v: i for i, v in enumerate(used)}
    pick = np.array(used)
    return HairShape(name, pos[pick], None if nrm is None else nrm[pick], None if tan is None else tan[pick],
                     [sh.uvs[v] for v in used] if sh.uvs else sh.uvs, [tuple(new[v] for v in t) for t in tris],
                     [sh.weights[v] for v in used], sh.shader_ref, sh.alpha_ref, sh.block)


LAYERS = 0                  # fill layers add_volume stacks under a raised wig by default (hair_pack): off
                            # (2026-11-02: 3 layers at 20 mm read in the viewer as a choppy puffed shelf
                            # ending above the forehead; owner: 'that looks so choppy')
VOLUME_MAX_LAYERED = 0.02   # m: the most volume by default when the gap is filled (IDG Elegant's extra-long straight:
                            # ~18 hair sheets over ~24 mm along a ray out of the scalp; KS Anna ~4 within ~1 mm)
LAYER_TURN = 2.0            # degrees each fill layer is turned about the vertical, alternating, so its cards cover
                            # the gaps between the cards of the layer under it instead of lining up with them
LAYER_MIN_SHARE = 0.2       # a fill layer keeps the triangles that take at least this share of the volume: nearer
                            # the hairline / the strands it would lie on the original (z-fighting)


def add_volume(hair: Hair, head_pts: np.ndarray, head_nrm: np.ndarray, head: np.ndarray, amount: float,
               low: float = 0.06, high: float = 0.12, edge: Optional[Dict[int, Optional[float]]] = None,
               edge_fade: float = 0.05, keep=TINT_SHAPES, layers: int = 0, turn: float = LAYER_TURN,
               min_share: float = LAYER_MIN_SHARE) -> Hair:
    """Hair lying on the head moved `amount` m outward along the head's normal, full above `high` (C_Head-relative
    height: the top of the head only; the sides stay snug, as on the vanilla hairs), fading to nothing at `low`: KS
    wigs hug the scalp, Starfield's own hair stands off it (2026-11-02: owner saw the wigs flat next to the vanilla
    bob, then the sides floating when the whole head above the ears was pushed). Points off the head (strands) follow by the same fade with the
    displacement of their nearest head point, so locks stay attached. The wig's edge stays on the skin: with `edge` (its
    hairline_profile) the push fades to nothing at the hairline over `edge_fade` m (the sides up to 120 deg take the
    temple's height), and shapes named like `keep` (KS's 'Hairline' scalp tint) never move: a pushed-out edge or
    tint would leave a visible gap between hair and skin.

    With `layers` > 0 the wig is filled instead of moved (2026-11-02: owner: a raised KS wig looks like it floats,
    IDG's hair is 'more 3D, filled in'): the original stays on the scalp and `layers` copies of its raised part stand
    at amount * k / layers (k = 1..layers, the last at the full amount), each turned `turn` degrees about the vertical
    (alternating sides, scaled by the same fade) so the stack covers the gaps between cards. A copy keeps only the
    triangles whose three corners take at least `min_share` of the volume; weights / UVs / material are the
    original's, so the copies swing with it."""
    h = np.asarray(head, float)[:3, 3]
    nrm_head = np.asarray(head_nrm, float)
    shapes, added = [], []
    for sh in hair.shapes:
        pos = np.asarray(sh.positions, float)
        if any(k in (sh.name or b"").lower() for k in keep):
            shapes.append(sh)
            continue
        share, j = _volume_share(pos, head_pts, head_nrm, h, low, high, edge, edge_fade)
        if layers <= 0:
            shapes.append(HairShape(sh.name, pos + (amount * share)[:, None] * nrm_head[j], sh.normals, sh.tangents,
                                    sh.uvs, sh.triangles, sh.weights, sh.shader_ref, sh.alpha_ref, sh.block))
            continue
        shapes.append(sh)
        tris = np.asarray(sh.triangles, int).reshape(-1, 3)
        ok_tri = (share[tris] >= min_share).all(axis=1) if len(tris) else np.zeros(0, bool)
        nrm = None if sh.normals is None else np.asarray(sh.normals, float)
        tan = None if sh.tangents is None else np.asarray(sh.tangents, float)
        for k in range(1, layers + 1):
            deg = turn * ((k + 1) // 2) * (1 if k % 2 else -1) * share
            p = _turn_z(pos - h, deg) + h + (amount * k / layers * share)[:, None] * nrm_head[j]
            sub = _sub_shape(sh, (sh.name or b"") + b"_layer%d" % k, p,
                             None if nrm is None or nrm.shape != pos.shape else _turn_z(nrm, deg),
                             None if tan is None or tan.shape != pos.shape else _turn_z(tan, deg), ok_tri)
            if sub is not None:
                shapes.append(sub)
                added.append(len(sub.positions))
    report = dict(hair.report, volume=amount)
    if layers > 0:
        report.update(layers=layers, layer_vertices=int(sum(added)),
                      shapes=[(s.name or b"").decode("latin-1") for s in shapes],
                      vertices=int(sum(len(s.positions) for s in shapes)))
    return Hair(shapes, hair.bones, hair.host_of_root, report)


def _components(n_vertices: int, triangles) -> np.ndarray:
    """Connected-component label per vertex (vertices sharing a triangle are connected)."""
    parent = np.arange(n_vertices)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for t in triangles:
        a = find(t[0])
        for v in t[1:]:
            b = find(v)
            if a != b:
                parent[b] = a
    return np.array([find(v) for v in range(n_vertices)])


def orient_outward(hair: Hair, head: np.ndarray) -> Tuple[Hair, Dict]:
    """Every hair card turned to face away from the head: a card (connected piece of mesh) whose triangles mostly face
    inward gets its winding reversed and its normals negated. Away from the head = from the cranium's centre (C_Head +
    9 cm up) above it, from the vertical through it below (hanging hair faces away from the body). Verified 2026-11-02:
    IDG's cards face outward (99-100 % of the triangles over the head), KS Anna's only half (Skyrim lights both sides
    of a double-sided card, flipping the normal for the back). Starfield's hair shader draws a card's back with the
    front's normal, so the inward half lit as if facing the scalp and changed light / dark as the view turned
    (owner's in-game shots, also on the no-physics wigs and with the depth offset off)."""
    c = np.asarray(head, float)[:3, 3] + np.array([0.0, 0.0, 0.09])
    shapes, flipped, cards = [], 0, 0
    for sh in hair.shapes:
        tris = np.asarray(sh.triangles, int).reshape(-1, 3)
        pos = np.asarray(sh.positions, float)
        if not len(tris):
            shapes.append(sh)
            continue
        a, b, d = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
        fn = np.cross(b - a, d - a)                      # area-weighted
        mid = (a + b + d) / 3.0
        out = mid - np.stack([np.full(len(mid), c[0]), np.full(len(mid), c[1]), np.minimum(mid[:, 2], c[2])], axis=1)
        facing = (fn * out).sum(1)
        comp = _components(len(pos), tris)
        tri_comp = comp[tris[:, 0]]
        score = {}
        for k, f in zip(tri_comp, facing):
            score[k] = score.get(k, 0.0) + f
        flip_comp = {k for k, v in score.items() if v < 0}
        cards += len(score)
        flipped += len(flip_comp)
        if not flip_comp:
            shapes.append(sh)
            continue
        flip_tri = np.isin(tri_comp, list(flip_comp))
        new_tris = [(t[0], t[2], t[1]) if f else tuple(t) for t, f in zip(sh.triangles, flip_tri)]
        flip_v = np.isin(comp, list(flip_comp))
        nrm = None if sh.normals is None else np.where(flip_v[:, None], -np.asarray(sh.normals, float),
                                                         np.asarray(sh.normals, float))
        shapes.append(HairShape(sh.name, sh.positions, nrm, sh.tangents, sh.uvs, new_tris, sh.weights,
                                sh.shader_ref, sh.alpha_ref, sh.block))
    return (Hair(shapes, hair.bones, hair.host_of_root, dict(hair.report, oriented=True)),
            {"cards": cards, "turned": flipped})


def _vertex_face_normals(pos: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """Per vertex the sum of its triangles' area-weighted normals (by winding), unnormalised."""
    acc = np.zeros_like(pos)
    if len(tris):
        fn = np.cross(pos[tris[:, 1]] - pos[tris[:, 0]], pos[tris[:, 2]] - pos[tris[:, 0]])
        for k in range(3):
            np.add.at(acc, tris[:, k], fn)
    return acc


def geometric_normals(hair: Hair) -> Tuple[Hair, Dict]:
    """Vertex normals recomputed from the final shape: each the area-weighted average of its triangles' normals (by
    their winding, which orient_outward turned away from the head). Verified 2026-11-03: IDG's (Starfield's own
    convention) vertex normals are exactly that (|cos| median 1.0 with the face normals, all on the faces' side).
    A Skyrim hair's stored normals were made for Skyrim's two-sided lighting and are not moved by the shaping
    (follow_head, push_out, separate_layers move the vertices): where they disagree with the card the hair shader
    lights the card as facing elsewhere (owner 2026-11-03: dark / light patches on the vanilla Skyrim hairstyles, as
    on the KS wigs). Report: per shape the share of old normals that pointed against their triangles and the median
    angle between old and new."""
    shapes, rows = [], []
    for sh in hair.shapes:
        pos = np.asarray(sh.positions, float)
        tris = np.asarray(sh.triangles, int).reshape(-1, 3)
        if not len(pos) or not len(tris):
            shapes.append(sh)
            continue
        acc = _vertex_face_normals(pos, tris)
        size = np.linalg.norm(acc, axis=1)
        good = size > 1e-14
        old = (np.asarray(sh.normals, float) if sh.normals is not None and np.shape(sh.normals) == pos.shape
               else np.zeros_like(pos))
        oldn = old / np.maximum(np.linalg.norm(old, axis=1, keepdims=True), 1e-12)
        new = np.where(good[:, None], acc / np.maximum(size, 1e-14)[:, None], oldn)
        cos = (oldn * new).sum(1)[good]
        rows.append({"name": (sh.name or b"").decode("latin-1"),
                     "old_against_faces": round(float((cos < 0).mean()), 3) if len(cos) else 0.0,
                     "old_vs_new_deg_median": round(float(np.degrees(np.arccos(np.clip(np.median(cos), -1, 1)))), 1)
                     if len(cos) else 0.0})
        shapes.append(HairShape(sh.name, sh.positions, new, sh.tangents, sh.uvs, sh.triangles, sh.weights,
                                sh.shader_ref, sh.alpha_ref, sh.block))
    return Hair(shapes, hair.bones, hair.host_of_root, dict(hair.report, geometric_normals=True)), {"shapes": rows}


def shell_normals(hair: Hair, head: np.ndarray) -> Tuple[Hair, Dict]:
    """Diagnostic: every vertex normal set to 'away from the head' (orient_outward's direction: from the cranium's
    centre above it, from the vertical through it below), as if the hair were one smooth shell. Lighting then no
    longer depends on how each card is tilted."""
    c = np.asarray(head, float)[:3, 3] + np.array([0.0, 0.0, 0.09])
    shapes, n = [], 0
    for sh in hair.shapes:
        pos = np.asarray(sh.positions, float)
        if not len(pos):
            shapes.append(sh)
            continue
        out = pos - np.stack([np.full(len(pos), c[0]), np.full(len(pos), c[1]), np.minimum(pos[:, 2], c[2])], axis=1)
        out /= np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-12)
        n += len(pos)
        shapes.append(HairShape(sh.name, sh.positions, out, sh.tangents, sh.uvs, sh.triangles, sh.weights,
                                sh.shader_ref, sh.alpha_ref, sh.block))
    return Hair(shapes, hair.bones, hair.host_of_root, dict(hair.report, shell_normals=True)), {"vertices": n}


LAYER_STEP = 0.0008           # m: the least gap separate_layers leaves between stacked hair cards
LAYER_CELL = 0.006           # m: the neighbourhood in which cards count as stacked
LAYER_MAX = 0.006            # m: the most any card is moved out


def separate_layers(hair: Hair, head: np.ndarray, step: float = LAYER_STEP, cell: float = LAYER_CELL,
                    limit: float = LAYER_MAX, smooth: int = 4, passes: int = 4, keep=None) -> Tuple[Hair, Dict]:
    """separate_layers_once `passes` times (the smoothing gives back part of each gap; repeating closes it)."""
    report = {}
    start = hair
    for _ in range(max(1, passes)):
        hair, report = separate_layers_once(hair, head, step, cell, limit, smooth, keep)
    shapes, moved = [], []
    for a, b in zip(start.shapes, hair.shapes):     # the total move capped at `limit` (deep stacks: the top ones)
        p0 = np.asarray(a.positions, float)
        dv = np.asarray(b.positions, float) - p0 if len(p0) else np.zeros((0, 3))
        n = np.linalg.norm(dv, axis=1) if len(p0) else np.zeros(0)
        dv = dv * np.minimum(1.0, limit / np.maximum(n, 1e-12))[:, None]
        moved.append(np.minimum(n, limit))
        shapes.append(b if b is a else HairShape(b.name, p0 + dv, b.normals, b.tangents, b.uvs, b.triangles,
                                                 b.weights, b.shader_ref, b.alpha_ref, b.block))
    hair = Hair(shapes, hair.bones, hair.host_of_root, hair.report)
    allm = np.concatenate(moved) if moved else np.zeros(0)
    on = allm > 1e-5
    return hair, {"vertices_moved": int(on.sum()), "largest_mm": round(1000 * float(allm.max()), 2) if len(allm) else 0,
                  "median_moved_mm": round(1000 * float(np.median(allm[on])), 2) if on.any() else 0.0,
                  "passes": passes}


def separate_layers_once(hair: Hair, head: np.ndarray, step: float = LAYER_STEP, cell: float = LAYER_CELL,
                         limit: float = LAYER_MAX, smooth: int = 4, keep=None) -> Tuple[Hair, Dict]:
    """Stacked hair cards moved apart: KS lays its cards on top of each other with no gap (Anna, measured
    2026-11-03: in 91 % of 6 mm patches where cards overlap, consecutive cards lie within 0.5 mm of each other,
    median 0), which Skyrim's sorted alpha blending hides. Starfield's hair shader writes depth, so two such cards
    fight over every pixel and the winner changes along the triangles: a maze of outlines etched into the hair
    (owner's looks-menu shots, also with crisp opacity). In every `cell` patch the cards present are ordered by
    their distance from the head (as orient_outward: from C_Head + 9 cm above it, from the vertical through it below)
    and each is moved outward just enough to sit `step` beyond the one under it (never more than `limit`); the moves
    are averaged over mesh neighbours `smooth` times so a card bends instead of stepping. Only moves outward."""
    keep = TINT_SHAPES if keep is None else keep
    c = np.asarray(head, float)[:3, 3] + np.array([0.0, 0.0, 0.09])
    use = [k for k, sh in enumerate(hair.shapes) if len(sh.positions) and len(sh.triangles)
           and not any(t in (sh.name or b"").lower() for t in keep)]
    if not use:
        return hair, {"vertices_moved": 0}
    pos, card, tris, base = [], [], [], 0
    for n, k in enumerate(use):
        sh = hair.shapes[k]
        p = np.asarray(sh.positions, float)
        t = np.asarray(sh.triangles, int).reshape(-1, 3)
        pos.append(p)
        card.append(_components(len(p), t) + base)
        tris.append(t + base)
        base += len(p)
    pos, card, tris = np.concatenate(pos), np.concatenate(card), np.concatenate(tris)
    axis = np.stack([np.full(len(pos), c[0]), np.full(len(pos), c[1]), np.minimum(pos[:, 2], c[2])], axis=1)
    out = pos - axis
    d = np.linalg.norm(out, axis=1)
    out /= np.maximum(d, 1e-9)[:, None]
    key = np.floor(pos / cell).astype(np.int64)
    _cells, cell_of = np.unique(key, axis=0, return_inverse=True)
    cell_of = cell_of.reshape(-1)
    pair, pair_of = np.unique(np.stack([cell_of, card], axis=1), axis=0, return_inverse=True)
    pair_of = pair_of.reshape(-1)
    mean = np.zeros(len(pair))
    np.add.at(mean, pair_of, d)
    mean /= np.maximum(np.bincount(pair_of, minlength=len(pair)), 1)
    lift = np.zeros(len(pair))
    order = np.lexsort((mean, pair[:, 0]))               # by cell, then distance from the head
    prev_cell, prev_top = -1, 0.0
    for i in order:
        if pair[i, 0] != prev_cell:
            prev_cell, prev_top = pair[i, 0], mean[i]
            continue
        want = prev_top + step
        lift[i] = min(max(want - mean[i], 0.0), limit)
        prev_top = mean[i] + lift[i]
    move = lift[pair_of]
    if smooth > 0 and len(tris):
        e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
        e = np.concatenate([e, e[:, ::-1]])
        deg = np.bincount(e[:, 0], minlength=len(pos)).astype(float)
        need = move.copy()
        for _ in range(smooth):
            acc = np.bincount(e[:, 0], weights=move[e[:, 1]], minlength=len(pos))
            move = np.where(deg > 0, 0.5 * move + 0.5 * acc / np.maximum(deg, 1), move)
        move = np.maximum(move, 0.5 * need)              # smoothing never undoes more than half a gap
    new = pos + move[:, None] * out
    shapes, start, it = list(hair.shapes), 0, iter(use)
    for k in use:
        sh = hair.shapes[k]
        n = len(sh.positions)
        shapes[k] = HairShape(sh.name, new[start:start + n], sh.normals, sh.tangents, sh.uvs, sh.triangles,
                              sh.weights, sh.shader_ref, sh.alpha_ref, sh.block)
        start += n
    moved = move > 1e-5
    return (Hair(shapes, hair.bones, hair.host_of_root, dict(hair.report, separated_layers=True)),
            {"vertices_moved": int(moved.sum()), "largest_mm": round(1000 * float(move.max()), 2),
             "median_moved_mm": round(1000 * float(np.median(move[moved])), 2) if moved.any() else 0.0})


def strand_axis(sh: HairShape, head=None) -> Optional[str]:
    """'u' or 'v': which texture axis the shape's strands run along, judged on its steep triangles (strands hang
    down): the UV direction (dP/du or dP/dv) that points more nearly down. None when it cannot tell."""
    pos = np.asarray(sh.positions, float)
    if not sh.uvs or not len(sh.triangles) or not len(pos):
        return None
    uv = np.asarray(sh.uvs, float)
    t = np.asarray(sh.triangles, int).reshape(-1, 3)
    e1, e2 = pos[t[:, 1]] - pos[t[:, 0]], pos[t[:, 2]] - pos[t[:, 0]]
    d1, d2 = uv[t[:, 1]] - uv[t[:, 0]], uv[t[:, 2]] - uv[t[:, 0]]
    det = d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]
    fn = np.cross(e1, e2)
    fl = np.linalg.norm(fn, axis=1)
    ok = (np.abs(det) > 1e-12) & (fl > 1e-12)
    ok &= np.abs(fn[:, 2]) < 0.8 * np.maximum(fl, 1e-12)          # steep: not lying flat on the crown
    if ok.sum() < 1:
        return None
    du = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2])[ok]
    dv = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1])[ok]
    su = np.median(np.abs(du[:, 2]) / np.maximum(np.linalg.norm(du, axis=1), 1e-12))
    sv = np.median(np.abs(dv[:, 2]) / np.maximum(np.linalg.norm(dv, axis=1), 1e-12))
    if abs(su - sv) < 0.1:
        return None
    return "u" if su > sv else "v"


def strands_down(hair: Hair, head=None) -> Tuple[Hair, List[bool]]:
    """The hair with every shape whose strands run along U given swapped UVs (u, v) -> (v, u), and per shape whether
    it was (its texture must be transposed to match: pipeline transpose=True). Starfield's hair shader runs strands
    along V (IDG's, and KS's: dP/dv points down, verified 2026-11-03); some vanilla Skyrim hair textures lay them
    across, which the strand maps, the band evening and the tangents all read the wrong way: the owner saw
    horizontal-looking texture and patchy light / dark on the Skyrim hairstyles."""
    shapes, flags = [], []
    for sh in hair.shapes:
        turn = strand_axis(sh) == "u"
        flags.append(turn)
        shapes.append(sh if not turn else HairShape(sh.name, sh.positions, sh.normals, sh.tangents,
                                                    [(v, u) for u, v in sh.uvs], sh.triangles, sh.weights,
                                                    sh.shader_ref, sh.alpha_ref, sh.block))
    return Hair(shapes, hair.bones, hair.host_of_root, hair.report), flags


def strands_across(sh: HairShape, across) -> np.ndarray:
    """Per vertex True where the shape's card has its texture's strands along U, from `across` (the texture's
    pipeline.strand_orientation map, rows = V, columns = U): each triangle sampled at its UV centroid (wrapping), then
    the majority of each card (connected piece) for all its vertices, so a card is lit one way. All False without a
    map or UVs."""
    pos = np.asarray(sh.positions, float)
    out = np.zeros(len(pos), bool)
    if across is None or not sh.uvs or not len(sh.triangles):
        return out
    m = np.asarray(across, bool)
    if not m.any():
        return out
    h, w = m.shape
    uv = np.asarray(sh.uvs, float)
    t = np.asarray(sh.triangles, int).reshape(-1, 3)
    c = uv[t].mean(1)
    col = np.floor(np.mod(c[:, 0], 1.0) * w).astype(int).clip(0, w - 1)
    row = np.floor(np.mod(c[:, 1], 1.0) * h).astype(int).clip(0, h - 1)
    tri = m[row, col]
    comp = _components(len(pos), t)
    tc = comp[t[:, 0]]
    for k in np.unique(tc):
        sel = tc == k
        out[comp == k] = tri[sel].mean() > 0.5
    return out


def uv_tangents(hair: Hair, along_v=None) -> Tuple[Hair, Dict]:
    """Tangents recomputed from the UVs as Starfield expects them: along +U (dP/du), perpendicular to the normal.
    Verified 2026-11-03: IDG's (the game's own convention) tangents follow dP/du (|cos| 1.0 on two styles); the
    tangents a Skyrim NIF hands us follow dP/dv (KS Anna / Erena: |cos| 1.0 with dP/dv, 0.2 with dP/du: the
    Skyrim tangent / bitangent swap). The hair shader lights along the strand from the tangent frame, so the KS
    hair was lit across its strands: bright / dark bands bounded by the cards' quads, the "brick" pattern (owner's
    looks-menu shots, unchanged by every texture fix). Vertices with no usable UV gradient keep their tangent.
    along_v: per shape, a per-vertex bool (strands_across) or None: those vertices take dP/dv instead, for cards whose
    texture has its strands along U (the shader's strand direction, the bitangent, then runs along them)."""
    shapes, fixed, total, turned = [], 0, 0, 0
    for k_sh, sh in enumerate(hair.shapes):
        pos = np.asarray(sh.positions, float)
        if sh.normals is None or not len(pos) or not sh.uvs or not len(sh.triangles):
            shapes.append(sh)
            continue
        uv = np.asarray(sh.uvs, float)
        t = np.asarray(sh.triangles, int).reshape(-1, 3)
        e1, e2 = pos[t[:, 1]] - pos[t[:, 0]], pos[t[:, 2]] - pos[t[:, 0]]
        d1, d2 = uv[t[:, 1]] - uv[t[:, 0]], uv[t[:, 2]] - uv[t[:, 0]]
        det = d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]
        ok = np.abs(det) > 1e-12
        du = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * np.where(ok, np.sign(det), 0.0)[:, None]   # dP/du * |det|
        acc = np.zeros_like(pos)
        for k in range(3):
            np.add.at(acc, t[:, k], du)
        turn = None if along_v is None or k_sh >= len(along_v) else along_v[k_sh]
        if turn is not None and np.asarray(turn, bool).any():
            turn = np.asarray(turn, bool)
            dv = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) * np.where(ok, np.sign(det), 0.0)[:, None]   # dP/dv * |det|
            acc_v = np.zeros_like(pos)
            for k in range(3):
                np.add.at(acc_v, t[:, k], dv)
            acc = np.where(turn[:, None], acc_v, acc)
            turned += int(turn.sum())
        n = np.asarray(sh.normals, float)
        n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        acc -= (acc * n).sum(1, keepdims=True) * n
        size = np.linalg.norm(acc, axis=1)
        good = size > 1e-12
        old = (np.asarray(sh.tangents, float) if sh.tangents is not None and np.shape(sh.tangents) == pos.shape
               else np.zeros_like(pos))
        old = old - (old * n).sum(1, keepdims=True) * n
        old = old / np.maximum(np.linalg.norm(old, axis=1, keepdims=True), 1e-12)
        tan = np.where(good[:, None], acc / np.maximum(size, 1e-12)[:, None], old)
        fixed += int(good.sum())
        total += len(pos)
        shapes.append(HairShape(sh.name, sh.positions, sh.normals, tan, sh.uvs, sh.triangles, sh.weights,
                                sh.shader_ref, sh.alpha_ref, sh.block))
    rep = {"vertices": total, "recomputed": fixed}
    if turned:
        rep["along_v"] = turned
    return Hair(shapes, hair.bones, hair.host_of_root, dict(hair.report, uv_tangents=True)), rep


def drop_duplicate_shapes(hair: Hair) -> Tuple[Hair, List[str]]:
    """The hair without shapes whose geometry repeats an earlier shape's (same positions, triangles and UVs): KS
    draws every wig twice, 'KSSMP_<name>' alpha-blended (test 40) and '..._HL' alpha-tested (test 200), Skyrim's
    two-pass trick for soft edges. Starfield's hair shader does its own soft edges, so the second copy would only lie
    in the first (z-fighting). (hair, names dropped)."""
    kept, dropped = [], []
    for sh in hair.shapes:
        pos = np.asarray(sh.positions, float)
        twin = any(len(o.positions) == len(pos) and list(o.triangles) == list(sh.triangles)
                   and np.allclose(np.asarray(o.positions, float), pos, atol=1e-6) and list(o.uvs) == list(sh.uvs)
                   for o in kept)
        (dropped if twin else kept).append(sh)
    if not dropped:
        return hair, []
    names = [(s.name or b"").decode("latin-1") for s in dropped]
    report = dict(hair.report, shapes=[(s.name or b"").decode("latin-1") for s in kept],
                  vertices=int(sum(len(s.positions) for s in kept)), dropped_duplicates=names)
    return Hair(kept, hair.bones, hair.host_of_root, report), names


def rigid(hair: Hair) -> Hair:
    """The same hair without physics: every simulated bone's weight moved to the human bone its chain hangs from
    (no new bones, no cloth). A control for in-game tests: if this shows and the physics version does not, the
    simulated bones / cloth are the problem."""
    par = {b.name: b.parent for b in hair.bones}

    def host(name):
        seen = 0
        while name in par and seen < 256:
            name, seen = par[name], seen + 1
        return name
    shapes = []
    for sh in hair.shapes:
        ws = []
        for vw in sh.weights:
            acc: Dict[str, float] = {}
            for b, w in vw:
                acc[host(b)] = acc.get(host(b), 0.0) + w
            ws.append(sorted(acc.items(), key=lambda kv: -kv[1]))
        shapes.append(HairShape(sh.name, sh.positions, sh.normals, sh.tangents, sh.uvs, sh.triangles, ws,
                                sh.shader_ref, sh.alpha_ref, sh.block))
    return Hair(shapes, [], {}, dict(hair.report, rigid=True))


def head_local(hair: Hair, sf_world: Dict[str, np.ndarray], bone: str = None) -> Tuple[Hair, Dict[str, np.ndarray]]:
    """The hair rigidly on one bone (default C_Head) in that bone's own frame: (hair, world) with world = {bone:
    identity}, so nif_files writes an identity bind and bone-local vertices: the convention of the worn left blade,
    seen in game. A second control: if this shows and rigid() does not, the multi-bone / rest-pose binds are the
    problem."""
    bone = bone or SF_HEAD
    inv = np.linalg.inv(sf_world[bone])
    r, t = inv[:3, :3], inv[:3, 3]

    def turn(v):
        if len(v) == 0:
            return v
        v = np.asarray(v, float).reshape(-1, 3) @ r.T
        n = np.linalg.norm(v, axis=1, keepdims=True)
        return v / np.maximum(n, 1e-12)
    shapes = []
    for sh in hair.shapes:
        pos = np.asarray(sh.positions, float) @ r.T + t
        shapes.append(HairShape(sh.name, pos, turn(sh.normals), turn(sh.tangents), sh.uvs, sh.triangles,
                                [[(bone, 1.0)] for _ in sh.weights], sh.shader_ref, sh.alpha_ref, sh.block))
    return Hair(shapes, [], {}, dict(hair.report, rigid=True, head_local=bone)), {bone: np.eye(4)}


FACE_BONES_PREFERRED = ("faceBone_C_HeadTop", "faceBone_C_HeadBack", "faceBone_C_HeadFore1")


def xf_matrix(xf) -> np.ndarray:
    """4x4 of a NIF transform (rot 9 row-major, trans 3, scale): p' = s R p + t."""
    rot, trans, scale = xf
    m = np.eye(4)
    m[:3, :3] = np.asarray(rot, float).reshape(3, 3) * float(scale)
    m[:3, 3] = trans
    return m


def face_bone_worlds(skin: dict, node: Optional[np.ndarray] = None) -> Dict[str, np.ndarray]:
    """{face bone: rest world 4x4} from a vanilla *_facebones.nif's skin (sfnif.parse_skin): bind = inverse(rest world)
    composed with the shape's node transform (the robe's convention; identity on Eris' hairs), so world = node @
    inverse(bind). Stored row-major."""
    node = np.eye(4) if node is None else np.asarray(node, float)
    out = {}
    for name, (_sphere, rot, trans, scale) in zip(skin["bones"], skin["binds"]):
        name = name.decode("latin-1") if isinstance(name, bytes) else name
        if not name.lower().startswith("facebone_"):
            continue
        inv = np.eye(4)
        inv[:3, :3] = np.asarray(rot, float).reshape(3, 3) * float(scale or 1.0)
        inv[:3, 3] = trans
        out[name] = node @ np.linalg.inv(inv)
    return out


def pick_face_bone(worlds: Dict[str, np.ndarray]) -> str:
    for b in FACE_BONES_PREFERRED:
        if b in worlds:
            return b
    if not worlds:
        raise HairError("no face bone in the facebones template")
    return sorted(worlds)[0]


def on_face_bone(hair: Hair, face_bone: str, host: str = None) -> Hair:
    """The hair with every weight on `host` (default C_Head) moved to `face_bone`: the *_facebones.nif variant the
    game draws on actors with face bones (vanilla hairs and hats ship both; the facebones one has no C_Head)."""
    host = host or SF_HEAD
    shapes = [HairShape(sh.name, sh.positions, sh.normals, sh.tangents, sh.uvs, sh.triangles,
                        [[(face_bone if b == host else b, w) for b, w in vw] for vw in sh.weights],
                        sh.shader_ref, sh.alpha_ref, sh.block) for sh in hair.shapes]
    return Hair(shapes, hair.bones, hair.host_of_root, dict(hair.report, face_bone=face_bone))


def merge(hairs: List[Hair]) -> Hair:
    """One hair from several (a head part and its extra parts, e.g. Skyrim's hair + hairline): shapes and bones
    together, reports listed."""
    out = Hair([], [], {}, {"parts": []})
    for h in hairs:
        out.shapes += h.shapes
        out.bones += [b for b in h.bones if b.name not in {x.name for x in out.bones}]
        out.host_of_root.update(h.host_of_root)
        out.report["parts"].append(h.report)
    return out


def head_capsule(sf_world: Dict[str, np.ndarray], hair: Hair, margin: float = 0.024) -> smpcloth.Capsule:
    """A capsule for the skull on C_Head, shrunk so that no simulated particle starts inside it. Size from the
    Starfield male head mesh (2026-10-27: least-squares sphere through the cranium above the head bone: centre
    (0, 0.023, 0.067) m from C_Head in model axes, radius 0.084), a little inside the scalp."""
    w = sf_world[SF_HEAD]
    centre = np.array([0.0, 0.023, 0.067])
    start, end = centre - [0.0, 0.01, 0.0], centre + [0.0, 0.01, 0.0]
    radius = 0.078
    roots = set(hair.host_of_root)
    pts = [b.world[:3, 3] for b in hair.bones if b.name not in roots] + [b.tip for b in hair.bones
                                                                         if b.tip is not None]
    for p in pts:
        q = np.asarray(p, float) - w[:3, 3]
        t = float(np.clip((q - start) @ (end - start) / ((end - start) @ (end - start)), 0.0, 1.0))
        radius = min(radius, float(np.linalg.norm(q - (start + t * (end - start)))) - margin)
    return smpcloth.Capsule("S2S_head", SF_HEAD, start, end, max(radius, 0.03))


# Body colliders for long hair (2026-11-02: the owner saw the physics wigs sink into the back / hips with only the head
# collider). Model space at rest (metres, +Y forward, +Z up, left = -X), placed from the cloth skeleton's bone origins
# (C_Chest z 1.23, C_Hips 1.06, L_Butt (-0.08, -0.14, 0.97), L_Thigh (-0.12, -0.02, 0.94), L_Calf z 0.49, L_Biceps
# (-0.15, -0.05, 1.40), L_Elbow (-0.34, -0.07, 1.20)); radii estimated for a slim body (--body-scale to change).
# (name, bone, start, end, radius); the R_ ones are mirrored from the L_ ones.
BODY_CAPSULES = (
    ("S2S_neck", "C_Neck", (0.0, -0.03, 1.44), (0.0, -0.03, 1.52), 0.050),
    ("S2S_chest", "C_Chest", (-0.08, 0.0, 1.31), (0.08, 0.0, 1.31), 0.105),
    ("S2S_waist", "C_Spine1", (-0.06, -0.01, 1.14), (0.06, -0.01, 1.14), 0.090),
    ("S2S_hips", "C_Hips", (-0.08, -0.03, 0.98), (0.08, -0.03, 0.98), 0.110),
    ("S2S_L_thigh", "L_Thigh", (-0.11, -0.02, 0.90), (-0.14, -0.05, 0.56), 0.070),
    ("S2S_L_upperarm", "L_Biceps", (-0.154, -0.047, 1.398), (-0.341, -0.067, 1.202), 0.045),
)


def body_capsules(sf_world: Dict[str, np.ndarray], hair: Hair, scale: float = 1.0,
                  margin: float = 0.025) -> Tuple[List[smpcloth.Capsule], Dict[str, float]]:
    """Capsules for the neck, chest, waist, hips, thighs and upper arms (BODY_CAPSULES, radii x `scale`), each shrunk so
    that no simulated particle starts inside it (as head_capsule), left out when that leaves under 2 cm or its bone
    is not in the skeleton. Returns (capsules, {name: radius or a reason})."""
    specs = []
    for name, bone, a, b, r in BODY_CAPSULES:
        specs.append((name, bone, a, b, r))
        if bone.startswith("L_"):
            specs.append((name.replace("_L_", "_R_"), "R_" + bone[2:], (-a[0], a[1], a[2]), (-b[0], b[1], b[2]), r))
    roots = set(hair.host_of_root)
    pts = [np.asarray(x.world[:3, 3], float) for x in hair.bones if x.name not in roots] + \
          [np.asarray(x.tip, float) for x in hair.bones if x.tip is not None]
    out, report = [], {}
    for name, bone, a, b, r in specs:
        if bone not in sf_world:
            report[name] = f"no bone {bone}"
            continue
        a, b = np.asarray(a, float), np.asarray(b, float)
        radius = r * scale
        for p in pts:
            t = float(np.clip((p - a) @ (b - a) / ((b - a) @ (b - a)), 0.0, 1.0))
            radius = min(radius, float(np.linalg.norm(p - (a + t * (b - a)))) - margin)
        if radius < 0.02:
            report[name] = "left out: the hair starts inside it"
            continue
        o = np.asarray(sf_world[bone], float)[:3, 3]
        out.append(smpcloth.Capsule(name, bone, a - o, b - o, radius))
        report[name] = round(radius, 4)
    return out, report


def face_capsule(sf_world: Dict[str, np.ndarray], hair: Hair, margin: float = 0.024) -> Optional[smpcloth.Capsule]:
    """A capsule just behind the face (chin to brow) on C_Head, so front locks hang beside / in front of the face
    instead of through it (2026-11-02: locks crossed the cheek and eye; the skull capsule does not reach the face).
    From the cloth skeleton: C_Head z 1.632, the eyes 4 cm above and 8 cm in front of it, the chin 6 cm below and
    10 cm in front. Shrunk like head_capsule; None when that leaves under 3 cm."""
    w = sf_world[SF_HEAD]
    start, end, radius = np.array([0.0, 0.035, -0.065]), np.array([0.0, 0.035, 0.03]), 0.055
    roots = set(hair.host_of_root)
    pts = [b.world[:3, 3] for b in hair.bones if b.name not in roots] + [b.tip for b in hair.bones
                                                                         if b.tip is not None]
    for p in pts:
        q = np.asarray(p, float) - w[:3, 3]
        t = float(np.clip((q - start) @ (end - start) / ((end - start) @ (end - start)), 0.0, 1.0))
        radius = min(radius, float(np.linalg.norm(q - (start + t * (end - start)))) - margin)
    return smpcloth.Capsule("S2S_face", SF_HEAD, start, end, radius) if radius >= 0.03 else None


def on_face_bones(hair: Hair, ref_points: np.ndarray, ref_weights: List[List[Tuple[str, float]]], k: int = 4,
                  host: str = None) -> Hair:
    """The hair with each vertex's `host` (C_Head) weight spread over face bones as a vanilla facebones hair skins
    the same spot: the face-bone weights of the k nearest reference vertices (ref_points model space; only those
    mostly on face bones), blended by inverse distance. The scalp then follows the face-bone shape the character was
    made with (one face bone does not). At most MAX_WEIGHTS weights per vertex, renormalised."""
    host = host or SF_HEAD
    keep, refw = [], []
    for i, ws in enumerate(ref_weights):
        face = {b: w for b, w in ws if b.lower().startswith("facebone_") and w > 0}
        tot = sum(face.values())
        if tot >= 0.5 * max(sum(w for _b, w in ws), 1e-9):
            keep.append(i)
            refw.append({b: w / tot for b, w in face.items()})
    if not keep:
        raise HairError("no reference vertex on face bones")
    ref = np.asarray(ref_points, float)[keep]
    shapes = []
    for sh in hair.shapes:
        pos = np.asarray(sh.positions, float)
        need = [i for i, vw in enumerate(sh.weights) if any(b == host for b, _w in vw)]
        near = {}
        rr = (ref * ref).sum(1)
        kk = min(k, len(ref))
        for c in range(0, len(need), 512):                      # nearest reference vertices, a block at a time
            idx = need[c:c + 512]
            p = pos[idx]
            d2 = np.maximum((p * p).sum(1)[:, None] + rr[None, :] - 2.0 * p @ ref.T, 0.0)
            nn = np.argpartition(d2, kk - 1, axis=1)[:, :kk]
            for row, i in enumerate(idx):
                near[i] = [(int(j), float(np.sqrt(d2[row, j]))) for j in nn[row]]
        ws_out = []
        for i, vw in enumerate(sh.weights):
            if i not in near:
                ws_out.append(list(vw))
                continue
            acc: Dict[str, float] = {}
            for b, w in vw:
                if b != host:
                    acc[b] = acc.get(b, 0.0) + w
            hw = sum(w for b, w in vw if b == host)
            inv = [(j, 1.0 / max(dist, 1e-4)) for j, dist in near[i]]
            tot = sum(x for _j, x in inv)
            for j, x in inv:
                for b, w in refw[j].items():
                    acc[b] = acc.get(b, 0.0) + hw * w * x / tot
            top = sorted(acc.items(), key=lambda kv: -kv[1])[:MAX_WEIGHTS]
            s = sum(w for _b, w in top)
            ws_out.append([(b, w / s) for b, w in top])
        shapes.append(HairShape(sh.name, sh.positions, sh.normals, sh.tangents, sh.uvs, sh.triangles, ws_out,
                                sh.shader_ref, sh.alpha_ref, sh.block))
    return Hair(shapes, hair.bones, hair.host_of_root, dict(hair.report, face_bones="spread"))


def _mesh(sh: HairShape, bones: List[str], back_faces: bool):
    """(SfMesh, per-vertex weights) of a shape: geometry through convert_static.shape_to_mesh (metres already), then
    4 weights per vertex as (index into `bones`, u16) summing to 65535."""
    from . import convert_static, sfmesh
    from .skyrimconvert import with_back_faces
    s = nifmod.Fo4Shape(sh.name, (0.0, 0.0, 0.0), (1, 0, 0, 0, 1, 0, 0, 0, 1), 1.0, sh.shader_ref, sh.alpha_ref, -1,
                        [tuple(map(float, p)) for p in sh.positions], list(sh.uvs),
                        [tuple(map(float, v)) for v in sh.normals], [tuple(map(float, v)) for v in sh.tangents], [],
                        list(sh.triangles), True)
    weights = list(sh.weights)
    if back_faces:
        d = with_back_faces(s)
        if d is not None:
            s, weights = d, weights * 2
    m = convert_static.shape_to_mesh(s, 1.0)
    idx = {b: i for i, b in enumerate(bones)}
    m.weights_per_vertex = MAX_WEIGHTS
    out = []
    for vw in weights:
        q = [(idx[b], int(round(w * 65535))) for b, w in vw]
        q[0] = (q[0][0], q[0][1] + 65535 - sum(w for _b, w in q))
        q += [(0, 0)] * (MAX_WEIGHTS - len(q))
        out += q
    m.weights = out
    return m


def nif_files(hair: Hair, materials: List[Optional[str]], cloth_blob: Optional[bytes],
              sf_world: Dict[str, np.ndarray], out_name: str,
              back_faces: Optional[List[bool]] = None) -> Dict[str, bytes]:
    """{"meshes/<out_name>.nif": ..., "geometries/<a>/<b>.mesh": ...}: the skinned hair with the cloth on its root
    (cloth_blob None: no physics; materials[i] None = shape left out). Binds are the inverses of the bones' rest world transforms (the cloth
    skeleton's), the convention of the game's own hairs (Eris long curls: bind @ world = identity to 1e-6)."""
    from . import convert_static, sfmesh, sfnif
    world = dict(sf_world)
    for b in hair.bones:
        world[b.name] = b.world
    files, skinned = {}, []
    for i, sh in enumerate(hair.shapes):
        if materials[i] is None:
            continue
        bones = sorted({b for vw in sh.weights for b, _w in vw}, key=lambda b: (b != SF_HEAD, b))
        m = _mesh(sh, bones, bool(back_faces[i]) if back_faces else False)
        data = sfmesh.serialize(m)
        d, f = convert_static.mesh_file_path(data)
        files[f"geometries/{d}/{f}.mesh"] = data
        binds = []
        for b in bones:
            if b not in world:
                raise HairError(f"bone {b} has no rest pose")
            inv = np.linalg.inv(world[b])
            pts = np.array([sh.positions[k] for k, vw in enumerate(sh.weights) if any(x == b for x, _w in vw)])
            if len(pts):
                loc = pts @ inv[:3, :3].T + inv[:3, 3]
                c = (loc.min(0) + loc.max(0)) / 2
                r = float(np.linalg.norm(loc - c, axis=1).max())
            else:
                c, r = np.zeros(3), 0.0
            binds.append((tuple(map(float, c)) + (r,), tuple(map(float, inv[:3, :3].reshape(9))),
                          tuple(map(float, inv[:3, 3])), 1.0))
        skinned.append(sfnif.SkinnedShape(sh.name or f"Shape{i}".encode(), f"{d}\\{f}".encode(),
                                          len(m.triangles) * 3, len(m.positions), materials[i],
                                          [b.encode("latin-1") for b in bones], binds))
    if not skinned:
        raise HairError("no shape with a material")
    n = sfnif.build_skinned_nif(out_name.rsplit("/", 1)[-1].encode(), skinned)
    if cloth_blob is not None:
        sfnif.add_cloth(n, cloth_blob)
    files[f"meshes/{out_name}.nif"] = nifmod.serialize(n)
    return files
