"""Where a Skyrim furniture object's own sound comes from (read-only): the object's model, its behaviour graph and
clips, and the sound records whose EditorID matches.

2026-11-20 (owner, in game after the all-sets sound run: "Grindstone isnt playing its own sound??"). The character
side has none (owner's smithing_probe, verified): Skyrim's BlacksmithSharpeningWheelEnter / Spin / Exit clips carry no
SoundPlay trigger (Enter: 00NextClip, Exit: IdleFurnitureExit, Spin: no triggers) and no annotations, so
furniture_anim_pack found no Skyrim sound for the Grindstone set and its descriptors kept the template's (the impact
wrench's) foley. The wheel's sound must then come from the wheel itself: its animated model
(Furniture\\Clutter\\BlacksmithSharpeningWheelAnimating.nif), which Skyrim drives with a graph of its own. This prints:
  1. the model: block types, the behaviour graph it names (BSBehaviorGraphExtraData), its text keys
     (NiTextKeyExtraData: time, text) and every .hkx / .kf path in it;
  2. each such graph (and every other non-character behaviour .hkx whose path or bytes match --match): its events,
     state machines (states, clips, transitions), every clip trigger, every state enter / exit event (with payloads);
  3. those graphs' clip files: duration and annotations;
  4. Skyrim.esm SOUN / SNDR records whose EditorID matches --sound-match, with the files they play.

    python -I scripts\\armor\\object_sound_probe.py --skyrim-data "<Skyrim SE>\\Data" > object_sound_probe.txt
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

MODEL = "Furniture\\Clutter\\BlacksmithSharpeningWheelAnimating.nif"
MATCH = r"sharpen|grind|wheel"
SOUND_MATCH = r"sharpen|grind|whetstone|wheel"
CHARACTER = "meshes\\actors\\character\\"


def _string(n, idx):
    return n.strings[idx].decode("latin-1") if 0 <= idx < len(n.strings) else None


def model_info(n) -> dict:
    """{"types": {block type: count}, "graphs": [graph file], "text_keys": [(time, text)], "paths": [...]} of a parsed
    Skyrim NIF (nif.parse). BSBehaviorGraphExtraData: name (string index), graph file (string index), controls base
    skeleton (byte); NiTextKeyExtraData: name, key count, then (float time, string index) per key."""
    from fo4sf import nif as N
    types, graphs, keys = {}, [], []
    for i, blk in enumerate(n.blocks):
        t = n.type_of(i)
        types[t] = types.get(t, 0) + 1
        try:
            if t == "BSBehaviorGraphExtraData" and len(blk) >= 8:
                g = _string(n, struct.unpack_from("<i", blk, 4)[0])
                if g:
                    graphs.append(g)
            elif t == "NiTextKeyExtraData" and len(blk) >= 8:
                cnt, = struct.unpack_from("<I", blk, 4)
                for k in range(min(cnt, (len(blk) - 8) // 8)):
                    tm, si = struct.unpack_from("<fi", blk, 8 + 8 * k)
                    keys.append((round(tm, 4), _string(n, si)))
        except struct.error:
            continue
    paths = [p for p in N.referenced_paths(n) if p.lower().endswith(".hkx")]
    for s in n.strings:
        txt = s.decode("latin-1")
        if txt.lower().endswith((".hkx", ".kf")) and txt not in paths:
            paths.append(txt)
    return {"types": types, "graphs": graphs, "text_keys": keys, "paths": sorted(set(paths))}


def graph_lines(b: dict) -> list:
    """Printable lines for one read behaviour (skyrimbehavior.read): events, machines, every clip trigger and every
    state enter / exit event."""
    import smithing_probe as SP
    nodes, events = b["nodes"], b["events"]

    def ev(i):
        return events[i] if 0 <= i < len(events) else f"#{i}"

    def pay(p):
        d = nodes.get(p, {}).get("data")
        return " " + d if d else ""
    lines = [f"  events: {events}"]
    every = re.compile(r".")
    for m in SP.machines_with(b, every):
        lines.append(f"  machine {m['name']!r} start {m['start']!r}")
        for s in m["states"]:
            lines.append(f"    state {s['id']} {s['name']!r}: clips {s['clips']}")
            for e, to in s["transitions"]:
                lines.append(f"      on {e} -> {to!r}")
        for e, to in m["wildcard"]:
            lines.append(f"    any state: on {e} -> {to!r}")
    for n in nodes.values():
        if n["class"] == "hkbClipGenerator":
            tr = nodes.get(n.get("triggers"), {}).get("triggers") or []
            rows = ", ".join(f"{t['time']:g}{' (from end)' if t.get('relative_to_end') else ''} {ev(t['event'])}"
                             f"{pay(t['payload'])}" for t in tr)
            lines.append(f"  clip {n.get('name')!r} ({n.get('animation')}): {rows or 'no triggers'}")
        elif n["class"] == "hkbStateMachineStateInfo":
            for key in ("enter_events", "exit_events"):
                es = nodes.get(n.get(key), {}).get("events") or []
                if es:
                    lines.append(f"  state {n.get('name')!r} {key.split('_')[0]}: "
                                 + ", ".join(f"{ev(e['event'])}{pay(e['payload'])}" for e in es))
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--match", default=MATCH)
    ap.add_argument("--sound-match", default=SOUND_MATCH)
    a = ap.parse_args(argv)
    from fo4sf import bsa, nif, skyrimhkx
    from fo4sf import skyrimbehavior as SB
    rx = re.compile(a.match, re.I)
    arcs = bsa.SkyrimArchives(a.skyrim_data)
    names = sorted({bsa.norm(x) for ar in arcs.archives for x in ar.names})

    print(f"== 1. model {a.model}")
    graphs = []
    data = arcs.mesh(a.model)
    if data is None:
        print("  not found in the archives")
    else:
        try:
            info = model_info(nif.parse(data))
            for k in ("types", "graphs", "text_keys", "paths"):
                print(f"  {k}: {info[k]}")
            graphs = [bsa.norm(g if g.lower().startswith("meshes\\") else "meshes\\" + g) for g in info["graphs"]]
        except Exception as e:                                      # noqa: BLE001
            print(f"  unreadable: {type(e).__name__}: {e}")

    print("== 2. behaviour graphs")
    keys = [k.encode() for k in a.match.split("|")]
    for n in names:
        if n.startswith(CHARACTER) or not n.endswith(".hkx") or "behavior" not in n:
            continue
        if n in graphs or rx.search(n):
            graphs.append(n)
            continue
        d = arcs._read(n)
        if d and any(k in d.lower() for k in keys):
            graphs.append(n)
    clips = {}
    for g in dict.fromkeys(graphs):
        d = arcs._read(g)
        if d is None:
            print(f"-- {g}: not found")
            continue
        try:
            b = SB.read(d)
        except Exception as e:                                      # noqa: BLE001
            print(f"-- {g}: unreadable ({type(e).__name__}: {e})")
            continue
        print(f"-- {g} ({b['name']})")
        for line in graph_lines(b):
            print(line)
        for node in b["nodes"].values():
            if node["class"] == "hkbClipGenerator" and node.get("animation"):
                clips[os.path.basename(node["animation"].replace("\\", "/")).lower()] = g

    print("== 3. clip files")
    by_base = {}
    for n in names:
        if n.endswith(".hkx") and not n.startswith(CHARACTER):
            by_base.setdefault(n.rsplit("\\", 1)[-1], []).append(n)
    for base, g in sorted(clips.items()):
        for path in by_base.get(base, []) or [None]:
            if path is None:
                print(f"  {base} (from {g}): not found outside the character folder")
                continue
            try:
                an = (skyrimhkx.describe(arcs._read(path)).get("animations") or [{}])[0]
                notes = ", ".join(f"{x['time']:g} {x['text']}" for x in an.get("annotations", []))
                print(f"  {path}: {an.get('duration', 0):.2f} s; annotations: {notes or 'none'}")
            except Exception as e:                                  # noqa: BLE001
                print(f"  {path}: unreadable ({type(e).__name__}: {e})")

    print("== 4. sound records")
    from fo4sf import packages
    import sound_records as SR
    srx = re.compile(a.sound_match, re.I)
    ix = packages.Index(os.path.join(a.skyrim_data, "Skyrim.esm"))
    try:
        hits = sorted({ix.edid(f) for t in (b"SOUN", b"SNDR") for f in ix.by_type.get(t, [])
                       if srx.search(ix.edid(f) or "")} - {None})
    finally:
        ix.close()
    print(f"  {len(hits)} matching: {hits}")
    for line in SR.skyrim_sounds(a.skyrim_data, hits):
        print(line)


if __name__ == "__main__":
    main()
