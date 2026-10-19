"""Skyrim behaviour graphs (hk_2010.2.0-r1 .hkx, hkbBehaviorGraph): read the structure a translator / generator needs.

Layouts (64-bit Skyrim SE; offsets are the game's). Worked out 2026-10-19 from the data: pointer fixups inside each
object tell which field points to what (state list, generator, clip path, string arrays), and integers were checked
against those (a transition's toStateId names a state of its machine). Verified by `checks` over the 118 vanilla
behaviour graphs Pandora ships as templates (they carry 8 extra leading bytes per object: `bias`, detected per file
from hkRootLevelContainer's first pointer). Fields not listed here are not read.
  hkbNode (all generators / modifiers): variableBindingSet ptr @16, name char* @56
  hkbBehaviorGraph: rootGenerator @128, data (hkbBehaviorGraphData) @136
  hkbBehaviorGraphData: variableInfos @32, characterPropertyInfos @48, eventInfos @64, stringData @120
  hkbBehaviorGraphStringData: eventNames @16, attributeNames @32, variableNames @48, characterPropertyNames @64
  hkbStateMachine: eventToSendWhenStateOrTransitionChanges.id @72, startStateId @104, returnToPreviousStateEventId
    @108, randomTransitionEventId @112, transitionToNextHigherStateEventId @116, ...LowerStateEventId @120,
    syncVariableIndex @124, wrapAroundStateId u8 @132, maxSimultaneousTransitions i8 @133, startStateMode u8 @134,
    selfTransitionMode u8 @135, states (ptr array) @144, wildcardTransitions @160
  hkbStateMachineStateInfo: enterNotifyEvents @64, exitNotifyEvents @72, transitions @80, generator @88, name @96,
    stateId @104, probability f32 @108, enable u8 @112
  hkbStateMachineTransitionInfoArray: transitions (inline array of 72-byte records) @16; record: triggerInterval
    (enterEventId, exitEventId, enterTime, exitTime) @0, initiateInterval @16, transition (effect) ptr @32,
    condition ptr @40, eventId @48, toStateId @52, fromNestedStateId @56, toNestedStateId @60, priority i16 @64,
    flags i16 @66
  hkbClipGenerator: animationName @72, triggers @80, cropStart @88, cropEnd @92, startTime @96, playbackSpeed @100,
    enforcedDuration @104, userControlledTimeFraction @108, animationBindingIndex i16 @112, mode u8 @114,
    flags u8 @115
  hkbBlenderGenerator: blendParameter f32 @76, children (ptr array) @96;  hkbBlenderGeneratorChild: generator @48,
    weight f32 @64
  hkbBehaviorReferenceGenerator: behaviorName char* @72 (e.g. Behaviors\\QuadrupedBehavior.hkx)
  hkbVariableBindingSet: bindings (40-byte records: memberPath char* @0, variableIndex i32 @28, bindingType i8 @33)
Every other object is kept generically: its class, name (when it is an hkbNode) and the objects it points to, in
field order, so the whole tree can be walked.
"""
import struct
from typing import Dict, List, Optional

from . import hkpackfile

NODE_NAME, NODE_BINDINGS = 56, 16
TRANSITION_SIZE = 72
BINDING_SIZE = 40
SM_MODES = {0: "default", 1: "sync", 2: "random", 3: "chooser"}


class BehaviorError(ValueError):
    pass


