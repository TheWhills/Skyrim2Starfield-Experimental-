"""Dodge states for the player's melee graph: TK Dodge's events play converted dodge clips (graph-side prep for the
combat plugin, docs/armor/combat-plugin-spec.md "Dodge").

--attacks-graph (the stance packs' way, 2026-10-23): the dodges become full-body states at the top of MeleeAttacks.agx
(copies of the standing power attack: entered from idle, the combo, the attacks and each other; back to idle when the
clip ends, which sends AttackEnd), on event names the game already knows (KNOWN_EVENTS: the NPC melee attack events,
which it never sends to the player; new names are refused by the graph, owner's logs), and Player_Melee.agx's attack
switch (the Attacking option that MeleeAttackPowerStart selects) learns those events so the dodge plays full body.
The plugin's sDodgeEvents must name the same events. The MeleeActions variant below is the earlier, untested layout.

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


# Event names Starfield's graphs already know and never send to the player: the NPC melee attack events
# (npc_meleeattacks.agx). Owner's logs 2026-10-23: new names (TKDodgeBack, S2S_ComboPower) are "not taken by the graph".
KNOWN_EVENTS = {"Forward": "MeleeAttack01", "Back": "MeleeAttack02", "Left": "MeleeAttack03", "Right": "MeleeAttack04",
                "ForwardLeft": "MeleeAttack05", "ForwardRight": "MeleeAttackPower01", "BackLeft": "MeleeAttackPower02"}
ATTACKS_REL = ("meshes", "animtextdata", "tables", "graphs", "meleeattacks.agx")
PLAYER_REL = ("meshes", "animtextdata", "tables", "graphs", "player_melee.agx")
POWER_TOP, POWER_EVENT = "MeleeAttackPower_A", "MeleeAttackPowerStart"


def build_attacks(raw: bytes, directions=FOUR, events=None, tags=None, blend_in=0.1, blend_out=0.2):
    """(graph bytes, report): dodge states at the top of MeleeAttacks.agx, played full body like the standing power
    attack. Each is a copy of MeleeAttackPower_A (its AttackStart enter event; root motion as for attacks), entered on
    its event from idle, the combo, the top-level attacks and the other dodges, and back to idle when the clip ends
    (the idle state sends AttackEnd, which also ends the plugin's dodge). Use with add_switch_events on Player_Melee."""
    root = agx_edit.load(raw)
    g = root
    nodes = g.findall("node")
    power = agx_edit.state(g, POWER_TOP)
    t = agx_edit.transitions(g)
    idle = next((s for s, d, e, _c in t if d == power and e == POWER_EVENT
                 and agx_edit._rows(nodes[s]).get("TagName") in (None, "", "None")), None)
    if idle is None:
        raise agx_edit.AgxEditError("no idle state that starts MeleeAttackPower_A")
    enter = next((l for l in agx_edit._links_into(nodes[power])
                  if agx_edit._rows(l).get("Event") == POWER_EVENT and int(l.findtext("node")) - 1 == idle), None)
    leave = next((l for l in agx_edit._links_into(nodes[idle])
                  if int(l.findtext("node")) - 1 == power and not agx_edit._rows(l).get("Event")
                  and not agx_edit._rows(l).get("Condition")), None)
    existing = {e for _s, _d, e, _c in t}
    sources = [i for i, n in enumerate(nodes) if i != idle and (agx_edit._rows(n).get("TagName") not in (None, "", "None")
                                                                or agx_edit._rows(n).get("State Machine Name"))]
    report = {"states": {}, "idle": idle}
    made = {}
    for d in directions:
        event = (events or {}).get(d) or KNOWN_EVENTS.get(d) or f"TKDodge{d}"
        if event in existing:
            raise agx_edit.AgxEditError(f"{event} is already used in this graph")
        tag = (tags or {}).get(d) or f"S2S_Dodge{d}"
        i = agx_edit.clone_state(g.findall("node")[power], g, root)
        agx_edit.set_tag(g.findall("node")[i], tag)
        agx_edit.set_row(g.findall("node")[i], "Speed Multiplier", "")      # not scaled by the weapon's speed
        made[d] = (i, event, tag)
    dodge_states = [i for i, _e, _t in made.values()]
    for d, (i, event, tag) in made.items():
        for src in [idle] + sources + dodge_states:
            agx_edit.add_transition(root, g, src, i, event, blend_in, template=enter)
        agx_edit.add_transition(root, g, i, idle, "", blend_out, template=leave)
        report["states"][d] = {"index": i, "event": event, "tag": tag}
    return agx_edit.dump(root, raw), report


def add_switch_events(raw: bytes, events) -> (bytes, int):
    """Player_Melee.agx with `events` added wherever it lists MeleeAttackPowerStart as an event that switches to the
    full-body attack graph (the Attacking option of the Switch / Blend Node over MeleeAttacks): a dodge then plays full
    body like the standing power attack. Returns (bytes, lists changed)."""
    root = agx_edit.load(raw)
    n = 0
    for row in root.iter("row"):
        for p in row.findall("prop"):
            v = p.find("value")
            if v is None or not v.text:
                continue
            items = [x.strip() for x in v.text.split(",")]
            if POWER_EVENT in items:
                v.text = ",".join(items + [e for e in events if e not in items])
                n += 1
    if not n:
        raise agx_edit.AgxEditError("no MeleeAttackPowerStart switch list in this graph")
    return agx_edit.dump(root, raw), n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", help="the vanilla MeleeActions.agx")
    ap.add_argument("--out", required=True, help="pack root (Data layout)")
    ap.add_argument("--eight-way", action="store_true", help="diagonals too (TK Dodge 8-way)")
    ap.add_argument("--tag", action="append", default=[], metavar="DIRECTION=TAG",
                    help="clip tag for a direction instead of TKDodge<Direction> (repeatable)")
    ap.add_argument("--template", default="MeleeBlock_Out", help="the action state the dodge states copy")
    ap.add_argument("--attacks-graph", help="MeleeAttacks.agx (e.g. a stance pack's): put full-body dodge states "
                    "there instead of MeleeActions (needs --player-graph); --graph is then not used")
    ap.add_argument("--player-graph", help="the vanilla Player_Melee.agx (its attack switch learns the dodge events)")
    ap.add_argument("--event", action="append", default=[], metavar="DIRECTION=EVENT",
                    help="graph event for a direction (with --attacks-graph; default: the NPC attack events, "
                         "KNOWN_EVENTS)")
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
    if a.attacks_graph:
        if not a.player_graph:
            sys.exit("--attacks-graph needs --player-graph")
        events = {}
        for spec in a.event:
            d, _, e = spec.partition("=")
            if d not in dirs or not e:
                sys.exit(f"--event wants DIRECTION=EVENT with DIRECTION one of {', '.join(dirs)}; got {spec}")
            events[d] = e
        with open(a.attacks_graph, "rb") as fh:
            data, report = build_attacks(fh.read(), dirs, events, tags)
        with open(a.player_graph, "rb") as fh:
            pdata, nlists = add_switch_events(fh.read(), [st["event"] for st in report["states"].values()])
        for rel, blob in ((ATTACKS_REL, data), (PLAYER_REL, pdata)):
            dst = os.path.join(out, *rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(blob)
        for d, st in report["states"].items():
            print(f"{st['event']} -> state {st['index']} playing {st['tag']}")
        print(f"player graph: {nlists} attack switch lists learned the dodge events")
        return 0
    if not a.graph:
        sys.exit("--graph (MeleeActions.agx) or --attacks-graph is required")
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
