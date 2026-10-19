"""Write Starfield .agx animation graphs (the graph-editor XML read by fo4sf.agx), from a small model:

    graph = {"name": "Data\\\\Meshes\\\\AnimTextData\\\\Tables\\\\Graphs\\\\X.agx",
             "start_variable": "", "nodes": [node, ...], "links": [(from_index, to_index, link_props), ...]}
    node  = {"kind": "anim", "tag": "Idle", "flags": [...], "props": {...}}               NT_ANIMATION_NODE
          | {"kind": "empty"}                                                             NT_ANIMATION_NODE, TagName None
          | {"kind": "sm", "name": "Locomotion", "graph": graph (nested, no "name")}      NT_STATE_MACHINE_EMBEDDED
          | {"kind": "ref", "graph_ref": "Jumping"}                                       NT_GRAPH_REF
    link_props: {"event", "condition", "blend" (s), "priority", "type" ("Smooth")}

Layout as in the shipped files (SW SFBM mod, Nexus 16022; verified by reading them): CRLF, tab indents; every node has
node_type, noninstanced, flags, name, pos / expanded pos, use_color_2, user_id, collapsed, guid, its inputs (a
transition INTO a state is a <link> on the target's input naming the source node index and one of the source's output
slots), its outputs, and a property sheet of (Property, Value) rows with value types (0 int / variable, 1 float /
variable, 2 string, 3 bool). A state machine is a <graph> whose nodes are its states; its own sheet sets the start
selection. Unverified: how the default state is marked when Start Selection Method is Default (none of the shipped
nodes carries a marker): the writer puts the start state first.
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
GRAPH_ROWS = [("Start Selection Method", 2, "Default", 0), ("Start Selection Variable", 0, ""),
              ("Maintain Sync Selection Variable When Exiting", 3, "False"), ("Update While Inactive", 3, "False")]
LINK_ROWS = [("Event", 2, ""), ("Comment", 2, ""), ("Condition", 2, ""), ("Blend Time", 1, "0.2"), ("Priority", 0, "0"),
             ("Allow Self Transition", 3, "False"), ("Do Not Follow Sync Group", 3, "False"),
             ("Transition Type", 2, "Smooth", 0)]
NODE_TYPES = {"anim": "NT_ANIMATION_NODE", "empty": "NT_ANIMATION_NODE", "sm": "NT_STATE_MACHINE_EMBEDDED",
              "ref": "NT_GRAPH_REF"}
NODE_NAMES = {"anim": "Animation", "empty": "Animation", "sm": "State Machine Embedded", "ref": "Graph Ref"}


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
    lines = [f"{ind}<Link_Style>1</Link_Style>"]
    for i, n in enumerate(nodes):
        kind = n["kind"]
        flags = "".join(f"<flag>{_esc(f)}</flag>" for f in n.get("flags", []))
        lines += [f"{ind}<node>", f"{ind}\t<node_type>{NODE_TYPES[kind]}</node_type>",
                  f"{ind}\t<noninstanced>False</noninstanced>", f"{ind}\t<flags>{flags}</flags>",
                  f"{ind}\t<name>{NODE_NAMES[kind]}</name>",
                  f"{ind}\t<pos_x>{200 + 220 * (i % 6)}</pos_x>", f"{ind}\t<pos_y>{150 + 160 * (i // 6)}</pos_y>",
                  f"{ind}\t<expanded_pos_x>{200 + 220 * (i % 6)}</expanded_pos_x>",
                  f"{ind}\t<expanded_pos_y>{150 + 160 * (i // 6)}</expanded_pos_y>",
                  f"{ind}\t<use_color_2>False</use_color_2>", f"{ind}\t<user_id>{i}</user_id>",
                  f"{ind}\t<collapsed>True</collapsed>", f"{ind}\t<guid>{ids.guid()}</guid>"]
        lines.append(f"{ind}\t<input> <name></name> <id>{ids.next()}</id> <idx>0</idx>")
        for a, slot, props in incoming[i]:
            vals = {"Event": props.get("event", ""), "Condition": props.get("condition", ""),
                    "Blend Time": f"{props.get('blend', 0.2):g}", "Priority": str(props.get("priority", 0)),
                    "Transition Type": props.get("type", "Smooth"), "Comment": props.get("comment", "")}
            lines += ["", f"{ind}\t\t<link>", f"{ind}\t\t\t<node>{a}</node> <output>{slot}</output> <hidden>False</hidden>"]
            lines += _sheet(LINK_ROWS, vals, ind + "\t")
            lines.append(f"{ind}\t\t</link>")
        lines.append(" </input>")
        for slot, oid in enumerate(outs[i]):
            lines += [f"{ind}\t<output> <name></name> <id>{oid}</id> <idx>{slot}</idx>", " </output>"]
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
        lines.append(f"{ind}</node>")
    sv = g.get("start_variable", "")
    lines += _sheet(GRAPH_ROWS, {"Start Selection Method": "Variable" if sv else "Default",
                                 "Start Selection Variable": sv}, ind)
    return lines


def write(g: Dict) -> bytes:
    ids = _Ids(g.get("name", "graph"))
    lines = ["<root>", f"<Name>{_esc(g['name'])}</Name>"] + _graph_body(g, ids, "") + ["</root>", ""]
    return "\r\n".join(lines).encode("ascii", "replace")
