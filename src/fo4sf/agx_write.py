"""Write Starfield .agx animation graphs (the graph-editor XML read by fo4sf.agx), from a small model:

    graph = {"name": "Data\\\\Meshes\\\\AnimTextData\\\\Tables\\\\Graphs\\\\X.agx",
             "start_variable": "", "start_method": "Default" | "Sync" | "Variable", "default": 0,
             "nodes": [node, ...], "links": [(from_index, to_index, link_props), ...]}
    node  = {"kind": "anim", "tag": "Idle", "flags": [...], "props": {...}}               NT_ANIMATION_NODE
          | {"kind": "empty"}                                                             NT_ANIMATION_NODE, TagName None
          | {"kind": "sm", "name": "Locomotion", "graph": graph (nested, no "name")}      NT_STATE_MACHINE_EMBEDDED
          | {"kind": "ref", "graph_ref": "Jumping"}                                       NT_GRAPH_REF
          | {"kind": "blendtree", "name": "...", "graph": {"type": "blendtree", "nodes", "links"}}
                                                    NT_BLEND_TREE_EMBEDDED: a data-flow graph whose node 0 is its output
          | {"kind": "blend", "name", "variable", "variable_type": "Standard", "range": (min, max),
             "inputs": [names], "curves": [[(range, weight), ...] per input] or None}           NT_BLEND_NODE
          | {"kind": "switch", "name", "variable", "variable_type": "Variable", "inputs": [case names],
             "tag_alteration": "Do Nothing"}                                                    NT_SWITCH_NODE
    link_props (state machine transitions): {"event", "condition", "blend" (s), "priority", "type" ("Smooth")}
    link_props (data links inside a blend tree): {"data": True, "input": index of the target's input}

Layout as in the shipped files (SW SFBM mod, Nexus 16022; verified by reading them): CRLF, tab indents; every node has
node_type, noninstanced, flags, name, pos / expanded pos, use_color_2, user_id, collapsed, guid, its inputs (a
transition INTO a state is a <link> on the target's input naming the source node index and one of the source's output
slots), its outputs, and a property sheet of (Property, Value) rows with value types (0 int / variable, 1 float /
variable, 2 string, 3 bool). A state machine is a <graph> whose nodes are its states; its own sheet sets the start
selection.
Verified on vanilla graphs (owner's sf_anim_survey samples, 38 Starfield graphs, 2026-10-19): a state machine's default
state carries `<default_state>True</default_state>` as the first line of its <node>, unindented (75 machines, never
more than one, not always the first node); Start Selection Method is Default (0) / Sync (1, with an iSync* variable) /
Variable (2); vanilla nodes without flags have no <flags> element (the writer omits it too); flag names seen: Animation
Driven, Allow Rotation, Turn Animation, Is Attack Not Ready, Equip Not OK, Is Busy, Disable Foot IK, Block POV Switch.
"""
import uuid
from typing import Dict, List

ANIM_ROWS = [("TagName", 2, ""), ("Sync System", 2, ""), ("Sync Slave", 3, "False"), ("Send Event On End", 2, ""),
             ("State Variable", 0, ""), ("State Variable Ref Count", 0, ""), ("Update Ref Count When Inactive", 3, "True"),
             ("Speed Multiplier", 1, ""), ("Speed Multiplier Is Duration", 3, "False"), ("Crop Start Frames", 0, "0"),
             ("Crop End Frames", 0, "0"), ("Randomize Start Point", 3, "False"), ("Mirror", 3, "False"),
             ("Process Inactive Events", 3, "True"), ("Variable Control", 1, ""), ("Sync Only Transition Out", 3, "False")]
SM_ROWS = [("State Machine Name", 2, ""), ("Sync Only Transition Out", 3, "False")]
REF_ROWS = [("Graph Ref", 2, ""), ("Wrapped Graph", 3, "False")]
START_METHODS = ["Default", "Sync", "Variable"]
GRAPH_ROWS = [("Start Selection Method", 2, "Default"), ("Start Selection Variable", 0, ""),
              ("Maintain Sync Selection Variable When Exiting", 3, "False"), ("Update While Inactive", 3, "False")]
LINK_ROWS = [("Event", 2, ""), ("Comment", 2, ""), ("Condition", 2, ""), ("Blend Time", 1, "0.2"), ("Priority", 0, "0"),
             ("Allow Self Transition", 3, "False"), ("Do Not Follow Sync Group", 3, "False"),
             ("Transition Type", 2, "Smooth", 0)]
