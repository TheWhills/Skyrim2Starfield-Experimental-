"""How Skyrim's smithing animations are built (read-only): the stations' records, the behaviour state machines that
play the smithing clips (states, the order they chain in, the events between them), the props they load, and each
clip's own events. Step 1 of putting Skyrim's smithing animations on our forge / anvil / grindstone / workbench /
smelter (docs/npc/furniture.md "Smithing").

2026-11-16, owner: "let's work through the smithing animations. These are going to be more complicated because in
Skyrim the character takes a sword, puts them in water trough, and also puts them in the forge, etc. There's hammering,
it's a whole thing." So a smithing station is not one idle loop (as the sit / lean / sweep sets are) but a sequence of
clips with props swapped between them; this finds that sequence before anything is converted.

Prints (all from Skyrim.esm and Skyrim's archives; nothing is copied):
  1. FURN / IDLM records whose EditorID looks like smithing (--match): model, keywords, workbench type, markers and
     the animation each marker names; IDLE records that match (event, behaviour file); ANIO records that match (prop
     model) - the props the clips load.
  2. Every character behaviour graph with a clip matching --match: each state machine that holds such clips, with
     its start state, states (id, name, the clips under it), transitions (event -> state) and wildcard transitions;
     the clips' triggers (time, event, payload: AnimObjLoad / AnimObjDraw name the prop) and every string payload in
     the graph that looks like a prop.
  3. Each matching clip file: duration, frames and its annotations (time, text).

    python -I scripts\\armor\\smithing_probe.py --skyrim-data "<Skyrim SE>\\Data" > smithing_probe.txt
"""
import argparse
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts", "interior"))

MATCH = (r"smith|forge|anvil|grindstone|sharpen|smelt|tongs|hammer|quench|trough|bellows|ingot|"
         r"craftingsmithing|blacksmith|armortable|workbench")
BEHAVIORS = "meshes\\actors\\character\\behaviors\\"


def machines_with(b: dict, rx) -> list:
    """State machines of a read behaviour (skyrimbehavior.read) whose subtree holds a clip matching rx, each as
    {"name", "start", "mode", "states": [{"id", "name", "clips", "transitions": [(event, to state name)]}],
    "wildcard": [(event, to state name)]}; clips are the animation file names (no folders) under the state's
    generator, nested machines included."""
    nodes, events = b["nodes"], b["events"]

    def clips_under(o, seen):
        if o is None or o in seen or o not in nodes:
            return []
        seen.add(o)
        n = nodes[o]
        out = []
        if n["class"] == "hkbClipGenerator":
            out.append(os.path.basename((n.get("animation") or "").replace("\\", "/")))
        follow = list(n.get("children", [])) + list(n.get("states") or []) + list(n.get("blend_children") or [])
        follow += [n[k] for k in ("generator",) if n.get(k) is not None]
        for c in follow:
            out += clips_under(c, seen)
        return out

    def ev(i):
        return events[i] if 0 <= i < len(events) else f"#{i}"

    out = []
    for o, n in nodes.items():
        if n["class"] != "hkbStateMachine":
            continue
        all_clips = clips_under(o, set())
        if not any(rx.search(c) for c in all_clips):
            continue
        states = [nodes[s] for s in n["states"] if s in nodes]
        name_of = {s.get("state_id"): s.get("name") for s in states}
        rows = []
        for s in states:
            tr = nodes.get(s.get("transitions"), {}).get("transitions") or []
            rows.append({"id": s.get("state_id"), "name": s.get("name"),
                         "clips": sorted(set(clips_under(s.get("generator"), set()))),
                         "transitions": [(ev(t["event"]), name_of.get(t["to_state"], t["to_state"])) for t in tr]})
        wild = nodes.get(n.get("wildcard"), {}).get("transitions") or []
        out.append({"name": n.get("name"), "start": name_of.get(n.get("start_state"), n.get("start_state")),
                    "mode": n.get("start_mode"), "states": rows,
                    "wildcard": [(ev(t["event"]), name_of.get(t["to_state"], t["to_state"])) for t in wild]})
    return sorted(out, key=lambda m: m["name"] or "")


