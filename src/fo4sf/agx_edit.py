"""Edit a shipped Starfield .agx graph in place (read-modify-write), keeping every byte not changed.

The graph-editor XML round-trips through ElementTree byte for byte (verified 2026-10-19 on the vanilla MeleeAttacks.agx
and Player_Melee.agx: identical once CRLF line ends and the newline after </root> are put back, with
short_empty_elements=False). Format facts used here (see agx_write): a state machine is a <graph> whose <node>s are
its states; a transition INTO a state is a <link> inside one of the target's <input>s, naming the source as its 1-based
index among the sibling nodes plus one of the source's <output> slots. Seen on 42 vanilla graphs: one link per <input>
at most (a state has one input per incoming transition, sometimes with spare empty ones), one transition per output
slot, and <id>s unique within a node (inputs and outputs together), not across the file. A link whose source is the
target itself is an any-state ("wildcard") transition: vanilla enters every action of MeleeActions that way
(CastSelf <- CastSelf on CastSelfStart, ...) and leaves to the idle state with event-less links from each action
(verified on MeleeActions.agx / MeleeAttacks.agx: read as 1-based indices, every link is then either such a
self-link on a start event or a plausible state-to-state edge).
"""
import copy
import uuid
import xml.etree.ElementTree as ET
from typing import List, Optional


class AgxEditError(ValueError):
    pass


def load(raw: bytes) -> ET.Element:
    return ET.fromstring(raw)


def dump(root: ET.Element, like: bytes = b"\r\n") -> bytes:
    out = ET.tostring(root, encoding="utf-8", short_empty_elements=False)
    if b"\r\n" in like:
        out = out.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        return out + b"\r\n"
    return out + b"\n"


def _rows(n: ET.Element) -> dict:
    out = {}
    for sh in n.findall("property_sheet"):
        for r in sh.findall("row"):
            p = r.findall("prop")
            if len(p) >= 2:
                out.setdefault(p[0].findtext("value"), p[1].findtext("value"))
    return out


def machine(root: ET.Element, name: Optional[str] = None) -> ET.Element:
    """The node list holder of a state machine: the file's top level (name None) or the <graph> of the embedded
    state machine called `name` (searched depth first)."""
    if name is None:
        return root
    stack = [root]
    while stack:
        g = stack.pop()
        for n in g.findall("node"):
            sub = n.find("graph")
            if sub is None:
                continue
            if _rows(n).get("State Machine Name") == name:
                return sub
            stack.append(sub)
    raise AgxEditError(f"no state machine {name!r}")


def state(graph: ET.Element, tag: str) -> int:
    """0-based index of the state whose TagName (or State Machine Name) is `tag`; exactly one must match."""
    hits = [i for i, n in enumerate(graph.findall("node"))
            if tag in (_rows(n).get("TagName"), _rows(n).get("State Machine Name"))]
    if len(hits) != 1:
        raise AgxEditError(f"state {tag!r}: {len(hits)} matches")
    return hits[0]


def transitions(graph: ET.Element) -> List[tuple]:
    """[(source index, target index, event, condition)] of one machine."""
    out = []
    for t, n in enumerate(graph.findall("node")):
        for inp in n.findall("input"):
            for link in inp.findall("link"):
                r = _rows(link)
                out.append((int(link.findtext("node")) - 1, t, r.get("Event") or "", r.get("Condition") or ""))
    return out


def _links_into(node: ET.Element) -> List[ET.Element]:
    """The node's own incoming links (not those inside an embedded machine it holds)."""
    return [link for inp in node.findall("input") for link in inp.findall("link")]


def set_event(graph: ET.Element, src: int, dst: int, event: str, old: str) -> int:
    """Set the Event of the transitions src -> dst whose event is `old`; returns how many changed."""
    n = 0
    for link in _links_into(graph.findall("node")[dst]):
        if int(link.findtext("node")) - 1 != src:
            continue
        for r in link.iter("row"):
            p = r.findall("prop")
            if p and p[0].findtext("value") == "Event" and (p[1].findtext("value") or "") == old:
                p[1].find("value").text = event
                n += 1
    return n


