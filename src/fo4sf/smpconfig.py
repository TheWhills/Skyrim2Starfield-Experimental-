"""HDT-SMP / Faster HDT-SMP physics configs (Skyrim): read the XML, resolve its defaults, and describe what a converted
mesh would need in Starfield. Read-only; for the physics plan in docs/armor/animation-port.md.

Format knowledge comes from the files themselves and from the schema FSMP ships, FSMPV/hdtSMP64.xsd (MIT licence,
DaymareOn; read 2026-10-19 from FSMP 4.1.1). No FSMP / HDT-SMP code (GPL) was read or copied.

What the schema documents and real files show (verified 2026-10-19 on KS Hairdos SMP and Cloaks of Skyrim HDT-SMP):
* A worn NIF names its config with an NiStringExtraData called "HDT Skinned Mesh Physics Object" whose value is a
  Data-relative path (seen: "SKSE\\Plugins\\hdtSkinnedMeshConfigs\\cloakF.xml", "Data\\meshes\\...\\Ominous.xml").
* <system> is read in document order. <bone-default>, <generic-constraint-default>, <stiffspring-constraint-default>,
  <conetwist-constraint-default>, <per-vertex-shape-default>, <per-triangle-shape-default> without a name set the
  default ("" name) for the elements that follow; with a name they are templates picked by template="..."; extends=
  inherits from another default. <constraint-group> is only a container (its defaults are not scoped).
* <bone name>: a rigid body on that skeleton node. mass 0 or unset = kinematic (follows the animation); mass > 0 =
  simulated. A bone used by a constraint but never declared is created with the bone-default current at that point.
  A second declaration of a bone is ignored.
* Constraints between bodyA and bodyB: generic-constraint (6-DOF spring, per-axis linear / angular limits, stiffness,
  damping, equilibrium; lower > upper = free axis), stiffspring-constraint (distance spring), conetwist-constraint.
* Collision: <per-vertex-shape name> / <per-triangle-shape name> turn the NIF shape with that name into spheres per
  vertex / triangles; tags plus can-/no-collide-with-tag/-bone filter pairs. Bones may also carry primitive shapes
  (box, sphere, capsule, hull, cylinder, compound).
* Numbers may use a comma decimal separator ("0,1"); the runtime accepts both.
* Simulation is Bullet rigid bodies; the skinned mesh only moves through its bones.
"""
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Dict, List, Optional

PHYSICS_EXTRA = b"HDT Skinned Mesh Physics Object"

KINDS = {"bone": "bone-default",
         "generic-constraint": "generic-constraint-default",
         "stiffspring-constraint": "stiffspring-constraint-default",
         "conetwist-constraint": "conetwist-constraint-default",
         "per-vertex-shape": "per-vertex-shape-default",
         "per-triangle-shape": "per-triangle-shape-default"}
DEFAULTS = {v: k for k, v in KINDS.items()}
CONSTRAINTS = ("generic-constraint", "stiffspring-constraint", "conetwist-constraint")
SHAPES = ("per-vertex-shape", "per-triangle-shape")
LISTS = ("can-collide-with-tag", "no-collide-with-tag", "can-collide-with-bone", "no-collide-with-bone")
ALIASES = {"prenetration": "penetration"}


class SmpError(ValueError):
    pass


def flex(s: str) -> float:
    """A schema 'flexFloat': dot or comma decimal separator."""
    return float(s.strip().replace(",", "."))


def _value(e: ET.Element):
    """One property element: vector (x/y/z[/w] attributes), nested element (frames, shapes) or scalar text."""
    a = e.attrib
    if "x" in a and "y" in a and "z" in a:
        return tuple(flex(a[k]) for k in ("x", "y", "z", "w") if k in a)
    if len(e):
        return _props(e)
    t = (e.text or "").strip()
    if t.lower() in ("true", "false"):
        return t.lower() == "true"
    try:
        return flex(t)
    except ValueError:
        return t


def _props(e: ET.Element) -> Dict:
    out = {}
    if e.tag == "shape":
        out["type"] = e.get("type")
    for c in e:
        if not isinstance(c.tag, str):
            continue
        k = ALIASES.get(c.tag, c.tag)
        if k in LISTS:
            out.setdefault(k, []).append((c.text or "").strip())
        elif k == "weight-threshold":
            out.setdefault(k, {})[c.get("bone")] = flex(c.text or "0")
        elif k == "shape":
            out.setdefault("shapes", []).append(_props(c))
        else:
            out[k] = _value(c)
    return out


