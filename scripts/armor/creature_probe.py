"""What a creature is made of in Skyrim and in Starfield, side by side (read-only). Step 1 of the first creature
conversion (docs/research/tes4skyrim.md "Suggested next steps": a Riverwood chicken).

2026-11-17, owner: "yes" to testing whether Starfield takes a new creature skeleton. tes4skyrim's creature path keeps
each creature's own skeleton (no retarget); ours would too, so the questions are what a Starfield creature race names
(skeleton, rig, root graph, animation folders) and what Skyrim's chicken brings (skeleton bones, clips, graphs).

Skyrim (Skyrim.esm + its BSAs), for --race (default ChickenRace): the race's path subrecords in order (skeleton,
behaviour project ...), how many NPC_ records use it, its movement / attack counts; the behaviour project, the
character file it names, that file's rig, behaviour and animation list; the rig's bones (count, names, parents).
Starfield (Starfield.esm + archives): every RACE with its path subrecords (skeleton .nif, rig .rig, root graph .agx,
animation folder) and how many NPC_ records use it; for --sf-race (repeatable, an EditorID), its rig's size and
strings and its root graph's referenced graphs and first lines. Which subrecord is which field is not assumed: every
subrecord that reads as a path is printed with its signature.

    python -I scripts\\armor\\creature_probe.py --skyrim-data "$sky" --starfield-data "$sf\\Data" > creature_probe.txt
    python -I scripts\\armor\\creature_probe.py --skyrim-data "$sky" --starfield-data "$sf\\Data" --sf-race <EDID>
"""
import argparse
import os
import posixpath
import re
import struct
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

PATH_RX = re.compile(r"[\\/]|\.(nif|hkx|agx|rig|af|afx|txt|xml)$", re.I)


def as_text(d: bytes):
    """The subrecord as a 0-terminated printable string, else None."""
    t = bytes(d).rstrip(b"\0")
    if not t or b"\0" in t or not all(32 <= c < 127 for c in t):
        return None
    return t.decode("latin-1")


def path_subs(subs) -> list:
    """[(signature, text)] of the subrecords that read as a file or folder path, in record order."""
    out = []
    for s, d in subs:
        t = as_text(d)
        if t and PATH_RX.search(t):
            out.append((s.decode("latin-1"), t))
    return out


def race_row(subs, fid: int) -> dict:
    """{form, edid, paths, counts} of a RACE: path subrecords plus how many times each signature occurs."""
    from fo4sf import sfplugin
    return {"form": f"{fid:08X}", "edid": sfplugin.edid(subs), "paths": path_subs(subs),
            "counts": dict(Counter(s.decode("latin-1") for s, _d in subs))}


def npc_race_counts(records) -> Counter:
    """{race FormID: NPC_ count} from (type, header, subs, fid) NPC_ records (RNAM, 4 bytes, both games)."""
    c = Counter()
    for _t, _h, subs, _f in records:
        r = next((bytes(d) for s, d in subs if s == b"RNAM" and len(d) >= 4), None)
        if r is not None:
            c[struct.unpack_from("<I", r)[0]] += 1
    return c


def resolve(base_file: str, rel: str) -> str:
    """An archive path (lower case, backslashes) for rel as written inside base_file (relative to base_file's
    folder, as Skyrim's project / character files are)."""
    d = posixpath.dirname(base_file.replace("\\", "/").lower())
    return posixpath.normpath(posixpath.join(d, rel.replace("\\", "/").lower())).replace("/", "\\")


def character_refs(strings) -> dict:
    """{rig, behaviors, animations} from a Skyrim character file's strings (by shape: skeleton*.hkx is the rig,
    Behaviors\\*.hkx a behaviour, everything else ending .hkx a clip)."""
    out = {"rig": [], "behaviors": [], "animations": []}
    for s in strings:
        low = s.lower().replace("/", "\\")
        if not low.endswith(".hkx"):
            continue
        if "skeleton" in posixpath.basename(low.replace("\\", "/")):
            out["rig"].append(s)
        elif low.startswith("behaviors\\") or "\\behaviors\\" in low:
            out["behaviors"].append(s)
        else:
            out["animations"].append(s)
    return {k: list(dict.fromkeys(v)) for k, v in out.items()}     # the character file names its rig twice


