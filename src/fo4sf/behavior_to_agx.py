"""Prototype: translate a Skyrim behaviour graph (skyrimbehavior.read) into a Starfield .agx graph model
(agx_write.write), and report what did and did not carry over.

Mapping (both are nested state machines whose transitions fire on events, with conditions and blend times):
  hkbStateMachine                -> a graph (the file, or NT_STATE_MACHINE_EMBEDDED with a nested <graph>)
  hkbStateMachineStateInfo       -> one node of that graph; its generator decides the node:
     hkbClipGenerator             -> NT_ANIMATION_NODE, TagName = the clip generator's name (hkx_to_af writes the
                                     converted clip's .afx with the same tag, so they match by construction)
     hkbStateMachine              -> nested state machine
     wrappers (hkbModifierGenerator, BSiStateTaggingGenerator, BSIsActive / BSSynchronizedClipGenerator, ...)
                                  -> unwrapped to the generator they hold; the modifiers are reported, not translated
     hkbBlenderGenerator          -> NT_BLEND_TREE_EMBEDDED whose output (node 0) is an NT_BLEND_NODE: variable =
                                     the variable bound to blendParameter, range = the children's weights, one
                                     input per child with a triangle curve (weight 1 at its own parameter, 0 at its
                                     neighbours': the Skyrim blender's linear interpolation)
     hkbManualSelectorGenerator   -> NT_BLEND_TREE_EMBEDDED whose output is an NT_SWITCH_NODE on the variable bound
                                     to selectedGeneratorIndex (Variable Type Variable), one input per choice
     (inside a tree, children are translated the same way: clips, nested machines, nested blends / selectors)
     anything else (pose matching, cyclic blend transitions, ...) -> an empty state, reported
  transitions (per state and wildcard) -> links into the target node: Event (event name), Condition (expression,
     rewritten in the .agx spelling), Blend Time (hkbBlendingTransitionEffect duration @80, 0.2 s when 0 / absent);
     a wildcard transition becomes a link from every other state (no wildcard node is known in .agx)
  start state -> first node (how .agx marks a default state is unverified)
  hkbBehaviorReferenceGenerator -> NT_GRAPH_REF naming the referenced behaviour (QuadrupedBehavior)
  a state machine / blend / selector used from more than one place -> its own graph (file), referenced by name with
     NT_GRAPH_REF where it is used (.agx has no in-file instancing; copying it everywhere blew the dragon graph up
     from 66 to 742 machines). A blend tree can be a whole graph: Player_Melee's root is one.
Not translated yet (reported): blend-weight variables that are not bound, modifiers (look-at, foot IK, ragdoll,
timers, expressions), clip triggers (they belong in the clip's .afx), nested-state transitions.
Supported hypotheses until a translated graph runs in game: the event / variable names (Skyrim's are kept; the
engine <-> graph interface map comes from the Starfield survey), the condition spelling (`!greaterthan!`,
`!ampersand!` and `|` seen in shipped graphs; `!lessthan!` assumed by analogy).
"""
import re
from collections import Counter
from typing import Dict, Optional

WRAPPERS = {"hkbModifierGenerator": "generator", "BSiStateTaggingGenerator": "default", "BSSynchronizedClipGenerator":
            "clip", "BSOffsetAnimationGenerator": "default"}
TERMINAL = ("hkbClipGenerator", "hkbStateMachine", "hkbBlenderGenerator", "hkbManualSelectorGenerator",
            "hkbBehaviorReferenceGenerator")
EFFECT_DURATION = 80


def condition(expr: Optional[str]) -> str:
    """Skyrim expression -> the .agx spelling seen in Starfield's graphs."""
    if not expr:
        return ""
    s = expr.replace("&&", " !ampersand! ").replace("||", " | ").replace("==", "=")
    s = re.sub(r">=", " !greaterthan!= ", s)
    s = re.sub(r"<=", " !lessthan!= ", s)
    s = s.replace(">", " !greaterthan! ").replace("<", " !lessthan! ")
    return re.sub(r"\s+", " ", s).strip()


