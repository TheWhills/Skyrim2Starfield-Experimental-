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
        st = s.skin_transform
        if st is not None:
            rs, ts = np.array(st.rotation, float).reshape(3, 3), np.array(st.translation, float)
            to_model = lambda v: ((np.asarray(v, float) - ts) @ rs) / st.scale
            rot = lambda v: np.asarray(v, float) @ rs
        else:
            to_model = rot = lambda v: np.asarray(v, float)
        pos = np.array([place.point(to_model(v)) for v in s.positions])
        nrm = np.array([rot(v) for v in s.normals]) if s.normals else np.zeros((0, 3))
        tan = np.array([rot(v) for v in s.tangents]) if s.tangents else np.zeros((0, 3))
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


def head_capsule(sf_world: Dict[str, np.ndarray], hair: Hair, margin: float = 0.004) -> smpcloth.Capsule:
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