BLENDTREE_ROWS = [("Blend Tree Name", 2, ""), ("Sync Only Transition Out", 3, "False")]
BLENDTREE_GRAPH_ROWS = [("Blend Tree Name", 2, "")]
# dropdown list orders (CALUMI.Motion's definitions; they match the list indexes in the shipped files)
BLEND_VARIABLE_TYPES = ["Standard", "Parametric", "Layer"]
SWITCH_VARIABLE_TYPES = ["Event", "Variable", "Event and Variable"]
TAG_ALTERATIONS = ["Do Nothing", "Prefix", "Suffix"]
NODE_TYPES = {"anim": "NT_ANIMATION_NODE", "empty": "NT_ANIMATION_NODE", "sm": "NT_STATE_MACHINE_EMBEDDED",
              "ref": "NT_GRAPH_REF", "blendtree": "NT_BLEND_TREE_EMBEDDED", "blend": "NT_BLEND_NODE",
              "switch": "NT_SWITCH_NODE"}
NODE_NAMES = {"anim": "Animation", "empty": "Animation", "sm": "State Machine Embedded", "ref": "Graph Ref",
              "blendtree": "Blend Tree Embedded", "blend": "Blend", "switch": "Switch"}


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _sheet(rows, values: Dict[str, str], ind: str) -> List[str]:
    out = [f"{ind}<property_sheet>", f"{ind}\t<num_columns>2</num_columns>",
           f"{ind}\t<column> <header>Property</header> <types>5</types> </column>",
           f"{ind}\t<column> <header>Value</header> <types>5</types> </column>"]
    for row in rows:
        name, typ, default = row[0], row[1], row[2]
        val = values.get(name, default)
        li = f" <listindex>{row[3]}</listindex>" if len(row) > 3 else ""
        out += [f"{ind}\t<row>", f"{ind}\t\t<prop> <type>2</type> <value>{_esc(name)}</value> </prop>",
                f"{ind}\t\t<prop> <type>{typ}</type> <value>{_esc(val)}</value>{li} </prop>", f"{ind}\t</row>"]
    out.append(f"{ind}</property_sheet>")
    return out


class _Ids:
    def __init__(self, seed: str):
        self.n, self.seed = 0, seed

    def next(self):
        self.n += 1
        return self.n

    def guid(self):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self.seed}/{self.next()}"))