class Translator:
    def __init__(self, b: Dict, reader=None, prefix: str = "Graph"):
        self.b, self.N, self.E = b, b["nodes"], b["events"]
        self.r = reader
        self.prefix = re.sub(r"[^A-Za-z0-9_]", "", prefix) or "Graph"
        uses = Counter()
        for n in self.N.values():                        # how often each (unwrapped) generator is used
            for ch in n["children"]:
                g, _m = self._unwrap(ch) if self.N[ch]["class"] in WRAPPERS or self.N[ch]["class"] in TERMINAL \
                    else (None, [])
                if g is not None:
                    uses[g] += 1
        self.shared = {g for g, k in uses.items() if k > 1 and self.N[g]["class"] in
                       ("hkbStateMachine", "hkbBlenderGenerator", "hkbManualSelectorGenerator")}
        self.graph_names, self.pending, self.extra = {}, [], {}
        self.report = {"states": 0, "clip_states": 0, "machines": 0, "empty_states": Counter(), "modifiers": Counter(),
                       "links": 0, "wildcard_links": 0, "events": Counter(), "conditions": 0, "blend_default": 0,
                       "tags": {}, "blends": 0, "switches": 0, "blends_without_variable": 0, "graph_refs": 0,
                       "behavior_refs": Counter()}

    def _blend(self, effect) -> float:
        if effect is not None and self.r is not None and self.N.get(effect, {}).get("class") == "hkbBlendingTransitionEffect":
            d, = self.r.u("<f", effect, EFFECT_DURATION)
            if 0 < d < 10:
                return round(float(d), 3)
        self.report["blend_default"] += 1
        return 0.2

    def _unwrap(self, o):
        """(final generator object, [modifier classes passed])."""
        mods, seen = [], set()
        while o is not None and o in self.N and o not in seen:
            seen.add(o)
            n = self.N[o]
            c = n["class"]
            if c in TERMINAL:
                return o, mods
            if c not in WRAPPERS:
                return o, mods
            gens = [ch for ch in n["children"] if self.N[ch]["class"] not in ("hkbVariableBindingSet",)]
            mods += [self.N[ch]["class"] for ch in gens if "Modifier" in self.N[ch]["class"]]
            nxt = [ch for ch in gens if "Modifier" not in self.N[ch]["class"]]
            o = nxt[0] if nxt else None
        return o, mods

    def _bound(self, o, member):
        for b in self.N[o].get("bindings", []):
            if b["member"] == member and b["kind"] == "variable" and 0 <= b["variable"] < len(self.b["variables"]):
                return self.b["variables"][b["variable"]]
        return ""

    @staticmethod
    def _hats(params):
        """Triangle curves: input k weighs 1 at its parameter and falls to 0 at its neighbours' parameters."""
        order = sorted(range(len(params)), key=lambda k: params[k])
        curves = [None] * len(params)
        for pos, k in enumerate(order):
            pts = []
            if pos > 0:
                pts.append((params[order[pos - 1]], 0.0))
            pts.append((params[k], 1.0))
            if pos < len(order) - 1:
                pts.append((params[order[pos + 1]], 0.0))
            curves[k] = pts
        return curves

    def _ref_name(self, gen):
        if gen not in self.graph_names:
            base = re.sub(r"[^A-Za-z0-9_]", "", self.N[gen].get("name") or "") or f"Node{gen}"
            name = f"{self.prefix}_{base}"
            while name in self.graph_names.values():
                name += "_"
            self.graph_names[gen] = name
            self.pending.append(gen)
        return self.graph_names[gen]

    def _ref_node(self, gen, here):
        """An NT_GRAPH_REF for a shared generator (not the one being emitted as a graph root), else None."""
        if gen in self.shared and gen != here:
            self.report["graph_refs"] += 1
            return {"kind": "ref", "graph_ref": self._ref_name(gen)}
        if self.N.get(gen, {}).get("class") == "hkbBehaviorReferenceGenerator":
            beh = (self.N[gen].get("behavior") or "").replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
            self.report["behavior_refs"][beh] += 1
            return {"kind": "ref", "graph_ref": beh}
        return None

    def _tree_node(self, o, nodes, links, here=None) -> int:
        """Translate generator o into a node of a blend tree (data-flow) graph; returns its index."""
        gen, mods = self._unwrap(o)
        self.report["modifiers"].update(mods)
        n = self.N.get(gen, {})
        c = n.get("class")
        idx = len(nodes)
        ref = self._ref_node(gen, here)
        if ref is not None:
            nodes.append(ref)
            return idx
        if c == "hkbClipGenerator":
            nodes.append({"kind": "anim", "tag": n.get("name")})
            self.report["clip_states"] += 1
            self.report["tags"][n.get("name")] = n.get("animation")
        elif c == "hkbStateMachine":
            nodes.append({"kind": "sm", "name": n.get("name"), "graph": self.machine(gen)})
        elif c == "hkbBlenderGenerator":
            kids = [self.N[ch] for ch in n.get("blend_children", []) if ch in self.N]
            params = [k.get("weight", 0.0) for k in kids]
            var = self._bound(gen, "blendParameter")
            if not var:
                self.report["blends_without_variable"] += 1
            lo, hi = (min(params), max(params)) if params and max(params) > min(params) else (0.0, 1.0)
            nodes.append({"kind": "blend", "name": n.get("name") or "", "variable": var, "range": (lo, hi),
                          "inputs": [f"input{i}" for i in range(len(kids))],
                          "curves": self._hats(params) if len(set(params)) == len(params) else None})
            self.report["blends"] += 1
            for i, k in enumerate(kids):
                child = self._tree_node(k.get("generator"), nodes, links)
                links.append((child, idx, {"data": True, "input": i}))
        elif c == "hkbManualSelectorGenerator":
            gens = [ch for ch in n["children"] if self.N[ch]["class"] not in ("hkbVariableBindingSet",)]
            var = self._bound(gen, "selectedGeneratorIndex")
            nodes.append({"kind": "switch", "name": n.get("name") or "", "variable": var,
                          "variable_type": "Variable" if var else "Event",
                          "inputs": [self.N[g].get("name") or f"case{i}" for i, g in enumerate(gens)]})
            self.report["switches"] += 1
            for i, g2 in enumerate(gens):
                child = self._tree_node(g2, nodes, links)
                links.append((child, idx, {"data": True, "input": i}))
        else:
            nodes.append({"kind": "empty"})
            self.report["empty_states"][c or "none"] += 1
        return idx

    def _machine_as_root(self, sm) -> Dict:
        self.shared.discard(sm)                         # emitting it here: no self-reference
        try:
            return self.machine(sm)
        finally:
            self.shared.add(sm)

    def machine(self, sm) -> Dict:
        n = self.N[sm]
        self.report["machines"] += 1
        states = [s for s in n["states"] if s in self.N]
        start = n["start_state"]
        states.sort(key=lambda s: self.N[s]["state_id"] != start)           # start state first
        index = {self.N[s]["state_id"]: i for i, s in enumerate(states)}
        nodes, links = [], []
        for s in states:
            st = self.N[s]
            self.report["states"] += 1
            gen, mods = self._unwrap(st.get("generator"))
            self.report["modifiers"].update(mods)
            c = self.N.get(gen, {}).get("class")
            ref = self._ref_node(gen, None)
            if ref is not None:
                nodes.append(ref)
            elif c == "hkbClipGenerator":
                tag = self.N[gen].get("name") or st.get("name")
                nodes.append({"kind": "anim", "tag": tag})
                self.report["clip_states"] += 1
                self.report["tags"][tag] = self.N[gen].get("animation")
            elif c == "hkbStateMachine":
                nodes.append({"kind": "sm", "name": self.N[gen].get("name") or st.get("name"),
                              "graph": self.machine(gen)})
            elif c in ("hkbBlenderGenerator", "hkbManualSelectorGenerator"):
                tnodes, tlinks = [], []
                self._tree_node(gen, tnodes, tlinks, here=gen)
                nodes.append({"kind": "blendtree", "name": self.N[gen].get("name") or st.get("name"),
                              "graph": {"type": "blendtree", "nodes": tnodes, "links": tlinks}})
            else:
                nodes.append({"kind": "empty"})
                self.report["empty_states"][c or "none"] += 1

        def add(frm, t):
            to = index.get(t["to_state"])
            if to is None:
                return
            ev = self.E[t["event"]] if 0 <= t["event"] < len(self.E) else ""
            props = {"event": ev, "condition": condition(t.get("condition_expr")), "blend": self._blend(t.get("effect"))}
            if props["condition"]:
                self.report["conditions"] += 1
            if ev:
                self.report["events"][ev] += 1
            links.append((frm, to, props))
            self.report["links"] += 1
        for i, s in enumerate(states):
            for t in (self.N.get(self.N[s].get("transitions"), {}).get("transitions") or []):
                add(i, t)
        for t in (self.N.get(n.get("wildcard"), {}).get("transitions") or []):
            for i in range(len(states)):
                if index.get(t["to_state"]) != i:
                    add(i, t)
                    self.report["wildcard_links"] += 1
        return {"nodes": nodes, "links": links}


