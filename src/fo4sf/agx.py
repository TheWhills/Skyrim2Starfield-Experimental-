"""Starfield animation graphs (.agx, AnimTextData\\Tables\\Graphs\\*.agx) and clip descriptors (.afx): readers.

Both are plain XML text (verified 2026-10-19 on the four graphs and 44 descriptors shipped by the SW SFBM Vanilla
Blocking Fix mod, Nexus 16022: CRLF, ASCII). An .agx is the export of Bethesda's graph editor:
  <root><Name>Data\\Meshes\\AnimTextData\\Tables\\Graphs\\X.agx</Name> ... <node>* [<node_group>]
  node: node_type (NT_ANIMATION_NODE, NT_SWITCH_NODE, NT_BLEND_NODE, NT_GRAPH_REF, NT_STATE_MACHINE_EMBEDDED,
        NT_BLEND_TREE_EMBEDDED, NT_ASSIGN_VARIABLE, NT_MERGE_NODE, NT_BONE_CONSTRAINT, ...), name, user_id, guid,
        <input> (name, id, idx, <link> to an upstream <node> index + <output>, with its own property sheet: Event,
        Condition (text expression over graph variables, e.g. "bDontAllowBlock=0"), Blend Time, Priority,
        Transition Type), <output>*, and a property sheet of (Property, Value) rows.
  NT_ANIMATION_NODE: TagName (the clip tag), State Variable, Speed Multiplier (a variable, e.g. WeaponSpeedMult),
        Crop Start / End Frames, Mirror, Sync System ...
  NT_SWITCH_NODE: Variable Name / Type (Event, Variable, Event and Variable), Tag Alteration (Do Nothing, Prefix,
        Suffix): selects a variant by name prefix / suffix. Verified in the shipped files: the variants keep the BASE
        tag in their .afx (tag MeleeAttack_A) and carry the prefix in the file name (Sneak_MeleeAttack_A.af /
        sneak_meleeattack_a.afx, ZeroG_MeleeAttack_A.af), side by side with the plain MeleeAttack_A.af.
  NT_GRAPH_REF: Graph Ref (another graph by name: MeleeActions, Jumping, ...).
An .afx: <root> is_state (1 on the looping clip, MeleeBlock_Idle), tag, filename, rampout (blend-out frames), flags, <events><event> frame / name / payload, <variables><variable>
name / start / end (frame windows, e.g. bDontAllowBlock 0..30).
Supported hypothesis: a node's TagName (+ the active prefix / suffix variant) is looked up among the .afx of the
folders the actor's subgraph data gives for the equipped weapon, most specific first (melee\\onehanded\\player\\
sword\\twohandblock, ...\\sword, ...\\player): the mod overrides MeleeAttack_A in player, player\\knife and
player\\sword separately, and the block clips in player and player\\sword\\twohandblock.
"""
import xml.etree.ElementTree as ET
from typing import Dict, List


def _props(el) -> Dict[str, str]:
    ps = el.find("property_sheet")
    out = {}
    if ps is None:
        return out
    for row in ps.findall("row"):
        v = [p.findtext("value") for p in row.findall("prop")]
        if len(v) >= 2 and v[0] is not None:
            out[v[0]] = v[1] if v[1] is not None else ""
    return out


def read_graph(data: bytes) -> Dict:
    """{"name", "nodes": [{"index", "type", "props", "inputs": [{"name", "links": [{"node", "output", "props"}]}],
    "outputs": [names]}]}."""
    root = ET.fromstring(data.decode("utf-8-sig", "replace"))
    nodes = []
    for i, n in enumerate(root.findall("node")):
        inputs = []
        for inp in n.findall("input"):
            links = [{"node": int(l.findtext("node") or -1), "output": int(l.findtext("output") or -1),
                      "props": _props(l)} for l in inp.findall("link")]
            inputs.append({"name": (inp.findtext("name") or "").strip(), "links": links})
        nodes.append({"index": i, "type": n.findtext("node_type"), "props": _props(n), "inputs": inputs,
                      "outputs": [(o.findtext("name") or "").strip() for o in n.findall("output")]})
    return {"name": root.findtext("Name"), "nodes": nodes}


def summary(graph: Dict) -> Dict:
    """What a graph plays and reacts to: clip tags, tag alterations, referenced graphs, events and conditions on links,
    variables it reads."""
    tags, refs, alters, events, conds, variables = [], [], [], [], [], set()
    for n in graph["nodes"]:
        p = n["props"]
        if n["type"] == "NT_ANIMATION_NODE" and p.get("TagName"):
            tags.append(p["TagName"])
        if n["type"] == "NT_GRAPH_REF" and p.get("Graph Ref"):
            refs.append(p["Graph Ref"])
        if n["type"] == "NT_SWITCH_NODE" and p.get("Tag Alteration") in ("Prefix", "Suffix"):
            alters.append({"switch": p.get("Name"), "mode": p["Tag Alteration"], "variable": p.get("Variable Name"),
                           "cases": [i["name"] for i in n["inputs"]]})
        for k in ("Variable Name", "State Variable", "Speed Multiplier", "Sync Variable", "Activate Variable",
                  "Control Variable"):
            v = p.get(k)
            if v and not v.replace(".", "", 1).isdigit():
                variables.add(v)
        for i in n["inputs"]:
            for l in i["links"]:
                lp = l["props"]
                if lp.get("Event"):
                    events.append(lp["Event"])
                if lp.get("Condition"):
                    conds.append(lp["Condition"])
    return {"name": graph["name"], "nodes": len(graph["nodes"]), "tags": tags, "graph_refs": refs,
            "tag_alterations": alters, "events": sorted(set(events)), "conditions": sorted(set(conds)),
            "variables": sorted(variables)}


def read_descriptor(data: bytes) -> Dict:
    """An .afx: {"tag", "filename", "is_state", "rampout", "events": [(frame, name, payload)],
    "variables": [(name, start, end)]}."""
    r = ET.fromstring(data.decode("utf-8-sig", "replace"))

    def num(x):
        try:
            return int(x)
        except (TypeError, ValueError):
            return x
    return {"tag": r.findtext("tag"), "filename": r.findtext("filename"), "is_state": r.findtext("is_state"),
            "rampout": num(r.findtext("rampout")),
            "events": [(num(e.findtext("frame")), e.findtext("name"), e.findtext("payload") or "")
                       for e in r.iter("event")],
            "variables": [(v.findtext("name"), num(v.findtext("start")), num(v.findtext("end")))
                          for v in r.iter("variable")]}


def set_link_blend(data: bytes, event: str, blend: float):
    """(graph bytes, count): every transition whose Event is `event` gets Blend Time `blend` (seconds); the rest of the
    file is kept byte for byte (CRLF, tabs). A transition is a <link> property sheet with an Event row and a Blend Time
    row (fo4sf.agx_write's layout, verified on the vanilla graphs)."""
    import re
    text = data.decode("latin-1")
    count = 0

    def fix(m):
        nonlocal count
        sheet = m.group(0)
        if not re.search(r"<value>Event</value>\s*</prop>\s*<prop>\s*<type>\d+</type>\s*<value>" + re.escape(event)
                         + r"</value>", sheet):
            return sheet
        new, n = re.subn(r"(<value>Blend Time</value>\s*</prop>\s*<prop>\s*<type>\d+</type>\s*<value>)[^<]*(</value>)",
                         lambda b: b.group(1) + f"{blend:g}" + b.group(2), sheet, count=1)
        count += n
        return new

    text = re.sub(r"<property_sheet>.*?</property_sheet>", fix, text, flags=re.S)
    return text.encode("latin-1"), count