class _Reader:
    def __init__(self, data: bytes):
        if data[:8] != hkpackfile.MAGIC:
            raise BehaviorError("not a Havok binary packfile")
        self.pf = hkpackfile.Packfile(data)
        if self.pf.ptr_size != 8:
            raise BehaviorError("only 64-bit (SE) behaviour files are read")
        s = self.pf.data_section
        self.s = s
        self.objs = sorted(self.pf.objects())
        self.cls = {o: c for o, c in self.objs}
        self.ends = {o: e for (o, _), e in zip(self.objs, [o for o, _ in self.objs[1:]] + [s.end])}
        self.ptr = {k: v for k, v in s.local.items()}
        self.ptr.update({k: v[1] for k, v in s.glob.items() if v[0] == self.pf.sections.index(s)})
        root = next((o for o, c in self.objs if c == "hkRootLevelContainer"), None)
        self.bias = 0
        if root is not None and root not in self.ptr and root + 8 in self.ptr:
            self.bias = 8                                  # Pandora's template copies

    def at(self, o, off):
        return o + self.bias + off

    def p(self, o, off) -> Optional[int]:
        return self.ptr.get(self.at(o, off))

    def u(self, fmt, o, off):
        return self.pf.unpack(fmt, self.at(o, off))

    def cstr(self, t) -> Optional[str]:
        if t is None:
            return None
        a = self.s.start + t
        e = self.pf.data.find(b"\0", a, min(a + 512, self.s.start + self.s.end))
        if e < a:
            return None
        b = self.pf.data[a:e]
        return b.decode("latin-1") if all(32 <= c < 127 for c in b) else None

    def string(self, o, off):
        return self.cstr(self.p(o, off))

    def array(self, o, off):
        """(element data offset, count) of the hkArray at o + off."""
        d = self.p(o, off)
        n, = self.u("<i", o, off + 8)
        return d, (n if d is not None else 0)

    def ptr_array(self, o, off) -> List[Optional[int]]:
        d, n = self.array(o, off)
        return [self.ptr.get(d + 8 * k) for k in range(n)] if d is not None else []

    def string_array(self, o, off) -> List[str]:
        d, n = self.array(o, off)
        return [self.cstr(self.ptr.get(d + 8 * k)) or "" for k in range(n)] if d is not None else []

    def children(self, o) -> List[int]:
        """Objects this object points to, in field order (object range only, so arrays written after it count)."""
        out = []
        for k in sorted(x for x in self.ptr if o <= x < self.ends[o]):
            t = self.ptr[k]
            if t in self.cls and t != o and t not in out:
                out.append(t)
        return out


def _bindings(r: _Reader, o) -> List[dict]:
    bs = r.p(o, NODE_BINDINGS)
    if bs is None or r.cls.get(bs) != "hkbVariableBindingSet":
        return []
    d, n = r.array(bs, 16)
    out = []
    for k in range(n if d is not None else 0):
        b = d + BINDING_SIZE * k
        path = r.cstr(r.ptr.get(b))
        var, = r.pf.unpack("<i", b + 28)
        kind, = r.pf.unpack("<b", b + 33)
        out.append({"member": path, "variable": var, "kind": "character_property" if kind == 1 else "variable"})
    return out


