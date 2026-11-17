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

import numpy as np

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


NODE_TYPES = ("NiNode", "BSFadeNode", "BSLeafAnimNode", "BSMultiBoundNode", "NiBillboardNode", "BSWeakReferenceNode")


def nif_summary(data: bytes) -> list:
    """A model at a glance: block type counts, node names (NiNode family: the bones of a skeleton.nif), extra data
    (type and name) and strings that look like paths. Readable for Skyrim (BS 100) and Starfield (BS 172+) files."""
    from fo4sf import nif as nifmod
    n = nifmod.parse(data)
    types = Counter(n.type_of(i) for i in range(len(n.blocks)))

    def name(i):
        idx = struct.unpack_from("<i", n.blocks[i], 0)[0] if len(n.blocks[i]) >= 4 else -1
        return n.strings[idx].decode("latin-1", "replace") if 0 <= idx < len(n.strings) else ""
    nodes = [name(i) for i in range(len(n.blocks)) if n.type_of(i) in NODE_TYPES]
    extras = [f"{n.type_of(i)} {name(i)!r}" for i in range(len(n.blocks))
              if "ExtraData" in n.type_of(i) or n.type_of(i) in ("SkinAttach", "BSXFlags")]
    paths = [x.decode("latin-1", "replace") for x in n.strings if PATH_RX.search(x.decode("latin-1", "replace"))]
    tree = node_tree(n, name) if len(nodes) <= 64 else []
    return [f"BS {n.bs_version}, {len(n.blocks)} blocks: " + ", ".join(f"{t} {c}" for t, c in sorted(types.items())),
            f"nodes ({len(nodes)}): {', '.join(nodes)}",
            f"extra data: {', '.join(extras) or '-'}",
            f"path strings: {', '.join(paths) or '-'}", *tree]


def node_tree(n, name) -> list:
    """For a small skeleton.nif: each node with its parent, local translation, extra data names and the collision
    it carries (bhkNPCollisionObject -> bhkPhysicsSystem: size and the readable strings inside the Havok blob, i.e.
    which bones a ragdoll or controller names). NiAVObject layout as nif.node_children (FO4 / Starfield)."""
    from fo4sf import nif as nifmod
    import sf_anim_survey as SAS
    parent = {}
    for i in range(len(n.blocks)):
        if n.type_of(i) in NODE_TYPES:
            for c in nifmod.node_children(n, i):
                parent[c] = i
    out = []
    for i in range(len(n.blocks)):
        if n.type_of(i) not in NODE_TYPES:
            continue
        b = n.blocks[i]
        ne = struct.unpack_from("<I", b, 4)[0]
        extras = struct.unpack_from(f"<{ne}i", b, 8)
        t = struct.unpack_from("<3f", b, 8 + 4 * ne + 8)
        coll = struct.unpack_from("<i", b, 8 + 4 * ne + 8 + 52)[0]
        from fo4sf.retarget import mat_to_quat
        rq = mat_to_quat(struct.unpack_from("<9f", b, 8 + 4 * ne + 8 + 12))
        rot = "" if abs(abs(rq[3]) - 1) < 1e-4 else f" q ({rq[0]:+.3f}, {rq[1]:+.3f}, {rq[2]:+.3f}, {rq[3]:+.3f})"
        line = (f"node {name(i)!r} <{name(parent[i]) if i in parent else '-'}> t ({t[0]:.3f}, {t[1]:.3f}, {t[2]:.3f})"
                + rot
                + (f" extra [{', '.join(f'{n.type_of(e)} {name(e)!r}' for e in extras if 0 <= e < len(n.blocks))}]"
                   if ne else ""))
        if 0 <= coll < len(n.blocks):
            line += f" collision {n.type_of(coll)}"
            cb = n.blocks[coll]
            if n.type_of(coll) == "bhkNPCollisionObject" and len(cb) >= 10:
                sysref = struct.unpack_from("<i", cb, 6)[0]
                if 0 <= sysref < len(n.blocks):
                    blob = n.blocks[sysref][4:]
                    strs = [x for x in SAS.strings_of(blob, 3) if not x.startswith("hk") or len(x) > 3]
                    line += f" -> {n.type_of(sysref)} {len(blob)} bytes, strings: {', '.join(strs[:80])}"
        out.append(line)
    return out


