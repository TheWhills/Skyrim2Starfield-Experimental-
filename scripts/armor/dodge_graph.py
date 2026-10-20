"""Dodge states for the player's melee graph: TK Dodge's events play converted dodge clips (graph-side prep for the
combat plugin, docs/armor/combat-plugin-spec.md "Dodge").

The vanilla MeleeActions.agx top machine enters every action from any state on its start event (a self-link: CastSelf
on CastSelfStart, ...) and leaves to the IdleTimer machine without an event when the clip ends (verified on the
vanilla graph, see fo4sf.agx_edit). Each dodge direction becomes one more such action: a copy of a simple action state
(default MeleeBlock_Out: a clip, no sync system), playing the direction's clip tag, entered on TKDodge<Direction>
(the event the plugin sends: s2s::combat::dodge_event), sending TKDR_DodgeEnd when its clip ends (the plugin's dodge
end), and leaving to IdleTimer.

    python -I scripts\\armor\\dodge_graph.py --graph <extract>\\meleeactions.agx --out <pack> [--eight-way]
        [--tag Forward=<clip tag> ...]

Clip tags default to the event names (TKDodgeForward ...): clips converted with hkx_to_af --tag TKDodgeForward.
New tags may need the Creation Kit's animation-cache rebuild (unresolved, pc_checklist step 1); --tag can point a
direction at a vanilla tag whose clip a pack replaces instead. Unresolved too: whether these states can interrupt an
attack (MeleeAttacks is a separate graph) and whether event names new to the graph reach it (they are plain names in
the .agx, like every vanilla event).
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import agx_edit  # noqa: E402

GRAPH_REL = ("meshes", "animtextdata", "tables", "graphs", "meleeactions.agx")
FOUR = ("Forward", "Back", "Left", "Right")
EIGHT = FOUR + ("ForwardLeft", "ForwardRight", "BackLeft", "BackRight")
IDLE = "IdleTimer"
END_EVENT = "TKDR_DodgeEnd"


def _link_template(graph, want_self: bool, dst=None):
    """A vanilla link to copy: an any-state self-link with an event, or an event-less exit into `dst`."""
    nodes = graph.findall("node")
    for t, n in enumerate(nodes):
        if dst is not None and t != dst:
            continue
        for link in agx_edit._links_into(n):
            src = int(link.findtext("node")) - 1
            ev = agx_edit._rows(link).get("Event") or ""
            if want_self and src == t and ev:
                return link
            if not want_self and src != t and not ev:
                return link
    return None


def build(raw: bytes, directions=FOUR, tags=None, template="MeleeBlock_Out", blend_in=0.1, blend_out=0.2):
    """(graph bytes, report): one dodge state per direction in the top machine of MeleeActions.agx."""
    root = agx_edit.load(raw)
    g = agx_edit.machine(root)
    idle = agx_edit.state(g, IDLE)
    tpl = agx_edit.state(g, template)
    enter, leave = _link_template(g, True), _link_template(g, False, idle)
    existing = {e for _s, _d, e, _c in agx_edit.transitions(g)}
    report = {"states": {}, "template": template, "idle": IDLE}
    for d in directions:
        event = f"TKDodge{d}"
        if event in existing:
            raise agx_edit.AgxEditError(f"{event} is already used in this graph")
        tag = (tags or {}).get(d) or event
        i = agx_edit.clone_state(g.findall("node")[tpl], g, root)
        node = g.findall("node")[i]
        agx_edit.set_tag(node, tag)
        agx_edit.set_row(node, "Send Event On End", END_EVENT)
        agx_edit.set_row(node, "State Variable", "")
        agx_edit.add_transition(root, g, i, i, event, blend_in, template=enter)
        agx_edit.add_transition(root, g, i, idle, "", blend_out, template=leave)
        report["states"][d] = {"index": i, "event": event, "tag": tag}
    return agx_edit.dump(root, raw), report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", required=True, help="the vanilla MeleeActions.agx")
    ap.add_argument("--out", required=True, help="pack root (Data layout)")
    ap.add_argument("--eight-way", action="store_true", help="diagonals too (TK Dodge 8-way)")
    ap.add_argument("--tag", action="append", default=[], metavar="DIRECTION=TAG",
                    help="clip tag for a direction instead of TKDodge<Direction> (repeatable)")
    ap.add_argument("--template", default="MeleeBlock_Out", help="the action state the dodge states copy")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    dirs = EIGHT if a.eight_way else FOUR
    tags = {}
    for spec in a.tag:
        d, _, t = spec.partition("=")
        if d not in dirs or not t:
            sys.exit(f"--tag wants DIRECTION=TAG with DIRECTION one of {', '.join(dirs)}; got {spec}")
        tags[d] = t
    with open(a.graph, "rb") as fh:
        data, report = build(fh.read(), dirs, tags, a.template)
    dst = os.path.join(out, *GRAPH_REL)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(data)
    for d, st in report["states"].items():
        print(f"{st['event']} -> state {st['index']} playing {st['tag']}")
    print(f"graph {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