def read(data: bytes) -> Dict:
    """{"name", "events": [...], "variables": [...], "character_properties": [...], "root": obj id, "nodes":
    {obj id: {...}}, "bias", "checks": [...]} for the first hkbBehaviorGraph in the file."""
    r = _Reader(data)
    graphs = [o for o, c in r.objs if c == "hkbBehaviorGraph"]
    if not graphs:
        raise BehaviorError("no hkbBehaviorGraph (" + ", ".join(sorted(set(r.cls.values()))[:8]) + " ...)")
    g = graphs[0]
    gd = r.p(g, 136)
    sd = r.p(gd, 120) if gd is not None else None
    if sd is None or r.cls.get(sd) != "hkbBehaviorGraphStringData":
        sd = next((o for o, c in r.objs if c == "hkbBehaviorGraphStringData"), None)
    events = r.string_array(sd, 16) if sd is not None else []
    variables = r.string_array(sd, 48) if sd is not None else []
    props = r.string_array(sd, 64) if sd is not None else []
    nodes, checks = {}, []
    for o, c in r.objs:
        n = {"class": c, "children": r.children(o)}
        if c.startswith(("hkb", "BS")) and c not in ("hkbBehaviorGraphStringData", "hkbBehaviorGraphData",
                                                     "hkbVariableValueSet", "hkbVariableBindingSet",
                                                     "hkbStateMachineTransitionInfoArray", "hkbClipTriggerArray",
                                                     "hkbStateMachineEventPropertyArray", "hkbBoneWeightArray",
                                                     "hkbBoneIndexArray", "hkbExpressionDataArray",
                                                     "hkbStringEventPayload", "hkbExpressionCondition",
                                                     "hkbBlendingTransitionEffect", "hkbCharacterStringData",
                                                     "hkbProjectStringData", "hkbCharacterData", "hkbProjectData"):
            n["name"] = r.string(o, NODE_NAME)
            b = _bindings(r, o)
            if b:
                n["bindings"] = b
        if c == "hkbStateMachine":
            n.update(start_state=r.u("<i", o, 104)[0], wildcard=r.p(o, 160),
                     states=[x for x in r.ptr_array(o, 144) if x is not None],
                     start_mode=SM_MODES.get(r.u("<B", o, 134)[0]), self_transition=r.u("<B", o, 135)[0])
        elif c == "hkbStateMachineStateInfo":
            n.update(name=r.string(o, 96), state_id=r.u("<i", o, 104)[0], generator=r.p(o, 88),
                     transitions=r.p(o, 80), enter_events=r.p(o, 64), exit_events=r.p(o, 72),
                     enable=bool(r.u("<B", o, 112)[0]))
        elif c == "hkbStateMachineTransitionInfoArray":
            d, cnt = r.array(o, 16)
            tr = []
            for k in range(cnt if d is not None else 0):
                b = d + TRANSITION_SIZE * k
                ev, to, fnest, tnest = r.pf.unpack("<4i", b + 48)
                prio, flags = r.pf.unpack("<hH", b + 64)
                cond = r.ptr.get(b + 40)
                tr.append({"event": ev, "to_state": to, "to_nested": tnest, "from_nested": fnest, "priority": prio,
                           "flags": flags, "effect": r.ptr.get(b + 32), "condition": cond,
                           "condition_expr": r.cstr(r.ptr.get(r.at(cond, 16))) if cond is not None else None})
            n["transitions"] = tr
        elif c == "hkbClipGenerator":
            crop0, crop1, start, speed = r.u("<4f", o, 88)
            n.update(animation=r.string(o, 72), triggers=r.p(o, 80), crop=(crop0, crop1), start_time=start,
                     speed=speed, mode=r.u("<B", o, 114)[0])
        elif c == "hkbBlenderGenerator":
            n.update(blend_parameter=r.u("<f", o, 76)[0], blend_children=[x for x in r.ptr_array(o, 96) if x])
        elif c == "hkbBehaviorReferenceGenerator":
            n.update(behavior=r.string(o, 72))
        elif c == "hkbBlenderGeneratorChild":
            n.update(generator=r.p(o, 48), weight=r.u("<f", o, 64)[0])
        nodes[o] = n
    # checks: every transition targets a state of its machine (or a nested / wildcard case), event ids in range
    for o, n in nodes.items():
        if n["class"] != "hkbStateMachine":
            continue
        ids = {nodes[s]["state_id"] for s in n["states"] if s in nodes and "state_id" in nodes[s]}
        if n["start_state"] not in ids and ids:
            checks.append(f"{n.get('name')}: start state {n['start_state']} not among {sorted(ids)[:8]}")
        arrays = [nodes[s].get("transitions") for s in n["states"] if s in nodes] + [n.get("wildcard")]
        for a in arrays:
            for t in (nodes.get(a, {}).get("transitions") or []):
                if t["to_state"] not in ids:
                    checks.append(f"{n.get('name')}: transition to {t['to_state']} not among {sorted(ids)[:8]}")
                if not (-1 <= t["event"] < max(len(events), 1)):
                    checks.append(f"{n.get('name')}: event id {t['event']} out of range ({len(events)})")
    for o, n in nodes.items():
        if n["class"] == "hkbClipGenerator" and not (n.get("animation") or "").lower().endswith(".hkx"):
            checks.append(f"clip {n.get('name')}: animation {n.get('animation')!r}")
    return {"name": r.string(g, NODE_NAME), "events": events, "variables": variables, "character_properties": props,
            "root": r.p(g, 128), "nodes": nodes, "bias": r.bias, "checks": checks}


def summary(b: Dict) -> Dict:
    cls = {}
    for n in b["nodes"].values():
        cls[n["class"]] = cls.get(n["class"], 0) + 1
    sms = [n for n in b["nodes"].values() if n["class"] == "hkbStateMachine"]
    tr = sum(len(n.get("transitions") or []) for n in b["nodes"].values()
             if n["class"] == "hkbStateMachineTransitionInfoArray")
    return {"name": b["name"], "events": len(b["events"]), "variables": len(b["variables"]),
            "state_machines": len(sms), "states": sum(len(n["states"]) for n in sms), "transitions": tr,
            "clips": cls.get("hkbClipGenerator", 0), "classes": len(cls), "checks": len(b["checks"])}
