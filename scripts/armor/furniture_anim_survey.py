"""Furniture / idle-marker animations, both games (read-only): what Starfield plays on each furniture template we use,
and what Skyrim plays on each furniture / idle marker we convert. Step 1 of putting Skyrim's own furniture animations
on our furniture (docs/npc/furniture.md "Animations").

The route (verified twice: stances 2026-10-23, docs/armor/animation-port.md; a converted Skyrim chair idle played on
the human rig 2026-10-19): Starfield picks a furniture's clip folders by keywords, from the Furniture rows of the
generated table meshes\\animtextdata\\generatedsubgraphdata\\humanrace.txt (555 rows) and HumanRace's esm entries. An
esm entry with one keyword more wins. So each of our furniture copies can carry its own keyword, and an entry with it
puts a folder of converted Skyrim clips, under the tags the template's graph already plays, before the vanilla ones.

What this reads and writes (game files are read, nothing is copied; the report holds names and tags only):
  Starfield, per furniture template make_furniture.TEMPLATES uses: its keywords (Starfield.esm), the humanrace.txt
    Furniture rows those keywords match (graph, folders, actor keywords), the clip descriptors (.afx: tag, is_state)
    in each folder, and the graph's animation tags and link events.
  Skyrim, per base in our furniture.json (--work): kind, and for idle markers their IDLE records (anim event, behaviour
    file); every vanilla character behaviour's clip generators whose clip or name looks like furniture work (sit,
    lean, sweep, tanning, anvil, forge, chop, cook, alchemy ...).

    python -I scripts\\armor\\furniture_anim_survey.py --starfield "<Starfield>" --skyrim-data "<Skyrim SE>\\Data"
        --work C:\\Modding\\work\\s2s\\riverwood_doors --out C:\\Modding\\work\\furniture_anims

Writes <out>\\furniture_anims.json and furniture_anims.md (upload those).
"""
import argparse
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts", "interior"))

ANIM_ROOT = "meshes\\actors\\human\\animations\\"
# Skyrim clip generator names / clip paths that are furniture or idle-marker work
SKY_FURN_RE = re.compile(r"chair|bench|stool|throne|sit|lean|sweep|broom|tanning|tan_|anvil|forge|smelt|grindstone|"
                         r"sharpen|wheel|chop|woodcut|axe_?chop|cook|stir|alchemy|enchant|bed|sleep|bedroll|"
                         r"counter|bar_|table|wall|farm|hoe|rake|pickaxe|mine|bucket|lute|drum|flute|bard|"
                         r"warmhands|armscrossed|examine|study|browse|furniture|idlemarker|idle_?marker", re.I)


def norm(p: str) -> str:
    return p.replace("/", "\\").lower().lstrip("\\")


def matching_rows(rows, keywords) -> list:
    """Furniture rows of the generated table whose target keywords are all among `keywords` (EditorIDs, any case),
    most specific (most target keywords) first."""
    have = {k.lower() for k in keywords}
    out = [r for r in rows if r["role"].lower() == "furniture" and r["target"]
           and all(t.lower() in have for t in r["target"])]
    return sorted(out, key=lambda r: (-len(r["target"]), -len(r["actor"])))


def folder_candidates(path: str) -> list:
    """Archive folder(s) a table / SAPT animation path may mean: as given under meshes\\ when it starts at actors\\,
    else under meshes\\actors\\human\\animations\\."""
    p = norm(path).rstrip("\\")
    if p.startswith("meshes\\"):
        return [p + "\\"]
    if p.startswith("actors\\"):
        return ["meshes\\" + p + "\\"]
    return [ANIM_ROOT + p + "\\", "meshes\\" + p + "\\"]


def files_in(names, folder: str, ext: str) -> list:
    """Archive names directly in `folder` (normalised, ending in \\) with extension `ext`."""
    return sorted(n for n in names if n.startswith(folder) and n.endswith(ext) and "\\" not in n[len(folder):])


def idle_info(subs) -> dict:
    """A Skyrim IDLE record: {edid, event (ENAM), file (DNAM)}."""
    z = lambda d: d.rstrip(b"\0").decode("utf-8", "replace")                     # noqa: E731
    out = {}
    for s, d in subs:
        if s == b"EDID":
            out["edid"] = z(d)
        elif s == b"ENAM":
            out["event"] = z(d)
        elif s == b"DNAM":
            out["file"] = z(d)
    return out


def furniture_clips(behavior: dict) -> list:
    """[(clip generator name, animation path)] of a read Skyrim behaviour whose name or path looks like furniture."""
    out = []
    for n in behavior["nodes"].values():
        if n["class"] != "hkbClipGenerator":
            continue
        name, anim = n.get("name") or "", n.get("animation") or ""
        if SKY_FURN_RE.search(name) or SKY_FURN_RE.search(anim):
            out.append((name, anim))
    return sorted(set(out))