def hkx_strings(data: bytes) -> list:
    """Every string a Havok packfile's objects point at (behavior_inventory.object_strings), flattened."""
    from fo4sf import hkpackfile
    import behavior_inventory as BI
    pf = hkpackfile.Packfile(data)
    return [s for _o, _c, strs in BI.object_strings(pf) for s in strs]


GRAPHS = "meshes/animtextdata/tables/graphs/"


def graph_path(ref: str) -> str:
    """An archive key (lower case, forward slashes, under meshes/) for a graph named in a RACE (a path) or in a
    NT_GRAPH_REF (a bare name, e.g. MeleeActions)."""
    k = ref.replace("\\", "/").lower().strip()
    if not k.endswith(".agx"):
        return GRAPHS + posixpath.basename(k) + ".agx"
    k = k[len("data/"):] if k.startswith("data/") else k
    return k if k.startswith("meshes/") else "meshes/" + k


def deep_tags_refs(data: bytes):
    """(clip tags, graph refs) of every node at any depth: agx.read_graph sees the top level only, but
    NT_STATE_MACHINE_EMBEDDED / NT_BLEND_TREE_EMBEDDED nodes hold nested <graph><node>s (the critter's locomotion
    tags were missing from the 2026-11-17 run because of this)."""
    import xml.etree.ElementTree as ET
    from fo4sf import agx
    tags, refs = [], []
    for n in ET.fromstring(data.decode("utf-8-sig", "replace")).iter("node"):
        p = agx._props(n)
        ty = n.findtext("node_type")
        if ty == "NT_ANIMATION_NODE" and p.get("TagName"):
            tags.append(p["TagName"])
        if ty == "NT_GRAPH_REF" and p.get("Graph Ref"):
            refs.append(p["Graph Ref"])
    return tags, list(dict.fromkeys(refs))


NAME_RX = re.compile(r"^[A-Za-z_][\w \[\]\.\-]{2,}$")


def rig_names(data: bytes) -> list:
    """Bone names of a Starfield .rig: the name table at its end (docs/spikes/WP-doors-research.md: 96-byte bone
    records, then the names), read as the trailing run of 0-terminated identifier-like strings."""
    parts = bytes(data).split(b"\0")
    out = []
    for raw in reversed(parts):
        if not raw:
            continue
        t = raw.decode("latin-1")
        if not NAME_RX.match(t):
            break
        out.append(t)
    return out[::-1]


def walk_graphs(roots, read, limit: int = 60) -> list:
    """[(key, summary or None)] for the graphs reachable from roots through NT_GRAPH_REF, breadth first, each once.
    read(key) -> bytes or None."""
    from fo4sf import agx
    seen, out, queue = set(), [], [graph_path(r) for r in roots]
    while queue and len(out) < limit:
        k = queue.pop(0)
        if k in seen:
            continue
        seen.add(k)
        d = read(k)
        if d is None:
            out.append((k, None))
            continue
        sm = agx.summary(agx.read_graph(d))
        sm["tags"], sm["graph_refs"] = deep_tags_refs(d)     # nested state machines / blend trees included
        out.append((k, sm))
        queue += [graph_path(r) for r in sm["graph_refs"]]
    return out


