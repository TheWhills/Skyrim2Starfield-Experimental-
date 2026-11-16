"""What a piece of furniture can play, and from where (read-only): every animation tag of its graphs (the graph its
subgraph entries name and every graph that one links, recursively), and for each tag the first folder of each entry's
folder chain that has a descriptor for it, against our set's folder.

2026-11-15, owner, in game: seated (player and Hilde), the arms bend back and the hands go into the body for a moment,
after our sets answered every tag in furniture\\chair, \\bench, their female folders and furniture\\common, and with
our flavors replaced by the Idle. The chair / bench entries are HumanRace's own (Starfield.esm) plus the pirate table
rows; their chains and the graphs' own tags (the furniture graph plays GripOffset_LeftArm / _RightArm and links
NPC_IdlePartialBody, LookAt_Chest, LookAt_Head, InCameraValues) were not all checked.

    python -I scripts\\armor\\furniture_graph_probe.py --starfield "<Starfield>" --keyword AnimFurnChair
        --keyword AnimFurnBench --ours "<mods>\\S2S Furniture Anims\\meshes\\actors\\human\\animations\\furniture\\s2s_sit"
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import agx, sfplugin, subgraph  # noqa: E402

THIRD = lambda flags: bool(flags) and flags.replace(" ", "")[:4] == "0200" and flags.replace(" ", "")[4:8] == "0000"  # noqa: E731


def tag_of(text: str):
    m = re.search(r"<tag>\s*([^<]*?)\s*</tag>", text)
    return m.group(1) if m else None


def folder_tags(names, read, folder: str) -> dict:
    """{tag lower: (file name, has bEnableHandIK)} of the descriptors directly in an archive folder."""
    f = folder.lower().replace("/", "\\").rstrip("\\") + "\\"
    out = {}
    for n in names:
        if n.startswith(f) and n.endswith(".afx") and "\\" not in n[len(f):]:
            raw = read(n)
            text = raw.decode("utf-8", "replace") if raw else ""
            t = tag_of(text)
            if t and t.lower() not in out:
                out[t.lower()] = (n[len(f):], "benablehandik" in text.lower())
    return out


events_of = {}      # graph name -> the events its links react to (graph_tags fills it)


def graph_tags(names, read, graph: str, seen=None) -> dict:
    """{graph name: (tags, alterations)} for a graph and every graph it links (recursively)."""
    seen = {} if seen is None else seen
    key = os.path.splitext(os.path.basename(graph.replace("/", "\\")))[0].lower()
    if key in seen:
        return seen
    hit = next((n for n in names if n.endswith("\\" + key + ".agx")), None)
    if hit is None:
        seen[key] = (None, None)
        return seen
    try:
        s = agx.summary(agx.read_graph(read(hit)))
    except Exception as e:                                         # noqa: BLE001
        seen[key] = (f"not read: {type(e).__name__}", None)
        return seen
    seen[key] = (sorted(set(s["tags"])), s["tag_alterations"])
    events_of[key] = s["events"]
    for ref in s["graph_refs"]:
        graph_tags(names, read, ref, seen)
    return seen


def resolve(tag: str, chains: list, tags_by_folder: dict, ours: set):
    """'ours', or the distinct first folders (with a hand-IK mark) answering `tag` over the chains, or []."""
    if tag.lower() in ours:
        return "ours"
    hits = []
    for chain in chains:
        for f in chain:
            got = tags_by_folder.get(f, {}).get(tag.lower())
            if got:
                label = f.split("animations\\")[-1] + "\\" + got[0] + (" (hand IK)" if got[1] else "")
                if label not in hits:
                    hits.append(label)
                break
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--keyword", action="append", required=True)
    ap.add_argument("--ours", help="our set's folder on disk (its descriptors' tags count as answered)")
    ap.add_argument("--graph", action="append", default=[],
                    help="another graph to resolve (repeatable), e.g. FurnitureRandomSitChair: 2026-11-15 the owner's "
                         "S2SCombat log showed our chair enter sending LoadFurnitureGraph with that graph, then "
                         "IdleFlavor / FlavorEnd from it")
    a = ap.parse_args(argv)
    import furniture_anim_survey as S
    import stance_plugin
    data = os.path.join(a.starfield, "Data")
    esm = os.path.join(data, "Starfield.esm")
    recs = sfplugin.records(esm, [b"KYWD", b"RACE"])
    kw = {sfplugin.edid(r[2]).lower(): r[3] for r in recs if r[0] == b"KYWD" and sfplugin.edid(r[2])}
    names_of = {v: k for k, v in kw.items()}
    want = {kw[k.lower()] for k in a.keyword if k.lower() in kw}
    human = next(r for r in recs if r[0] == b"RACE" and sfplugin.edid(r[2]) == "HumanRace")
    rows = []
    for e in subgraph.parse(human[2]):
        if THIRD(e.get("flags")) and want & set(e["target_keywords"]):
            rows.append(("esm", [names_of.get(x, f"{x:08X}") for x in e["actor_keywords"]],
                         [names_of.get(x, f"{x:08X}") for x in e["target_keywords"]], e["graph"], e["paths"]))
    table = stance_plugin.read_table(data)
    for r in stance_plugin.parse_table(table) if table else []:
        if r["role"].lower() == "furniture" and r["perspective"].lower() == "3rd" and \
                {t.lower() for t in r["target"]} & {k.lower() for k in a.keyword}:
            rows.append(("table", r["actor"], r["target"], r["graph"], r["paths"]))
    arcs = S.SfArchives(data)
    chains, tags_by_folder, graphs = [], {}, {}
    print(f"{len(rows)} third-person entries for {', '.join(a.keyword)}:")
    for src, actor, target, graph, paths in rows:
        chain = [S.folder_candidates(p)[0].rstrip("\\") for p in paths]
        chains.append(chain)
        for f in chain:
            if f not in tags_by_folder:
                tags_by_folder[f] = folder_tags(arcs.names, arcs.read, f)
        print(f"  {src} | actor {','.join(actor) or '-'} | target {','.join(target)} | {graph} | "
              + ", ".join(f"{p} ({len(tags_by_folder[c])})" for p, c in zip(paths, chain)))
        if graph:
            graph_tags(arcs.names, arcs.read, graph, graphs)
    for g in a.graph:
        graph_tags(arcs.names, arcs.read, g, graphs)
    ours = set()
    if a.ours and os.path.isdir(a.ours):
        for fn in os.listdir(a.ours):
            if fn.lower().endswith(".afx"):
                with open(os.path.join(a.ours, fn), encoding="utf-8", errors="replace") as fh:
                    t = tag_of(fh.read())
                if t:
                    ours.add(t.lower())
    print(f"our folder: {len(ours)} tags")
    for g, (tags, alters) in graphs.items():
        if tags is None or isinstance(tags, str):
            print(f"== graph {g}: {tags or 'not found'}")
            continue
        print(f"== graph {g}: {len(tags)} tags" + (f"; tag alterations {alters}" if alters else ""))
        if events_of.get(g):
            print(f"   events: {', '.join(events_of[g])}")
        for t in tags:
            r = resolve(t, chains, tags_by_folder, ours)
            print(f"  {t:32s} " + (r if isinstance(r, str) else ("; ".join(r) if r else "no folder answers it")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