class SfArchives:
    """Starfield's non-texture archives: names (normalised) and reads (last archive wins)."""

    def __init__(self, data_dir):
        from fo4sf import ba2
        self.arcs = []
        for fn in sorted(os.listdir(data_dir), key=str.lower):
            if fn.lower().endswith(".ba2") and "texture" not in fn.lower():
                try:
                    self.arcs.append(ba2.Ba2(os.path.join(data_dir, fn)))
                except Exception:                                   # noqa: BLE001 (other formats: skipped)
                    pass
        self.names = sorted({norm(n) for a in self.arcs for n in a.names})

    def read(self, name):
        for a in reversed(self.arcs):
            i = a.find(name)
            if i is not None:
                return a.read(i)
        return None


def starfield_side(sf_dir, kinds=None):
    import make_furniture as MF
    import stance_plugin
    from fo4sf import agx, packages
    data = os.path.join(sf_dir, "Data")
    table = stance_plugin.read_table(data)
    rows = stance_plugin.parse_table(table) if table else []
    arcs = SfArchives(data)
    ix = packages.Index(os.path.join(data, "Starfield.esm"), types={b"FURN", b"IDLM", b"KYWD"})
    out, graphs_done = {}, {}
    try:
        for kind, (form, edid) in sorted(MF.TEMPLATES.items()):
            if kinds and kind not in kinds:
                continue
            fid = int(form, 16)
            kws = [ix.edid(k) or f"{k:08X}" for s, d in ix.subs(fid) if s == b"KWDA"
                   for k in struct.unpack(f"<{len(d) // 4}I", d)]
            entry = {"template": edid, "form": form, "type": ix.kind(fid), "keywords": kws, "rows": [],
                     "folders": {}, "graphs": {}}
            for r in matching_rows(rows, kws)[:24]:
                entry["rows"].append({k: r[k] for k in ("perspective", "actor", "target", "graph", "paths")})
                for p in r["paths"]:
                    if p in entry["folders"]:
                        continue
                    for folder in folder_candidates(p):
                        afx = files_in(arcs.names, folder, ".afx")
                        if not afx:
                            continue
                        clips = []
                        for n in afx[:60]:
                            try:
                                dsc = agx.read_descriptor(arcs.read(n))
                                clips.append({"file": n[len(folder):], "tag": dsc["tag"], "is_state": dsc["is_state"]})
                            except Exception as e:                  # noqa: BLE001
                                clips.append({"file": n[len(folder):], "error": f"{type(e).__name__}: {e}"})
                        entry["folders"][p] = {"archive_folder": folder, "afx": len(afx),
                                               "af": len(files_in(arcs.names, folder, ".af")), "clips": clips}
                        break
                    else:
                        entry["folders"][p] = {"afx": 0, "note": "no .afx found under " + " or ".join(folder_candidates(p))}
                g = r["graph"]
                if g and g not in entry["graphs"]:
                    if g not in graphs_done:
                        hit = next((n for n in arcs.names if n.endswith("\\" + norm(g)) or n == norm(g)), None)
                        if hit is None:
                            graphs_done[g] = {"note": "graph file not found in the archives"}
                        else:
                            try:
                                s = agx.summary(agx.read_graph(arcs.read(hit)))
                                graphs_done[g] = {"path": hit, "tags": sorted(set(s["tags"])), "events": s["events"],
                                                  "graph_refs": s["graph_refs"], "variables": s["variables"]}
                            except Exception as e:                  # noqa: BLE001 (binary graphs)
                                graphs_done[g] = {"path": hit, "error": f"{type(e).__name__}: {e}"}
                    entry["graphs"][g] = graphs_done[g]
            out[kind] = entry
    finally:
        ix.close()
    return {"table_rows": len(rows), "furniture_rows": sum(1 for r in rows if r["role"].lower() == "furniture"),
            "templates": out}