def clip_triggers(b: dict, rx) -> list:
    """[(clip generator name, animation file, [(time, event, payload text)])] for matching clips with triggers."""
    nodes, events = b["nodes"], b["events"]
    out = []
    for n in nodes.values():
        if n["class"] != "hkbClipGenerator":
            continue
        anim = os.path.basename((n.get("animation") or "").replace("\\", "/"))
        if not (rx.search(anim) or rx.search(n.get("name") or "")):
            continue
        tr = nodes.get(n.get("triggers"), {}).get("triggers") or []
        rows = [(t["time"], events[t["event"]] if 0 <= t["event"] < len(events) else f"#{t['event']}",
                 nodes.get(t["payload"], {}).get("data")) for t in tr]
        if rows:
            out.append((n.get("name"), anim, rows))
    return sorted(out, key=lambda x: (x[1], x[0] or ""))


def payload_strings(b: dict, rx=re.compile(r"animobj|object|prop", re.I)) -> list:
    return sorted({n["data"] for n in b["nodes"].values() if n["class"] == "hkbStringEventPayload" and n.get("data")
                   and rx.search(n["data"])})


def records(sky_data: str, rx) -> list:
    """Printable lines for section 1."""
    from fo4sf import packages
    import furniture_survey as survey
    from furniture_anim_survey import idle_info
    z = lambda d: d.rstrip(b"\0").decode("utf-8", "replace")                     # noqa: E731
    ix = packages.Index(os.path.join(sky_data, "Skyrim.esm"))
    lines = []
    try:
        for typ in (b"FURN", b"IDLM", b"IDLE", b"ANIO"):
            for f in sorted(ix.by_type.get(typ, [])):
                e = ix.edid(f) or ""
                if not rx.search(e):
                    continue
                if typ in (b"FURN", b"IDLM"):
                    try:
                        rec = survey.base_record(ix, f, starfield=False)
                    except Exception as ex:                         # noqa: BLE001
                        rec = {"error": f"{type(ex).__name__}: {ex}"}
                    keep = {k: rec.get(k) for k in ("model", "keywords", "bench_type", "animations", "nif_markers",
                                                     "mnam", "error") if rec.get(k)}
                    lines.append(f"  {typ.decode()} {f:08X} {e}: {keep}")
                elif typ == b"IDLE":
                    lines.append(f"  IDLE {f:08X} {idle_info(ix.subs(f))}")
                else:
                    subs = ix.subs(f)
                    model = next((z(d) for s, d in subs if s == b"MODL"), "")
                    other = {s.decode(): z(d) for s, d in subs if s in (b"BNAM",)}
                    lines.append(f"  ANIO {f:08X} {e}: model {model} {other or ''}")
    finally:
        ix.close()
    return lines


def prop_sources(b: dict, rx=re.compile(r"animobj", re.I)) -> dict:
    """{prop payload text: [where it is sent]} for string payloads matching rx: a clip trigger ("clip <name> <time>
    s <event>"), a state's enter / exit events ("state <name> enter <event>"), or else the nearest named node that
    points at it ("<class> <name>"). 2026-11-17 (owner's work_probe2): the axe, hoe and pickaxe are payloads in the
    graph but in no clip trigger, so where they are sent is what a prop conversion has to read."""
    nodes, events = b["nodes"], b["events"]

    def ev(i):
        return events[i] if 0 <= i < len(events) else f"#{i}"

    def text(pid):
        d = nodes.get(pid, {}).get("data")
        return d if d and rx.search(d) else None

    out, seen = {}, set()
    for o, n in nodes.items():
        if n["class"] == "hkbStateMachineStateInfo":
            for key, how in (("enter_events", "enter"), ("exit_events", "exit")):
                for e in nodes.get(n.get(key), {}).get("events") or []:
                    t = text(e["payload"])
                    if t:
                        out.setdefault(t, []).append(f"state {n.get('name')!r} {how} {ev(e['event'])}")
                        seen.add(e["payload"])
        elif n["class"] == "hkbClipGenerator":
            for tr in nodes.get(n.get("triggers"), {}).get("triggers") or []:
                t = text(tr["payload"])
                if t:
                    out.setdefault(t, []).append(f"clip {n.get('name')!r} {tr['time']:g} s {ev(tr['event'])}")
                    seen.add(tr["payload"])
    parents = {}
    for o, n in nodes.items():
        for c in n.get("children", []):
            parents.setdefault(c, []).append(o)
    for pid, n in nodes.items():
        t = text(pid) if n["class"] == "hkbStringEventPayload" else None
        if not t or pid in seen:
            continue
        found = []
        for par in parents.get(pid, []):
            cur, depth = par, 0
            while cur is not None and not nodes[cur].get("name") and depth < 4:
                cur, depth = (parents.get(cur) or [None])[0], depth + 1
            if cur is not None:
                found.append(f"{nodes[cur]['class']} {nodes[cur].get('name')!r}")
        out.setdefault(t, []).extend(found or ["(not referenced)"])
    return {k: sorted(set(v)) for k, v in sorted(out.items())}