def _merge(base: Dict, over: Dict) -> Dict:
    out = dict(base)
    for k, v in over.items():
        if k in LISTS and k in out:
            out[k] = out[k] + v
        elif k == "weight-threshold" and k in out:
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def parse(data: bytes) -> Dict:
    """{"bones": {name: props + dynamic}, "constraints": [...], "shapes": [...], "features": Counter, "warnings"}."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise SmpError(f"not XML: {e}")
    if root.tag != "system":
        raise SmpError(f"root is <{root.tag}>, not <system>")
    defaults = {k: {"": {}} for k in KINDS}
    cfg = {"bones": {}, "constraints": [], "shapes": [], "features": Counter(), "warnings": []}

    def default(kind, name=""):
        d = defaults[kind].get(name)
        if d is None:
            cfg["warnings"].append(f"{kind} template {name!r} not defined")
            return dict(defaults[kind][""])
        return d

    def bone(name, props=None, template=""):
        if name in cfg["bones"]:
            if props is not None:
                cfg["warnings"].append(f"bone {name!r} declared twice (second ignored)")
            return
        p = _merge(default("bone", template), props or {})
        p["dynamic"] = float(p.get("mass", 0) or 0) > 0
        p["declared"] = props is not None
        cfg["bones"][name] = p

    def walk(parent):
        for e in parent:
            if not isinstance(e.tag, str):
                continue
            tag = e.tag
            cfg["features"][tag] += 1
            if tag in DEFAULTS:
                kind = DEFAULTS[tag]
                # a redefinition starts from scratch unless it extends= another default (unverified: whether the
                # runtime instead merges an unnamed redefinition into the previous one)
                base = default(kind, e.get("extends")) if e.get("extends") is not None else {}
                defaults[kind][e.get("name") or ""] = _merge(base, _props(e))
            elif tag == "bone":
                bone(e.get("name"), _props(e), e.get("template") or "")
            elif tag in CONSTRAINTS:
                a, b = (e.get("bodyA") or "").strip(), (e.get("bodyB") or "").strip()
                for n in (a, b):
                    bone(n)
                p = _merge(default(tag, e.get("template") or ""), _props(e))
                cfg["constraints"].append({"type": tag, "a": a, "b": b, **p})
            elif tag in SHAPES:
                p = _merge(default(tag, e.get("template") or ""), _props(e))
                cfg["shapes"].append({"kind": tag, "name": e.get("name"), **p})
            elif tag == "constraint-group":
                walk(e)
            elif tag in ("pattern", "pattern-default", "repeat"):
                cfg["warnings"].append(f"<{tag}> not expanded by this reader")
            elif tag == "shape":
                cfg["features"]["shape:" + (e.get("type") or "?")] += 1
            else:
                cfg["warnings"].append(f"unknown element <{tag}>")
    walk(root)
    for b in cfg["bones"].values():
        for s in b.get("shapes", []):
            cfg["features"]["bone-shape:" + (s.get("type") or "?")] += 1
    return cfg


def chains(cfg: Dict) -> List[Dict]:
    """Connected groups of constrained bones: dynamic and kinematic members, longest dynamic run from an anchor, and
    whether the group is a tree (chains / branches) or has loops (a net, closer to cloth)."""
    adj: Dict[str, set] = {}
    edges = set()
    for c in cfg["constraints"]:
        a, b = c["a"], c["b"]
        if a == b:
            continue
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
        edges.add(frozenset((a, b)))
    bones, seen, out = cfg["bones"], set(), []
    for start in sorted(adj):
        if start in seen:
            continue
        comp, stack = set(), [start]
        while stack:
            n = stack.pop()
            if n in comp:
                continue
            comp.add(n)
            stack += adj[n] - comp
        seen |= comp
        dyn = sorted(n for n in comp if bones.get(n, {}).get("dynamic"))
        anchors = sorted(n for n in comp if not bones.get(n, {}).get("dynamic"))
        n_edges = sum(1 for e in edges if e <= comp)
        # longest run of dynamic bones reachable from an anchor (BFS depth over dynamic members)
        depth, frontier, visited = 0, set(anchors), set(anchors)
        while True:
            nxt = {m for n in frontier for m in adj[n] if m not in visited and m in dyn}
            if not nxt:
                break
            depth += 1
            visited |= nxt
            frontier = nxt
        out.append({"bones": len(comp), "dynamic": len(dyn), "anchors": anchors, "depth": depth,
                    "loops": n_edges - (len(comp) - 1), "unanchored": sorted(set(dyn) - visited)})
    return out


def needs(cfg: Dict) -> List[str]:
    """What a Starfield equivalent has to provide, as short feature names."""
    f, out = cfg["features"], []
    groups = chains(cfg)
    if any(g["dynamic"] for g in groups):
        out.append("bone_chains")
    if any(g["loops"] > 0 and g["dynamic"] for g in groups):
        out.append("bone_net")
    if any(b["dynamic"] and not any(b["name"] in (c["a"], c["b"]) for c in cfg["constraints"])
           for b in ({"name": k, **v} for k, v in cfg["bones"].items())):
        out.append("free_bodies")
    for k in ("stiffspring-constraint", "conetwist-constraint", "per-vertex-shape", "per-triangle-shape"):
        if f.get(k):
            out.append(k.replace("-constraint", "").replace("-", "_"))
    if any(k.startswith("bone-shape:") for k in f):
        out.append("bone_shapes")
    if any(c.get(k) for c in cfg["constraints"] for k in ("linearMotors", "angularMotors")):
        out.append("motors")
    if any(w.startswith("<pattern") or w.startswith("<repeat") for w in cfg["warnings"]):
        out.append("patterns")
    return out


def summary(cfg: Dict) -> Dict:
    bones = cfg["bones"]
    dyn = [k for k, v in bones.items() if v["dynamic"]]
    ctypes = Counter(c["type"] for c in cfg["constraints"])
    ang = [c for c in cfg["constraints"] if c["type"] == "generic-constraint"]

    def rng(key, i):
        vals = [c[key][i] for c in ang if isinstance(c.get(key), tuple) and len(c[key]) > i]
        return [round(min(vals), 3), round(max(vals), 3)] if vals else None
    return {"bones": len(bones), "dynamic": len(dyn), "kinematic": len(bones) - len(dyn),
            "constraints": dict(ctypes), "chains": chains(cfg),
            "shapes": dict(Counter(s["kind"] for s in cfg["shapes"])),
            "shape_names": [s["name"] for s in cfg["shapes"]],
            "masses": sorted({round(float(v.get("mass", 0)), 4) for v in bones.values() if v["dynamic"]}),
            "angular_limit_x": rng("angularUpperLimit", 0), "angular_stiffness_x": rng("angularStiffness", 0),
            "needs": needs(cfg), "warnings": cfg["warnings"][:20]}


def nif_physics_paths(n) -> List[str]:
    """Config paths named by a Skyrim NIF's "HDT Skinned Mesh Physics Object" NiStringExtraData blocks (verified
    layout on SSE files: name string index u32, value string index u32)."""
    import struct
    out = []
    for i, blk in enumerate(n.blocks):
        if n.type_of(i) != "NiStringExtraData" or len(blk) < 8:
            continue
        name, val = struct.unpack_from("<2I", blk)
        if name < len(n.strings) and n.strings[name] == PHYSICS_EXTRA and val < len(n.strings):
            out.append(n.strings[val].decode("latin-1"))
    return out


def data_relative(path: str) -> str:
    """Normalise a config path to lower-case, backslash, Data-relative form."""
    p = path.replace("/", "\\").strip().lower()
    while p.startswith("\\"):
        p = p[1:]
    if p.startswith("data\\"):
        p = p[5:]
    return p


def check_mesh(cfg: Dict, shape_names: List[str], skin_bones: List[str], skeleton: Optional[set] = None) -> Dict:
    """Does a NIF provide what its config names? Collision shapes by NIF shape name; physics bones either in the
    NIF's skin or (when given) on the actor skeleton; extra (non-skeleton) bones the converted mesh must carry."""
    shapes = set(shape_names)
    have = set(skin_bones) | (skeleton or set())
    named = [s["name"] for s in cfg["shapes"]]
    return {"shapes_found": [s for s in named if s in shapes],
            "shapes_missing": [s for s in named if s not in shapes],
            "bones_missing": sorted(b for b in cfg["bones"] if b not in have) if skeleton is not None else None,
            "extra_bones": sorted(b for b in cfg["bones"] if skeleton is not None and b not in skeleton
                                  and b in skin_bones)}