def _graph_body(g: Dict, ids: _Ids, ind: str) -> List[str]:
    nodes, links = g["nodes"], g.get("links", [])
    outs = {i: [] for i in range(len(nodes))}                        # source node -> its output slot ids
    incoming = {i: [] for i in range(len(nodes))}
    for k, (a, b, props) in enumerate(links):
        if not (0 <= a < len(nodes) and 0 <= b < len(nodes)):
            raise ValueError(f"link {k} {a}->{b} outside the graph")
        slot = len(outs[a])
        outs[a].append(ids.next())
        incoming[b].append((a, slot, props))
    if g.get("type") == "blendtree":
        consumed = {a for a, _b, _p in links}
        if 0 in consumed:
            raise ValueError("a blend tree's node 0 is its output and must not feed another node")
    lines = [f"{ind}<Link_Style>1</Link_Style>"]
    default = None if g.get("type") == "blendtree" else g.get("default", 0)
    if default is not None and nodes and not 0 <= default < len(nodes):
        raise ValueError(f"default state {default} outside the graph")
    for i, n in enumerate(nodes):
        kind = n["kind"]
        flags = "".join(f"<flag>{_esc(f)}</flag>" for f in n.get("flags", []))
        lines.append(f"{ind}<node>")
        if i == default:
            lines.append("<default_state>True</default_state>")           # unindented, as in the shipped files
        lines += [f"{ind}\t<node_type>{NODE_TYPES[kind]}</node_type>", f"{ind}\t<noninstanced>False</noninstanced>"]
        if kind == "blend":
            curves = n.get("curves") or [[] for _ in n.get("inputs", [])]
            lines.append(f"{ind}\t<divisions>0</divisions>")
            for pts in curves:
                lines.append(f"{ind}\t<blendInput>")
                for r, w in pts:
                    lines.append(f"{ind}\t\t<point><Range>{r:g}</Range><Weight>{w:g}</Weight></point>")
                lines.append(f"{ind}\t</blendInput>")
        elif flags:
            lines.append(f"{ind}\t<flags>{flags}</flags>")
        lines += [f"{ind}\t<name>{NODE_NAMES[kind]}</name>",
                  f"{ind}\t<pos_x>{200 + 220 * (i % 6)}</pos_x>", f"{ind}\t<pos_y>{150 + 160 * (i // 6)}</pos_y>",
                  f"{ind}\t<expanded_pos_x>{200 + 220 * (i % 6)}</expanded_pos_x>",
                  f"{ind}\t<expanded_pos_y>{150 + 160 * (i // 6)}</expanded_pos_y>",
                  f"{ind}\t<use_color_2>False</use_color_2>", f"{ind}\t<user_id>{i}</user_id>",
                  f"{ind}\t<collapsed>True</collapsed>", f"{ind}\t<guid>{ids.guid()}</guid>"]
        in_names = n.get("inputs") or [""]
        for k, iname in enumerate(in_names):
            lines.append(f"{ind}\t<input> <name>{_esc(iname)}</name> <id>{ids.next()}</id> <idx>{k}</idx>")
            for a, slot, props in incoming[i]:
                if props.get("input", 0) != k:
                    continue
                lines += ["", f"{ind}\t\t<link>", f"{ind}\t\t\t<node>{a}</node> <output>{slot}</output> <hidden>False</hidden>"]
                if not props.get("data"):
                    vals = {"Event": props.get("event", ""), "Condition": props.get("condition", ""),
                            "Blend Time": f"{props.get('blend', 0.2):g}", "Priority": str(props.get("priority", 0)),
                            "Transition Type": props.get("type", "Smooth"), "Comment": props.get("comment", "")}
                    lines += _sheet(LINK_ROWS, vals, ind + "\t")
                lines.append(f"{ind}\t\t</link>")
            lines.append(" </input>")
        out_name = "Out" if kind in ("blend", "switch") else ""
        for slot, oid in enumerate(outs[i] or ([ids.next()] if kind in ("blend", "switch") else [])):
            lines += [f"{ind}\t<output> <name>{out_name}</name> <id>{oid}</id> <idx>{slot}</idx>", " </output>"]
        if kind in ("anim", "empty"):
            vals = dict(n.get("props", {}))
            vals["TagName"] = n.get("tag") or "None" if kind == "anim" else "None"
            lines += _sheet(ANIM_ROWS, vals, ind + "\t")
        elif kind == "sm":
            lines += _sheet(SM_ROWS, {"State Machine Name": n.get("name", "")}, ind + "\t")
            lines.append(f"{ind}\t<graph>")
            lines += _graph_body(n["graph"], ids, ind + "\t\t")
            lines.append(f"{ind}\t</graph>")
        elif kind == "ref":
            lines += _sheet(REF_ROWS, {"Graph Ref": n.get("graph_ref", "")}, ind + "\t")
        elif kind == "blendtree":
            lines += _sheet(BLENDTREE_ROWS, {"Blend Tree Name": n.get("name", "")}, ind + "\t")
            sub = dict(n["graph"], type="blendtree")
            lines.append(f"{ind}\t<graph>")
            lines += _graph_body(sub, ids, ind + "\t\t")
            lines.append(f"{ind}\t</graph>")
        elif kind == "blend":
            vt = n.get("variable_type", "Standard")
            lo, hi = n.get("range", (0.0, 1.0))
            rows = [("Name", 2, ""), ("Variable Name", 1, ""), ("Variable Type", 2, vt, BLEND_VARIABLE_TYPES.index(vt)),
                    ("Sync Variable", 0, ""), ("Input Lock Time", 1, "-1"), ("Range Min", 1, "0"), ("Range Max", 1, "1"),
                    ("Wrap To Range", 3, "False"), ("Max Blend Time", 1, "0"), ("Normalize Weights", 3, "False"),
                    ("Only Highest Weight Active", 3, "False")]
            lines += _sheet(rows, {"Name": n.get("name", ""), "Variable Name": n.get("variable", ""),
                                   "Range Min": f"{lo:g}", "Range Max": f"{hi:g}"}, ind + "\t")
        elif kind == "switch":
            vt = n.get("variable_type", "Variable")
            ta = n.get("tag_alteration", "Do Nothing")
            rows = [("Name", 2, ""), ("Variable Name", 0, ""), ("Variable Type", 2, vt, SWITCH_VARIABLE_TYPES.index(vt)),
                    ("Max Blend Time", 1, "0"), ("Randomize If Invalid", 3, "False"),
                    ("Tag Alteration", 2, ta, TAG_ALTERATIONS.index(ta))]
            lines += _sheet(rows, {"Name": n.get("name", ""), "Variable Name": n.get("variable", "")}, ind + "\t")
        lines.append(f"{ind}</node>")
    if g.get("type") == "blendtree":
        lines += _sheet(BLENDTREE_GRAPH_ROWS, {}, ind)
        return lines
    sv = g.get("start_variable", "")
    method = g.get("start_method") or ("Variable" if sv else "Default")
    rows = [r if r[0] != "Start Selection Method" else (r[0], r[1], method, START_METHODS.index(method))
            for r in GRAPH_ROWS]
    lines += _sheet(rows, {"Start Selection Variable": sv}, ind)
    return lines


def write(g: Dict) -> bytes:
    ids = _Ids(g.get("name", "graph"))
    lines = ["<root>", f"<Name>{_esc(g['name'])}</Name>"] + _graph_body(g, ids, "") + ["</root>", ""]
    return "\r\n".join(lines).encode("ascii", "replace")
