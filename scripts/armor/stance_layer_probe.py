"""Read-only: what in the player's melee graphs can move the left arm in the combat (ready) stance.

    python -I scripts\\armor\\stance_layer_probe.py --starfield-data "$sf\\Data" --out C:\\Modding\\work\\stance_probe.txt

Why (docs/ai/decisions.md 2026-11-23): converted dodges, and the vanilla standing power attack alike, hold the left arm
out when started from the combat stance and not from the relaxed idle, whether the game or the plugin starts them; the
clips key the whole left arm. So something in the graphs adds to every full-body clip while the stance is ready.
This walks Player_Melee.agx and every graph it references (Graph Ref, recursively) from the game's archives (or loose
files given with --graph) and writes, per graph: the node types used, and every node that is of a kind that can move
bones on top of a clip (IK, bone constraints, additive / layered blends, bone weights / masks, Direct At, look-at) or
that switches stances (switches with a tag alteration, any property naming Ready / Relaxed / Alert / Combat), with all
its properties and its input links (events, conditions). Nothing is changed.
"""
import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

GRAPHS = "meshes/animtextdata/tables/graphs/"
START = "player_melee"
# node types / names / property text that can add to a clip's bones, or pick a stance
MOVES_BONES = re.compile(r"ik|constraint|additive|layer|bone|weight|mask|direct|look|aim|lean|copy|merge|pose|offset",
                         re.I)
STANCE = re.compile(r"ready|relaxed|alert|combat|stance|guard", re.I)


def _rows(el) -> dict:
    ps = el.find("property_sheet")
    out = {}
    if ps is None:
        return out
    for row in ps.findall("row"):
        v = [p.findtext("value") for p in row.findall("prop")]
        if len(v) >= 2 and v[0]:
            out[v[0]] = v[1] or ""
    return out


def _inputs(node) -> list:
    """[(input name, linked node index, its Event / Condition)] of a node's input links."""
    out = []
    for inp in node.findall("input"):
        for link in inp.findall("link"):
            r = _rows(link)
            out.append((inp.findtext("name") or "", link.findtext("node") or "",
                        ", ".join(f"{k}={r[k]}" for k in ("Event", "Condition", "Blend Time") if r.get(k))))
    return out


def interesting(node) -> str:
    """Why a node is listed ("" = not listed)."""
    kind = node.findtext("node_type") or ""
    name = node.findtext("name") or ""
    rows = _rows(node)
    if MOVES_BONES.search(kind) and kind not in ("NT_ANIMATION_NODE",):
        return "type"
    if kind == "NT_SWITCH_NODE" and rows.get("Tag Alteration", "Do Nothing") != "Do Nothing":
        return "tag alteration"
    text = " ".join([name] + [f"{k} {v}" for k, v in rows.items() if k != "Tag Alteration"])
    if kind != "NT_ANIMATION_NODE" and MOVES_BONES.search(text):
        return "bones"
    if STANCE.search(text):
        return "stance"
    return ""


def probe(name: str, raw: bytes) -> (list, list):
    """(report lines, referenced graph names) of one graph."""
    root = ET.fromstring(raw.decode("utf-8-sig", errors="replace"))
    lines, refs, kinds = [f"=== {name}"], [], {}
    # graph nodes only: a link's target is a <node> element too (its text is the 1-based source index)
    for i, node in enumerate(n for n in root.iter("node") if n.find("node_type") is not None):
        kind = node.findtext("node_type")
        kinds[kind] = kinds.get(kind, 0) + 1
        rows = _rows(node)
        if kind == "NT_GRAPH_REF" and rows.get("Graph Ref"):
            refs.append(rows["Graph Ref"])
        why = interesting(node)
        if not why:
            continue
        lines.append(f"  [{i}] {kind} '{node.findtext('name') or ''}' ({why})")
        for k, v in rows.items():
            if v:
                lines.append(f"      {k} = {v}")
        for inp, src, cond in _inputs(node):
            lines.append(f"      <- input '{inp}' from node {src}" + (f": {cond}" if cond else ""))
    lines.insert(1, "  node types: " + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())))
    return lines, refs


def stem(ref: str) -> str:
    return os.path.splitext(os.path.basename(ref.replace("\\", "/")))[0].lower()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield-data", required=True)
    ap.add_argument("--out", required=True, help="report text file (outside the repository)")
    ap.add_argument("--graph", action="append", default=[], help="a loose .agx to read instead of the archive's copy")
    ap.add_argument("--max-graphs", type=int, default=40)
    a = ap.parse_args(argv)
    if os.path.abspath(a.out).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    import hkx_to_af
    loose = {stem(p): p for p in a.graph}
    todo, seen, report = [START], set(), []
    while todo and len(seen) < a.max_graphs:
        g = todo.pop(0)
        if g in seen:
            continue
        seen.add(g)
        try:
            raw, _ = hkx_to_af.vanilla_file(loose.get(g) or f"{GRAPHS}{g}.agx", a.starfield_data)
        except SystemExit as e:
            report.append(f"=== {g}: not read ({e})")
            continue
        lines, refs = probe(g, raw)
        report += lines
        todo += [stem(r) for r in refs if stem(r) not in seen]
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(report) + "\n")
    print(f"{len(seen)} graphs read; {sum(1 for x in report if x.startswith('  ['))} nodes listed -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