def clip_file_index(names) -> dict:
    """{clip file name (lower): archive path} for character animations, third person first (2026-11-17: sorted
    paths put _1stperson before animations, so the chop and mill-load clips came out as their first-person files)."""
    by_base = {}
    for n in sorted(names, key=lambda x: ("\\_1stperson\\" in x, x)):
        if n.startswith("meshes\\actors\\character\\") and n.endswith(".hkx"):
            by_base.setdefault(n.replace("/", "\\").rsplit("\\", 1)[-1], n)
    return by_base


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--match", default=MATCH)
    ap.add_argument("--no-records", action="store_true")
    a = ap.parse_args(argv)
    from fo4sf import bsa, skyrimhkx
    from fo4sf import skyrimbehavior as SB
    rx = re.compile(a.match, re.I)
    if not a.no_records:
        print("== 1. records (FURN / IDLM / IDLE / ANIO)")
        for line in records(a.skyrim_data, rx):
            print(line)
    arcs = bsa.SkyrimArchives(a.skyrim_data, loose=False)
    names = sorted({bsa.norm(n) for ar in arcs.archives for n in ar.names})
    print("== 2. behaviour graphs")
    clip_paths = {}
    for n in names:
        if not (n.startswith(BEHAVIORS) and n.endswith(".hkx")):
            continue
        try:
            b = SB.read(arcs._read(n))
        except Exception as e:                                      # noqa: BLE001
            continue
        sms = machines_with(b, rx)
        if not sms:
            continue
        print(f"-- {n} ({b['name']})")
        for m in sms:
            print(f"  machine {m['name']!r} start {m['start']!r} mode {m['mode']}")
            for s in m["states"]:
                print(f"    state {s['id']} {s['name']!r}: clips {s['clips']}")
                for evn, to in s["transitions"]:
                    print(f"      on {evn} -> {to!r}")
            for evn, to in m["wildcard"]:
                print(f"    any state: on {evn} -> {to!r}")
        for gen, anim, rows in clip_triggers(b, rx):
            print(f"  clip {gen} ({anim}) triggers: " + ", ".join(f"{t:g} {e}{' ' + p if p else ''}"
                                                                 for t, e, p in rows))
        props = payload_strings(b)
        if props:
            print(f"  prop payloads: {props}")
        for prop, where in prop_sources(b).items():
            if rx.search(prop) or any(rx.search(w) for w in where):
                print(f"  prop {prop}: " + "; ".join(where))
        for node in b["nodes"].values():
            if node["class"] == "hkbClipGenerator" and rx.search(node.get("animation") or ""):
                clip_paths[os.path.basename(node["animation"].replace("\\", "/")).lower()] = node["animation"]
    print("== 3. clip files")
    by_base = clip_file_index(names)
    for base in sorted(clip_paths):
        path = by_base.get(base)
        if not path:
            print(f"  {base}: not found in the archives")
            continue
        try:
            d = skyrimhkx.describe(arcs._read(path))
            an = (d.get("animations") or [{}])[0]
            notes = ", ".join(f"{x['time']:g} {x['text']}" for x in an.get("annotations", []))
            print(f"  {path}: {an.get('duration', 0):.2f} s, {an.get('frames')} frames; {notes}")
        except Exception as e:                                      # noqa: BLE001
            print(f"  {path}: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