def folder_descriptors(folders, names, read) -> list:
    """[(folder, [{"file", "tag", "prefix", "is_state", "filename"}], af count)] for each animation folder (a RACE's
    DNAM / SAPT: every .afx beneath it, at any depth). names: archive keys (lower case, forward slashes)."""
    import xml.etree.ElementTree as ET
    out = []
    for f in dict.fromkeys(folders):
        base = f.replace("\\", "/").lower().strip("/")
        base = base if base.startswith("meshes/") else "meshes/" + base
        under = [n for n in names if n.startswith(base + "/")]
        rows = []
        for n in sorted(x for x in under if x.endswith(".afx")):
            d = read(n)
            row = {"file": n[len(base) + 1:], "tag": None, "prefix": None, "is_state": None, "filename": None}
            if d is not None:
                try:
                    r = ET.fromstring(d.decode("utf-8-sig", "replace"))
                    row.update({k: r.findtext(k) for k in ("tag", "prefix", "is_state", "filename")})
                except ET.ParseError:
                    row["tag"] = "(not XML)"
            rows.append(row)
        out.append((f, rows, sum(1 for n in under if n.endswith(".af"))))
    return out


def contract_lines(race: dict, read, names) -> list:
    """What a race's graphs play and what its folders supply: the list a new creature has to fill."""
    lines = []
    paths = list(dict.fromkeys(race["paths"]))
    graphs = [t for s, t in paths if s in ("NAM6", "SGNM")]
    folders = [t for s, t in paths if s in ("DNAM", "SAPT")]
    played = []
    for k, sm in walk_graphs(graphs, read):
        if sm is None:
            lines.append(f"  graph {k}: not found")
            continue
        played += sm["tags"]
        lines.append(f"  graph {k}: {sm['nodes']} nodes; refs {sm['graph_refs']}")
        lines.append(f"    tags ({len(sm['tags'])}): {', '.join(dict.fromkeys(sm['tags']))}")
        if sm["tag_alterations"]:
            lines.append("    tag variants: " + "; ".join(f"{a['mode']} by {a['variable']}: {a['cases']}"
                                                       for a in sm["tag_alterations"]))
        lines.append(f"    events: {', '.join(sm['events'])}")
        lines.append(f"    variables: {', '.join(sm['variables'])}")
    supplied = set()
    for f, rows, n_af in folder_descriptors(folders, names, read):
        lines.append(f"  folder {f}: {len(rows)} .afx, {n_af} .af")
        for r in rows:
            supplied.add((r["tag"] or "").lower())
            lines.append(f"    {r['file']}: tag {r['tag']}" + (f" prefix {r['prefix']}" if r["prefix"] else "")
                         + (" (state)" if r["is_state"] == "1" else "") + f" -> {r['filename']}")
    missing = [t for t in dict.fromkeys(played) if t.lower() not in supplied]
    lines.append(f"  tags the graphs name that the race's folders do not supply (other races' actions, or unused by "
                 f"this one; the folders are the race's real list) ({len(missing)}): "
                 + ", ".join(missing))
    return lines


