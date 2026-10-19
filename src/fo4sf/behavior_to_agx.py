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
     anything else (blends, selectors, pose matching, cyclic blend transitions, ...) -> an empty state, reported
  transitions (per state and wildcard) -> links into the target node: Event (event name), Condition (expression,
     rewritten in the .agx spelling), Blend Time (hkbBlendingTransitionEffect duration @80, 0.2 s when 0 / absent);
     a wildcard transition becomes a link from every other state (no wildcard node is known in .agx)
  start state -> first node (how .agx marks a default state is unverified)
Not translated yet (reported): blend trees and their variable bindings, modifiers (look-at, foot IK, ragdoll,
timers, expressions), clip triggers (they belong in the clip's .afx), nested-state transitions.
Supported hypotheses until a translated graph runs in game: the event / variable names (Skyrim's are kept; the
engine <-> graph interface map comes from the Starfield survey), the condition spelling (`!greaterthan!`,
`!ampersand!` and `|` seen in shipped graphs; `!lessthan!` assumed by analogy).
"""
import re
from collections import Counter
from typing import Dict, Optional

WRAPPERS = {"hkbModifierGenerator": "generator", "BSiStateTaggingGenerator": "default", "BSSynchronizedClipGenerator":
            "clip", "BSOffsetAnimationGenerator": "default", "hkbBehaviorReferenceGenerator": None}
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
    def __init__(self, b: Dict, reader=None):
        self.b, self.N, self.E = b, b["nodes"], b["events"]
        self.r = reader
        self.report = {"states": 0, "clip_states": 0, "machines": 0, "empty_states": Counter(), "modifiers": Counter(),
                       "links": 0, "wildcard_links": 0, "events": Counter(), "conditions": 0, "blend_default": 0,
                       "tags": {}}

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
            if c in ("hkbClipGenerator", "hkbStateMachine"):
                return o, mods
            if c not in WRAPPERS:
                return o, mods
            gens = [ch for ch in n["children"] if self.N[ch]["class"] not in ("hkbVariableBindingSet",)]
            mods += [self.N[ch]["class"] for ch in gens if "Modifier" in self.N[ch]["class"]]
            nxt = [ch for ch in gens if "Modifier" not in self.N[ch]["class"]]
            o = nxt[0] if nxt else None
        return o, mods

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
            if c == "hkbClipGenerator":
                tag = self.N[gen].get("name") or st.get("name")
                nodes.append({"kind": "anim", "tag": tag})
                self.report["clip_states"] += 1
                self.report["tags"][tag] = self.N[gen].get("animation")
            elif c == "hkbStateMachine":
                nodes.append({"kind": "sm", "name": self.N[gen].get("name") or st.get("name"),
                              "graph": self.machine(gen)})
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


def translate(b: Dict, machine=None, name: str = "Translated.agx", reader=None):
    """(.agx model, report) for the state machine object `machine` (default: the graph's root, unwrapped)."""
    t = Translator(b, reader)
    root = machine
    if root is None:
        root, _ = t._unwrap(b["root"])
    if t.N.get(root, {}).get("class") != "hkbStateMachine":
        raise ValueError(f"not a state machine: {t.N.get(root, {}).get('class')}")
    g = t.machine(root)
    g["name"] = "Data\\Meshes\\AnimTextData\\Tables\\Graphs\\" + name
    rep = t.report
    rep["empty_states"], rep["modifiers"] = dict(rep["empty_states"]), dict(rep["modifiers"].most_common(20))
    rep["events"] = dict(rep["events"].most_common())
    return g, rep


def find_machine(b: Dict, name: str):
    for o, n in b["nodes"].items():
        if n["class"] == "hkbStateMachine" and n.get("name") == name:
            return o
    return None