def clone_state(node: ET.Element, graph: ET.Element, root: Optional[ET.Element] = None) -> int:
    """Append a deep copy of `node` (a state from any graph, e.g. a whole embedded state machine) to `graph`'s states,
    without its own incoming links and output slots (they named states of its old machine; the copy's inner graph is
    kept as is), with a fresh guid and a user_id unused among its new siblings (in the whole file when `root` is given:
    vanilla user_ids repeat across machines, but a copy should not add a clash). Returns its index."""
    new = copy.deepcopy(node)
    for inp in new.findall("input"):
        for link in inp.findall("link"):
            inp.remove(link)
        inp.find("idx").tail = "\n "
    for out in new.findall("output"):
        new.remove(out)
    if new.find("guid") is not None:
        new.find("guid").text = str(uuid.uuid4())
    sibs = graph.findall("node")
    pool = root.iter("node") if root is not None else sibs     # with root: unique in the whole file
    used = [int(n.findtext("user_id")) for n in pool if (n.findtext("user_id") or "").strip().isdigit()]
    if new.find("user_id") is not None:
        new.find("user_id").text = str(max(used or [0]) + 1)
    kids = list(graph)
    at = kids.index(sibs[-1]) + 1 if sibs else len(kids)
    new.tail = sibs[-1].tail if sibs else "\n"
    graph.insert(at, new)
    return len(sibs)


def set_tag(node: ET.Element, tag: str) -> bool:
    """Set an animation state's TagName (the clip tag it plays); False if it has none."""
    for r in node.findall("property_sheet/row"):
        p = r.findall("prop")
        if len(p) >= 2 and p[0].findtext("value") == "TagName":
            p[1].find("value").text = tag
            return True
    return False


def set_row(node: ET.Element, key: str, value: str) -> bool:
    """Set the value of the state's own property row `key` (e.g. "Send Event On End"); False if it has none."""
    for r in node.findall("property_sheet/row"):
        p = r.findall("prop")
        if len(p) >= 2 and p[0].findtext("value") == key:
            p[1].find("value").text = value
            return True
    return False


def add_flag(node: ET.Element, flag: str) -> bool:
    """Add a state flag (e.g. "Force Copy Bone Weights"); False if already set. Vanilla keeps <flags> right after
    <noninstanced> and writes them on one line (<flags><flag>A</flag><flag>B</flag></flags>)."""
    flags = node.find("flags")
    if flags is None:
        flags = ET.Element("flags")
        ni = node.find("noninstanced")
        at = list(node).index(ni) + 1 if ni is not None else 0
        flags.tail = ni.tail if ni is not None else "\n\t"
        node.insert(at, flags)
    if flag in [f.text for f in flags.findall("flag")]:
        return False
    ET.SubElement(flags, "flag").text = flag
    return True


def remove_flag(node: ET.Element, flag: str) -> bool:
    """Remove a state flag; False if it was not set. An emptied <flags> is removed (vanilla writes none then)."""
    flags = node.find("flags")
    hit = [f for f in (flags.findall("flag") if flags is not None else []) if f.text == flag]
    for f in hit:
        flags.remove(f)
    if flags is not None and not flags.findall("flag"):
        node.remove(flags)
    return bool(hit)


def remove_state_events(node: ET.Element, names) -> List[str]:
    """Remove the named events from a state's Enter Events / Exit Events sheets (rows of '', Non Instanced, event,
    payload); returns "enter:Name" / "exit:Name" for each removed row."""
    gone = []
    for sh in node.findall("property_sheet"):
        heads = [c.findtext("header") for c in sh.findall("column")]
        kind = "enter" if "Enter Events" in heads else "exit" if "Exit Events" in heads else None
        if kind is None:
            continue
        for row in sh.findall("row"):
            p = row.findall("prop")
            if len(p) >= 3 and p[2].findtext("value") in names:
                sh.remove(row)
                gone.append(f"{kind}:{p[2].findtext('value')}")
        rows = sh.findall("row")
        cols = sh.findall("column")
        if not rows and cols:                          # an empty sheet ends right after its last column, as shipped
            cols[-1].tail = sh.find("num_columns").tail[:-1] if sh.find("num_columns").tail else "\n\t"
    return gone