def skyrim_side(sky_data: str, race_edid: str) -> list:
    from fo4sf import bsa, sfplugin, skyrimhkx
    esm = os.path.join(sky_data, "Skyrim.esm")
    races = {fid: (subs) for _t, _h, subs, fid in sfplugin.records(esm, [b"RACE"])}
    fid = next((f for f, s in races.items() if (sfplugin.edid(s) or "").lower() == race_edid.lower()), None)
    if fid is None:
        return [f"Skyrim: no RACE {race_edid}"]
    row = race_row(races[fid], fid)
    n_npc = npc_race_counts(sfplugin.records(esm, [b"NPC_"])).get(fid, 0)
    lines = [f"== Skyrim {row['edid']} {row['form']}: {n_npc} NPC_ records use it",
             "  path subrecords: " + "; ".join(f"{s} {t}" for s, t in row["paths"]),
             "  subrecord counts: " + ", ".join(f"{k} {v}" for k, v in sorted(row["counts"].items()))]
    arcs = bsa.SkyrimArchives(sky_data, loose=False)
    names = {bsa.norm(n) for ar in arcs.archives for n in ar.names}

    def read(p):
        p = bsa.norm(p if p.lower().startswith("meshes\\") else "meshes\\" + p)
        return (p, arcs._read(p)) if p in names else (p, None)
    for proj in dict.fromkeys(t for _s, t in row["paths"] if t.lower().endswith("project.hkx")):
        pp, pdata = read(proj)
        if pdata is None:
            lines.append(f"  project {pp}: not in the archives")
            continue
        chars = [s for s in hkx_strings(pdata) if s.lower().endswith(".hkx")]
        lines.append(f"  project {pp}: names {chars}")
        for ch in chars:
            cp, cdata = read(resolve(pp, ch))
            if cdata is None:
                lines.append(f"    character {cp}: not in the archives")
                continue
            refs = character_refs(hkx_strings(cdata))
            lines.append(f"    character {cp}: rig {refs['rig']}, behaviours {refs['behaviors']}, "
                         f"{len(refs['animations'])} clips")
            lines.append("      clips: " + ", ".join(posixpath.basename(a.replace("\\", "/"))
                                                    for a in refs["animations"]))
            for rig in refs["rig"]:
                rp, rdata = read(resolve(pp, rig))          # character-file paths are relative to the project
                if rdata is None:
                    lines.append(f"      rig {rp}: not in the archives")
                    continue
                d = skyrimhkx.describe(rdata)
                for sk in d["skeletons"]:
                    lines.append(f"      rig {rp}: skeleton {sk['name']!r}, {len(sk['bones'])} bones")
                    lines.append("        bones: " + ", ".join(f"{b}<{sk['bones'][p] if 0 <= p < len(sk['bones']) else '-'}"
                                                             for b, p in zip(sk["bones"], sk["parents"])))
            for bh in refs["behaviors"]:
                bp, bdata = read(resolve(pp, bh))
                lines.append(f"      behaviour {bp}: " + ("not in the archives" if bdata is None else f"{len(bdata)} bytes"))
    return lines


def starfield_side(sf_data: str, sf_races) -> list:
    from fo4sf import sfplugin
    import sf_anim_survey as SAS
    esm = os.path.join(sf_data, "Starfield.esm")
    races = [race_row(subs, fid) for _t, _h, subs, fid in sfplugin.records(esm, [b"RACE"])]
    used = npc_race_counts(sfplugin.records(esm, [b"NPC_"]))
    lines = [f"== Starfield: {len(races)} RACE records (path subrecords; NPC_ count)"]
    for r in sorted(races, key=lambda r: r["edid"] or ""):
        if r["paths"]:
            lines.append(f"  {r['edid']} {r['form']} ({used.get(int(r['form'], 16), 0)} NPC_): "
                         + "; ".join(f"{s} {t}" for s, t in r["paths"]))
    if not sf_races:
        return lines
    arcs = SAS.archives(sf_data)
    index = {}
    for label, ar in arcs:
        for i, n in enumerate(ar.names):
            index.setdefault(SAS.norm(n), (ar, i))

    def read(p):
        k = SAS.norm(p)
        for cand in (k, "meshes/" + k):
            if cand in index:
                ar, i = index[cand]
                return cand, ar.read(i)
        return k, None
    keys = list(index)
    for want in sf_races:
        r = next((x for x in races if (x["edid"] or "").lower() == want.lower()), None)
        if r is None:
            lines.append(f"== Starfield {want}: no such RACE")
            continue
        lines.append(f"== Starfield {r['edid']} {r['form']}")
        for s, t in dict.fromkeys(r["paths"]):
            if s == "NAM5":
                p, d = read(t)
                names = rig_names(d) if d is not None else []
                lines.append(f"  rig {p}: " + ("not found" if d is None else
                                               f"{len(d)} bytes; bone names at the end ({len(names)}): {', '.join(names)}"))
        lines += contract_lines(r, lambda k: read(k)[1], keys)
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim-data")
    ap.add_argument("--starfield-data")
    ap.add_argument("--race", default="ChickenRace", help="the Skyrim race (EditorID)")
    ap.add_argument("--sf-race", action="append", default=[], help="a Starfield race to open (EditorID; repeatable)")
    a = ap.parse_args(argv)
    if a.skyrim_data:
        print("\n".join(skyrim_side(a.skyrim_data, a.race)))
    if a.starfield_data:
        print("\n".join(starfield_side(a.starfield_data, a.sf_race)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