def skin_summary(data: bytes) -> list:
    """The skinned shapes of a Skyrim model (skyrimskin): name, vertices, triangles, bones, weight checks."""
    from fo4sf import nif as nifmod, skyrimskin
    out = []
    for sh in skyrimskin.skinned_shapes(nifmod.parse(data)):
        c = skyrimskin.check(sh)
        out.append(f"skinned {sh.name.decode('latin-1', 'replace')!r}: {c['vertices']} verts, {c['triangles']} tris, "
                   f"{c['bones']} bones, unweighted {c['unweighted_vertices']}, max influences {c['max_influences']}, "
                   f"bad tris {c['out_of_range_triangles']}, weights from {c['weight_source']}; bones: "
                   + ", ".join(b.decode("latin-1", "replace") for b in sh.bones))
    return out or ["no skinned shapes"]


def skin_chain(subs, armo: dict, arma: dict) -> list:
    """The models a record draws through its skin: every 4-byte subrecord naming an ARMO, then that ARMO's 4-byte
    subrecords naming ARMAs, and each ARMA's path subrecords. [(sig, armo edid, [(arma edid, [(sig, path)])])].
    armo / arma: {FormID: subrecords}."""
    from fo4sf import sfplugin
    out = []
    for sig, d in subs:
        if len(d) != 4:
            continue
        a = struct.unpack("<I", bytes(d))[0]
        if a not in armo:
            continue
        addons = []
        for s2, d2 in armo[a]:
            if len(d2) == 4 and struct.unpack("<I", bytes(d2))[0] in arma:
                aa = arma[struct.unpack("<I", bytes(d2))[0]]
                addons.append((sfplugin.edid(aa), path_subs(aa)))
        out.append((sig.decode("latin-1"), sfplugin.edid(armo[a]), addons))
    return out


def skin_lines(label: str, chain) -> list:
    return [f"  {label} {sig} -> ARMO {ae}: " + "; ".join(f"ARMA {ne} [{', '.join(f'{s} {t}' for s, t in ps)}]"
                                                         for ne, ps in addons)
            for sig, ae, addons in chain]