def set_condition(graph: ET.Element, src: int, dst: int, condition: str, old: Optional[str] = None) -> int:
    """Set the Condition of the transitions src -> dst (0-based states of `graph`; only those whose condition is `old`
    when given); returns how many changed."""
    n = 0
    for link in _links_into(graph.findall("node")[dst]):
        if int(link.findtext("node")) - 1 != src:
            continue
        for r in link.iter("row"):
            p = r.findall("prop")
            if p and p[0].findtext("value") == "Condition" and (old is None or (p[1].findtext("value") or "") == old):
                p[1].find("value").text = condition
                n += 1
    return n


def _next_socket_id(node: ET.Element) -> int:
    ids = [int(x.findtext("id")) for tag in ("input", "output") for x in node.findall(tag)
           if (x.findtext("id") or "").strip().lstrip("-").isdigit()]
    return max(ids or [0]) + 1


def add_transition(root: ET.Element, graph: ET.Element, src: int, dst: int, event: str, blend: float = 0.15,
                   condition: str = "", template: Optional[ET.Element] = None) -> bool:
    """Add a transition src -> dst (0-based state indices in `graph`) on `event`; False when one with the same event
    and condition already exists. The new link copies `template` (a <link>; default: the first transition link in the
    file) and sets its Event / Condition / Blend Time; the source gets a new output slot."""
    if any(s == src and d == dst and e == event and c == condition for s, d, e, c in transitions(graph)):
        return False
    nodes = graph.findall("node")
    if not (0 <= src < len(nodes) and 0 <= dst < len(nodes)):
        raise AgxEditError(f"transition {src}->{dst} outside the machine")
    if template is None:
        template = next((l for l in root.iter("link") if l.find("property_sheet") is not None), None)
        if template is None:
            raise AgxEditError("no transition in the file to copy the link layout from")
    s_node, d_node = nodes[src], nodes[dst]
    outs = s_node.findall("output")
    if outs:
        new_out = copy.deepcopy(outs[-1])
        at = list(s_node).index(outs[-1]) + 1
    else:                                             # the shipped layout: <output> <name></name> <id/> <idx/> </output>
        new_out = ET.Element("output")
        new_out.text = " "
        for tag, tail in (("name", " "), ("id", " "), ("idx", "\n ")):
            ET.SubElement(new_out, tag).tail = tail
        anchor = (s_node.findall("input") or [s_node.find("guid")])[-1]
        if anchor is None:
            raise AgxEditError("source state has no place for an output")
        new_out.tail = anchor.tail
        at = list(s_node).index(anchor) + 1
    new_out.find("id").text = str(_next_socket_id(s_node))
    new_out.find("idx").text = str(len(outs))
    s_node.insert(at, new_out)
    link = copy.deepcopy(template)
    link.find("node").text = str(src + 1)
    link.find("output").text = str(len(outs))
    for r in link.iter("row"):
        p = r.findall("prop")
        key = p[0].findtext("value") if p else None
        if key == "Event":
            p[1].find("value").text = event
        elif key == "Condition":
            p[1].find("value").text = condition
        elif key == "Blend Time":
            p[1].find("value").text = f"{blend:g}"
    ins = d_node.findall("input")
    free = next((i for i in ins if not i.findall("link")), None)
    if free is None:                                  # a new input, laid out like an existing one
        like = next((i for i in ins if i.findall("link")), None)
        if like is None:
            raise AgxEditError("target state has no input to copy the layout from")
        free = copy.deepcopy(like)
        for old in free.findall("link"):
            free.remove(old)
        free.find("id").text = str(_next_socket_id(d_node))
        free.find("idx").text = str(len(ins))
        d_node.insert(list(d_node).index(ins[-1]) + 1, free)
        free.find("idx").tail = like.find("idx").tail
    link.tail = template.tail
    free.append(link)
    return True