GRAPH_DIR = "Data\\Meshes\\AnimTextData\\Tables\\Graphs\\"


def translate(b: Dict, machine=None, name: str = "Translated.agx", reader=None):
    """(.agx model, report) for the state machine object `machine` (default: the graph's root, unwrapped).
    report["extra_graphs"] = {graph name: model} holds the shared parts, each its own .agx (<name>.agx)."""
    t = Translator(b, reader, prefix=name.rsplit(".", 1)[0])
    root = machine
    if root is None:
        root, _ = t._unwrap(b["root"])
    if t.N.get(root, {}).get("class") != "hkbStateMachine":
        raise ValueError(f"not a state machine: {t.N.get(root, {}).get('class')}")
    t.shared.discard(root)
    g = t.machine(root)
    g["name"] = GRAPH_DIR + name
    while t.pending:
        gen = t.pending.pop(0)
        gname = t.graph_names[gen]
        if t.N[gen]["class"] == "hkbStateMachine":
            sub = t._machine_as_root(gen)
        else:
            nodes, links = [], []
            t._tree_node(gen, nodes, links, here=gen)
            sub = {"type": "blendtree", "nodes": nodes, "links": links}
        sub["name"] = GRAPH_DIR + gname + ".agx"
        t.extra[gname] = sub
    rep = t.report
    rep["empty_states"], rep["modifiers"] = dict(rep["empty_states"]), dict(rep["modifiers"].most_common(20))
    rep["events"], rep["behavior_refs"] = dict(rep["events"].most_common()), dict(rep["behavior_refs"])
    rep["extra_graphs"] = t.extra
    return g, rep


def find_machine(b: Dict, name: str):
    for o, n in b["nodes"].items():
        if n["class"] == "hkbStateMachine" and n.get("name") == name:
            return o
    return None