def model_detail(data: bytes, read_mesh) -> list:
    """A Starfield model in full, for comparing ours with a vanilla one: nif_summary, then per BSGeometry its flags,
    transform, bounds, skin / shader refs, the material, each LOD's mesh path (found or not, through read_mesh(path)
    -> bytes or None) with the .mesh's vertex / triangle counts, weights per vertex, scale and the bone indices it
    uses; then the skin (SkinAttach names, BSSkin::Instance root / data / bone count, bind translations)."""
    from fo4sf import nif as nifmod, sfmesh, sfnif
    n = nifmod.parse(data)
    out = nif_summary(data)

    def name(i):
        idx = struct.unpack_from("<i", n.blocks[i], 0)[0] if len(n.blocks[i]) >= 4 else -1
        return n.strings[idx].decode("latin-1", "replace") if 0 <= idx < len(n.strings) else ""
    if not any(ln.startswith("node ") for ln in out):
        out += node_tree(n, name)
    for i in range(len(n.blocks)):
        t = n.type_of(i)
        if t == "BSXFlags":
            out.append(f"BSXFlags value 0x{struct.unpack_from('<I', n.blocks[i], 4)[0]:X}")
        elif t == "NiStringExtraData" and name(i) != "sgoKeep":
            v = struct.unpack_from("<i", n.blocks[i], 4)[0]
            out.append(f"NiStringExtraData {name(i)!r} = "
                       f"{n.strings[v].decode('latin-1', 'replace') if 0 <= v < len(n.strings) else '-'}")
        elif t == "BSSkin::Instance":
            root, dref, cnt = struct.unpack_from("<iiI", n.blocks[i], 0)
            refs = struct.unpack_from(f"<{cnt}i", n.blocks[i], 12)
            out.append(f"skin instance bone refs -> {', '.join(name(r) if 0 <= r < len(n.blocks) else str(r) for r in refs)}")
    for i in range(len(n.blocks)):
        if n.type_of(i) != "BSGeometry":
            continue
        g = sfnif.parse_bsgeometry(n.blocks[i])
        nm = n.strings[g.name_idx].decode("latin-1", "replace") if 0 <= g.name_idx < len(n.strings) else ""
        mat = ""
        if 0 <= g.shader < len(n.blocks):
            si = struct.unpack_from("<i", n.blocks[g.shader], 0)[0]
            mat = n.strings[si].decode("latin-1", "replace") if 0 <= si < len(n.strings) else ""
        out.append(f"BSGeometry {nm!r}: flags 0x{g.flags:X}, t {tuple(round(v, 3) for v in g.translation)}, "
                   f"scale {g.scale}, sphere {tuple(round(v, 3) for v in g.sphere)}, box "
                   f"{tuple(round(v, 3) if abs(v) < 1e30 else 'FLT_MAX' for v in g.box)}, skin -> "
                   f"{n.type_of(g.skin) if 0 <= g.skin < len(n.blocks) else '-'}, extra "
                   f"[{', '.join(n.type_of(e) for e in g.extra_refs if 0 <= e < len(n.blocks))}], material {mat!r}")
        for lod, ref in enumerate(g.meshes):
            if ref is None:
                continue
            path = ref.path.decode("latin-1", "replace")
            md = read_mesh(path)
            line = f"  LOD{lod} {path}: indices {ref.indices_size}, verts {ref.num_verts}, flags 0x{ref.flags:X}, "
            if md is None:
                out.append(line + "MESH NOT FOUND")
                continue
            try:
                m = sfmesh.parse(md)
                bones = sorted({b for b, w in m.weights if w}) if m.weights else []
                out.append(line + f"file v{m.version}: {len(m.positions)} verts, {len(m.triangles)} tris, scale "
                                  f"{m.scale:.4f}, weights/vertex {m.weights_per_vertex}, bone indices used {bones}, "
                                  f"uv {len(m.uv1)}, normals {len(m.normals)}, tangents {len(m.tangents)}, "
                                  f"meshlets {len(m.meshlets)}, lods {len(m.lods)}, tail {len(m.tail)} bytes")
            except Exception as e:                       # noqa: BLE001
                out.append(line + f"mesh unreadable: {type(e).__name__}: {e}")
    sk = sfnif.parse_skin(n)
    if sk:
        out.append(f"skin bones ({len(sk.get('bones', []))}): "
                   + ", ".join(b.decode("latin-1", "replace") for b in sk.get("bones", [])))
        out.append(f"skin instance (skeleton root, data, bones): {sk.get('instance')}")
        out.append("bind translations: " + ", ".join(f"{tuple(round(v, 3) for v in b[2])}" for b in sk.get("binds", [])))
    return out


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
        folder = bsa.norm("meshes\\" + posixpath.dirname(proj.replace("\\", "/")).replace("/", "\\")) + "\\"
        for nf in sorted(x for x in names if x.startswith(folder) and x.endswith(".nif")):
            try:
                lines.append(f"  model {nf}:")
                lines += ["    " + ln for ln in nif_summary(arcs._read(nf))]
                lines += ["    " + ln for ln in skin_summary(arcs._read(nf))]
            except Exception as e:                       # noqa: BLE001  (a probe: report and go on)
                lines.append(f"    unreadable: {type(e).__name__}: {e}")
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
    armo = {f: subs for _t, _h, subs, f in sfplugin.records(esm, [b"ARMO"])}
    arma = {f: subs for _t, _h, subs, f in sfplugin.records(esm, [b"ARMA"])}
    npcs = list(sfplugin.records(esm, [b"NPC_"]))
    for want in sf_races:
        r = next((x for x in races if (x["edid"] or "").lower() == want.lower()), None)
        if r is None:
            lines.append(f"== Starfield {want}: no such RACE")
            continue
        lines.append(f"== Starfield {r['edid']} {r['form']}")
        race_subs = next(subs for _t, _h, subs, f in sfplugin.records(esm, [b"RACE"]) if f == int(r["form"], 16))
        lines += skin_lines("race skin", skin_chain(race_subs, armo, arma))
        rf = struct.pack("<I", int(r["form"], 16))
        for _t, _h, subs, f in npcs:
            if any(sg == b"RNAM" and bytes(d)[:4] == rf for sg, d in subs):
                lines.append(f"  NPC_ {sfplugin.edid(subs)} {f:08X}")
                lines += skin_lines("  skin", skin_chain(subs, armo, arma))
        for s, t in dict.fromkeys(r["paths"]):
            if s == "ANAM":
                p, d = read(t)
                if d is None:
                    lines.append(f"  skeleton {p}: not found")
                    continue
                try:
                    lines += [f"  skeleton {p}:"] + ["    " + ln for ln in nif_summary(d)]
                except Exception as e:                   # noqa: BLE001
                    lines.append(f"  skeleton {p}: unreadable: {type(e).__name__}: {e}")
            if s == "NAM5":
                p, d = read(t)
                names = rig_names(d) if d is not None else []
                lines.append(f"  rig {p}: " + ("not found" if d is None else
                                               f"{len(d)} bytes; bone names at the end ({len(names)}): {', '.join(names)}"))
        lines += contract_lines(r, lambda k: read(k)[1], keys)
    return lines