def skyrim_side(sky_data, furniture_json=None):
    from fo4sf import bsa, packages
    from fo4sf import skyrimbehavior as SB
    import furniture_survey as survey
    out = {"bases": [], "behaviors": {}}
    if furniture_json and os.path.exists(furniture_json):
        with open(furniture_json, encoding="utf-8") as fh:
            furn = json.load(fh)
        ix = packages.Index(os.path.join(sky_data, "Skyrim.esm"))
        try:
            idle_by_edid = {}
            for f in ix.by_type.get(b"IDLE", []):
                e = ix.edid(f)
                if e:
                    idle_by_edid[e.lower()] = f
            for key, b in sorted(furn.get("bases", {}).items(), key=lambda kv: (kv[1].get("kind") or "", kv[0])):
                row = {"base": key, "edid": b.get("edid"), "kind": b.get("kind"),
                       "uses": sum(1 for r in furn.get("refs", []) if r.get("base") == key)}
                try:
                    rec = survey.base_record(ix, int(key.split(":")[0], 16), starfield=False)
                except Exception:                                   # noqa: BLE001
                    rec = {}
                row["type"] = rec.get("type")
                if rec.get("animations"):
                    row["idles"] = [idle_info(ix.subs(idle_by_edid[a.lower()])) if a.lower() in idle_by_edid
                                    else {"edid": a} for a in rec["animations"]]
                if rec.get("nif_markers"):
                    row["marker_anims"] = sorted({m.get("anim") for m in rec["nif_markers"] if isinstance(m, dict)})
                out["bases"].append(row)
        finally:
            ix.close()
    arcs = bsa.SkyrimArchives(sky_data, loose=False)
    names = sorted({bsa.norm(n) for a in arcs.archives for n in a.names})
    for n in names:
        if not re.match(r"meshes\\actors\\character\\behaviors\\[^\\]+\.hkx$", n):
            continue
        try:
            b = SB.read(arcs._read(n))
        except Exception as e:                                      # noqa: BLE001
            out["behaviors"][n] = {"error": f"{type(e).__name__}: {e}"}
            continue
        clips = furniture_clips(b)
        if clips:
            out["behaviors"][n] = {"name": b["name"], "clips": [{"name": c, "animation": a} for c, a in clips],
                                   "events": [e for e in b["events"] if SKY_FURN_RE.search(e)]}
    return out


def markdown(rep) -> str:
    L = ["# Furniture animations, Starfield and Skyrim", ""]
    sf = rep.get("starfield")
    if sf:
        L += [f"Starfield table: {sf['table_rows']} rows, {sf['furniture_rows']} Furniture", ""]
        for kind, e in sf["templates"].items():
            L.append(f"## {kind}: {e['template']} {e['form']} ({e['type']})")
            L.append("keywords: " + ", ".join(e["keywords"]))
            for r in e["rows"][:6]:
                L.append(f"- row {r['perspective']} actor {r['actor']} target {r['target']} -> {r['graph']}: "
                         + " > ".join(r["paths"]))
            for p, f in e["folders"].items():
                tags = sorted({c.get("tag") or "?" for c in f.get("clips", [])})
                L.append(f"  - {p}: {f.get('afx', 0)} afx / {f.get('af', 0)} af; tags {tags}" + (
                    f" ({f['note']})" if f.get("note") else ""))
            for g, s in e["graphs"].items():
                L.append(f"  - graph {g}: tags {s.get('tags')} events {s.get('events')}" + (
                    f" ({s.get('error') or s.get('note')})" if s.get("error") or s.get("note") else ""))
            L.append("")
    sk = rep.get("skyrim")
    if sk:
        L += ["# Skyrim", ""]
        for b in sk["bases"]:
            idl = "; ".join(f"{i.get('edid')} ev={i.get('event')} file={i.get('file')}" for i in b.get("idles", []))
            L.append(f"- {b['kind']}: {b['edid']} ({b.get('type')}, {b['uses']} uses)"
                     + (f" markers {b['marker_anims']}" if b.get("marker_anims") else "") + (f" idles: {idl}" if idl else ""))
        L.append("")
        for n, b in sk["behaviors"].items():
            if b.get("error"):
                L.append(f"- {n}: {b['error']}")
                continue
            L.append(f"## {n} ({len(b['clips'])} furniture clips)")
            L += [f"- {c['name']}: {c['animation']}" for c in b["clips"][:80]]
            if b["events"]:
                L.append("events: " + ", ".join(b["events"][:60]))
            L.append("")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--starfield", help="Starfield's game folder (Data\\ under it)")
    ap.add_argument("--skyrim-data", help="Skyrim SE's Data folder")
    ap.add_argument("--work", help="a Riverwood build folder: its furniture.json lists the Skyrim bases we convert")
    ap.add_argument("--kind", action="append", help="only these furniture kinds (make_furniture.TEMPLATES keys)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if not (a.starfield or a.skyrim_data):
        ap.error("give --starfield and / or --skyrim-data")
    os.makedirs(a.out, exist_ok=True)
    rep = {}
    if a.starfield:
        rep["starfield"] = starfield_side(a.starfield, a.kind)
        print(f"Starfield: {len(rep['starfield']['templates'])} templates, "
              f"{rep['starfield']['furniture_rows']} Furniture rows in the generated table")
    if a.skyrim_data:
        fj = os.path.join(a.work, "furniture.json") if a.work else None
        rep["skyrim"] = skyrim_side(a.skyrim_data, fj)
        print(f"Skyrim: {len(rep['skyrim']['bases'])} furniture bases, "
              f"{len(rep['skyrim']['behaviors'])} behaviours with furniture clips")
    with open(os.path.join(a.out, "furniture_anims.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    with open(os.path.join(a.out, "furniture_anims.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown(rep))
    print("->", os.path.join(a.out, "furniture_anims.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