def models_side(sf_data, models) -> list:
    """model_detail for each model: a file on disk (meshes from <its meshes root>\\..\\geometries, else the archives)
    or an archive path."""
    import sf_anim_survey as SAS
    index = {}
    if sf_data:
        for _label, ar in SAS.archives(sf_data):
            for i, n in enumerate(ar.names):
                index.setdefault(SAS.norm(n), (ar, i))

    def from_archive(k):
        k = SAS.norm(k)
        for cand in (k, "meshes/" + k, "geometries/" + k + ".mesh", "geometries/" + k):
            if cand in index:
                ar, i = index[cand]
                return ar.read(i)
        return None
    lines = []
    for m in models:
        if os.path.isfile(m):
            low = os.path.abspath(m).replace("\\", "/")
            cut = low.lower().rfind("/meshes/")
            root = low[:cut] if cut >= 0 else os.path.dirname(low)

            def read_mesh(path, root=root):
                f = os.path.join(root, "geometries", *path.replace("\\", "/").split("/")) + ".mesh"
                if os.path.isfile(f):
                    with open(f, "rb") as fh:
                        return fh.read()
                return from_archive(path)
            with open(m, "rb") as fh:
                data = fh.read()
            lines.append(f"== model on disk {m}")
        else:
            data, read_mesh = from_archive(m), from_archive
            lines.append(f"== model in the archives {m}")
            if data is None:
                lines.append("  not found")
                continue
        try:
            lines += ["  " + ln for ln in model_detail(data, read_mesh)]
        except Exception as e:                           # noqa: BLE001
            lines.append(f"  unreadable: {type(e).__name__}: {e}")
    return lines


def skyrim_motion(sky_data: str, folder: str = "meshes\\actors\\ambient\\chicken\\",
                  project: str = "ChickenProject") -> list:
    """Where each of a Skyrim creature's clips moves its root (animationdatasinglefile, the project's motion blocks
    mapped to clip files through its behaviours' clip generators), and the generators that play a clip mirrored."""
    from fo4sf import animdata, bsa, skyrimbehavior
    from fo4sf.retarget import SKYRIM_M_PER_UNIT
    arcs = bsa.SkyrimArchives(sky_data, loose=False)
    text = arcs._read("meshes\\animationdatasinglefile.txt")
    if text is None:
        return ["  animationdatasinglefile.txt not in the archives"]
    projects = animdata.parse(text.decode("latin-1"))
    proj = next((p for k, p in projects.items() if k.lower() == project.lower()), None)
    if proj is None:
        return [f"  project {project} not found"]
    behaviors = []
    for n in sorted({bsa.norm(x) for ar in arcs.archives for x in ar.names}):
        if n.startswith(folder) and "\\behaviors\\" in n and n.endswith(".hkx"):
            try:
                behaviors.append(skyrimbehavior.read(arcs._read(n)))
            except Exception:                            # noqa: BLE001
                pass
    gens = animdata.clip_generators(behaviors)
    rep = {}
    motion = animdata.clip_motion(proj, gens, rep)
    lines = [f"== Skyrim {project} root motion: {len(motion)} clips with motion; {len(proj.get('clips', []))} clip "
             f"generators, {rep.get('mirrored_skipped', 0)} mirrored, mapped by behaviour {rep.get('by_behavior', 0)}"]
    mirrored = sorted({c["name"] for c in proj.get("clips", []) if "[mirror" in c["name"].lower()})
    if mirrored:
        lines.append("  mirrored generators: " + ", ".join(mirrored))
    for stem, blk in sorted(motion.items()):
        tr, rot = blk.get("translations") or [], blk.get("rotations") or []
        t = tr[-1][1:4] if tr else (0.0, 0.0, 0.0)
        yaw = 0.0
        if rot:
            import math
            yaw = math.degrees(2 * math.atan2(rot[-1][3], rot[-1][4]))
        lines.append(f"  {stem}: {blk.get('duration', 0):.3f} s, ends x {t[0] * SKYRIM_M_PER_UNIT:+.3f} "
                     f"y {t[1] * SKYRIM_M_PER_UNIT:+.3f} z {t[2] * SKYRIM_M_PER_UNIT:+.3f} m, turn {yaw:+.1f} deg, "
                     f"{len(tr)} / {len(rot)} keys")
    return lines


def clip_headers(names, read, folder: str) -> list:
    """Each .af under folder: the root motion its header carries (rootmotion.read_header: end translation, yaw)."""
    from fo4sf import rootmotion
    base = folder.replace("\\", "/").lower().strip("/")
    base = base if base.startswith("meshes/") else "meshes/" + base
    out = []
    for n in sorted(x for x in names if x.startswith(base + "/") and x.endswith(".af")):
        d = read(n)
        if d is None or len(d) < 36:
            continue
        q, t = rootmotion.read_header(d)
        out.append(f"  {n[len(base) + 1:]}: header t ({t[0]:+.3f}, {t[1]:+.3f}, {t[2]:+.3f}) m, "
                   f"yaw {rootmotion.yaw_degrees(q):+.1f} deg, {len(d)} bytes")
    return out


def clip_tracks(calumi: str, read, rig_key: str, clips, work: str) -> list:
    """Through CALUMI: each clip's tracks and its first bone's (COM's) translation at the first and last key, i.e.
    whether a creature's clip moves COM across the ground (root motion in COM) or keeps it in place."""
    from fo4sf import af_writer
    os.makedirs(work, exist_ok=True)
    rig = os.path.join(work, "skeleton.rig")
    with open(rig, "wb") as fh:
        fh.write(read(rig_key))
    out = []
    for key in clips:
        d = read(key)
        if d is None:
            out.append(f"  {key}: not found")
            continue
        af = os.path.join(work, posixpath.basename(key))
        with open(af, "wb") as fh:
            fh.write(d)
        try:
            rb = af_writer.read_back(calumi, af, rig)
        except Exception as e:                           # noqa: BLE001
            out.append(f"  {key}: unreadable: {type(e).__name__}: {e}")
            continue
        com = rb["translations"].get("COM") or []
        line = f"  {posixpath.basename(key)}: {rb['frames']} frames, tracks {len(rb['bones'])}"
        if "Root" in rb["bones"]:
            line += " (has Root)"
        if com:
            a, b = np.array(com[0][1]), np.array(com[-1][1])
            line += (f"; COM first ({a[0]:+.3f}, {a[1]:+.3f}, {a[2]:+.3f}) last ({b[0]:+.3f}, {b[1]:+.3f}, "
                     f"{b[2]:+.3f}) m, {len(com)} keys")
            rq = rb["rotations"].get("COM") or []
            if rq:
                from fo4sf import rootmotion
                line += f", yaw first {rootmotion.yaw_degrees(rq[0][1]):+.1f} last {rootmotion.yaw_degrees(rq[-1][1]):+.1f}"
        else:
            line += "; no COM track"
        out.append(line)
    return out


def rig_dump(data: bytes) -> list:
    """A Starfield .rig laid open, to compare a vanilla rig with ours field by field: the bone names from the table at
    the end (rig_names), the record area taken as N x 96 bytes before it (docs/spikes/WP-doors-research.md: 96-byte
    records: rotation, translation, parent index, name offset), whatever precedes it as the header; each record as 24
    32-bit words (hex), with the words that read as plausible floats also shown as floats."""
    data = bytes(data)
    names = rig_names(data)
    n = len(names)
    table = sum(len(x) + 1 for x in names)
    start = len(data) - table - 96 * n
    out = [f"{len(data)} bytes, {n} bone names, name table {table} bytes, record area from {start}"
           + ("" if start >= 0 else " (does not fit: layout differs)")]
    if start < 0:
        return out
    out.append("header: " + data[:start].hex(" ", 4))
    for i in range(n):
        rec = data[start + 96 * i: start + 96 * (i + 1)]
        words = struct.unpack("<24I", rec)
        fl = struct.unpack("<24f", rec)
        shown = " ".join(f"{w:08x}" for w in words)
        floats = " ".join(f"{f:+.3f}" if w and 1e-6 < abs(f) < 1e4 else "." for w, f in zip(words, fl))
        out.append(f"  [{i:2d}] {names[i] if i < n else '?'}")
        out.append(f"       {shown}")
        out.append(f"       {floats}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim-data")
    ap.add_argument("--starfield-data")
    ap.add_argument("--race", default="ChickenRace", help="the Skyrim race (EditorID)")
    ap.add_argument("--sf-race", action="append", default=[], help="a Starfield race to open (EditorID; repeatable)")
    ap.add_argument("--model", action="append", default=[],
                    help="a Starfield model to print in full: an archive path (meshes\\...) or a .nif on disk whose "
                         "meshes are in the geometries folder beside its meshes folder (repeatable)")
    ap.add_argument("--motion", action="store_true",
                    help="root motion: Skyrim's chicken clips (motion data) and the vanilla critter clips' headers")
    ap.add_argument("--calumi", default="", help="with --motion: CALUMI.Animation.dll, to read the critter clips' tracks")
    ap.add_argument("--rig", action="append", default=[],
                    help="a .rig to lay open: an archive path (meshes\\...\\skeleton.rig) or a file on disk (repeatable)")
    a = ap.parse_args(argv)
    if a.rig:
        import sf_anim_survey as SAS
        index = {}
        if a.starfield_data:
            for _label, ar in SAS.archives(a.starfield_data):
                for i, nm in enumerate(ar.names):
                    index.setdefault(SAS.norm(nm), (ar, i))
        for r in a.rig:
            if os.path.isfile(r):
                with open(r, "rb") as fh:
                    d = fh.read()
            else:
                hit = index.get(SAS.norm(r))
                d = hit[0].read(hit[1]) if hit else None
            print(f"== rig {r}")
            print("\n".join(["  not found"] if d is None else rig_dump(d)))
        return 0
    if a.model:
        print("\n".join(models_side(a.starfield_data, a.model)))
        return 0
    if a.motion:
        if a.skyrim_data:
            print("\n".join(skyrim_motion(a.skyrim_data)))
        if a.starfield_data:
            import sf_anim_survey as SAS
            index = {}
            for _label, ar in SAS.archives(a.starfield_data):
                for i, n in enumerate(ar.names):
                    index.setdefault(SAS.norm(n), (ar, i))

            def read(k):
                hit = index.get(SAS.norm(k))
                return hit[0].read(hit[1]) if hit else None
            print("== Starfield critter clip headers (root motion)")
            print("\n".join(clip_headers(list(index), read, "actors/critter/animations")))
            if a.calumi:
                import tempfile
                clips = [f"meshes/actors/critter/animations/{c}.af" for c in
                         ("idle", "walkforward", "jogforward", "runforward", "turninplace_left90", "rundeparture_left180")]
                print("== Starfield critter clip tracks (CALUMI)")
                print("\n".join(clip_tracks(a.calumi, read, "meshes/actors/critter/characterassets/skeleton.rig",
                                             clips, tempfile.mkdtemp(prefix="critter_clips_"))))
        return 0
    if a.skyrim_data:
        print("\n".join(skyrim_side(a.skyrim_data, a.race)))
    if a.starfield_data:
        print("\n".join(starfield_side(a.starfield_data, a.sf_race)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
