"""Starfield's animated objects (read-only): what a spinning Skyrim water wheel can be built on.

2026-11-18, owner: Riverwood's mill water wheel should spin. Skyrim's wheel spins by keyframes inside its NIF
(NiControllerManager); Starfield NIFs carry no controllers: a record attaches a behaviour graph (.agx), a skeleton
(.rig) and an animations folder (docs/spikes/WP-doors-research.md: the DOOR record's ANAM / BNAM / CNAM). Since the
chicken we write .rig and .af ourselves (CALUMI), so a vanilla object that loops one animation is the template. This
prints, for every record of --types that names an .agx graph and a .rig (doors and actors left out):
  1. type, FormID, EditorID, model, graph, rig and the animations folder (the subrecord each sits in),
  2. records grouped by graph, those whose names sound like constant motion (--loopy) first,
  3. for the --loopy ones (or --match): the clips (.af / .afx) in their animations folder and each descriptor's tag.

    python -I scripts\\interior\\sf_animated_object_probe.py --starfield "<Starfield>" > animated_objects.txt
"""
import argparse
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "scripts", "armor"))

from fo4sf import sfplugin  # noqa: E402

TYPES = "STAT,MSTT,ACTI,CONT,FURN,LIGH,MISC,FLOR,TERM,BNDS,PKIN,GBFM,TACT,SCOL,ADDN,ARTO,IDLM,MOVT,PNDT"
LOOPY = re.compile(r"fan|turbine|wheel|windmill|spin|rotat|rotor|propel|gear|pump|piston|radar|dish|loop|idle|"
                   r"crank|drill|mill|turn|wind|vent|engine|machin|conveyor|sign|beacon", re.I)
TEXT = re.compile(rb"[ -~]{4,}")


def texts(data: bytes):
    return [t.decode("latin-1") for t in TEXT.findall(data)]


def scan_record(subs):
    """{"edid", "model", "graph", "rig", "anims", "where"} of one record's subrecords: the first text ending in .agx,
    the first ending in .rig, the folder text next to them (no extension, "animations" in it), the first .nif."""
    out = {"edid": "", "model": "", "graph": "", "rig": "", "anims": "", "where": {}}
    for s, d in subs:
        sig = s.decode("latin-1")
        if sig == "EDID":
            out["edid"] = d.split(b"\0", 1)[0].decode("latin-1")
            continue
        for t in texts(d):
            low = t.lower()
            if low.endswith(".agx") and not out["graph"]:
                out["graph"], out["where"]["graph"] = t, sig
            elif low.endswith(".rig") and not out["rig"]:
                out["rig"], out["where"]["rig"] = t, sig
            elif low.endswith(".nif") and not out["model"]:
                out["model"], out["where"]["model"] = t, sig
            elif "animations" in low and "." not in os.path.basename(low) and not out["anims"]:
                out["anims"], out["where"]["anims"] = t, sig
    return out


def survey(esm_path: str, types):
    rows = []
    for typ, _h, subs, fid in sfplugin.records(esm_path, [t.encode() for t in types]):
        r = scan_record(subs)
        if r["graph"] and r["rig"]:
            r.update(type=typ.decode("latin-1"), fid=fid)
            rows.append(r)
    return rows


def loopy(r) -> bool:
    return bool(LOOPY.search(" ".join((r["edid"], r["model"], r["graph"], r["rig"]))))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--starfield", required=True, help="the Starfield install (with Data)")
    ap.add_argument("--types", default=TYPES)
    ap.add_argument("--match", default="", help="regex on EditorID / model / graph: list these records' clips too")
    ap.add_argument("--max-clips", type=int, default=12, help="graphs whose folders are listed (loopy / match first)")
    a = ap.parse_args(argv)
    data = os.path.join(a.starfield, "Data")
    rows = survey(os.path.join(data, "Starfield.esm"), a.types.split(","))
    print(f"== {len(rows)} records with a graph and a rig ({a.types})")
    by_graph = defaultdict(list)
    for r in rows:
        by_graph[r["graph"].lower()].append(r)
    order = sorted(by_graph, key=lambda g: (not any(loopy(r) for r in by_graph[g]), g))
    for g in order:
        rs = by_graph[g]
        print(f"\n-- graph {rs[0]['graph']}  ({len(rs)} records){'  [loopy names]' if any(loopy(r) for r in rs) else ''}")
        for r in rs[:12]:
            print(f"   {r['type']} {r['fid']:08X} {r['edid']}: model {r['model']}  rig {r['rig']}  anims {r['anims']}"
                  f"  (fields {r['where']})")
        if len(rs) > 12:
            print(f"   ... {len(rs) - 12} more")
    match = re.compile(a.match, re.I) if a.match else None
    picks = [g for g in order if (match and any(match.search(" ".join((r["edid"], r["model"], r["graph"])))
                                                for r in by_graph[g])) or (not match and any(loopy(r) for r in by_graph[g]))]
    if not picks:
        return 0
    import sf_anim_survey as SAS
    from fo4sf import agx
    index = {}
    for _label, ar in SAS.archives(data):
        for i, nm in enumerate(ar.names):
            index.setdefault(SAS.norm(nm), (ar, i))
    print("\n== clips in the animations folders")
    for g in picks[:a.max_clips]:
        seen = set()
        for r in by_graph[g]:
            folder = SAS.norm(("meshes\\" + r["anims"]) if r["anims"] and not r["anims"].lower().startswith("meshes")
                              else r["anims"]).rstrip("/") + "/"
            if not r["anims"] or folder in seen:
                continue
            seen.add(folder)
            files = sorted(k for k in index if k.startswith(folder) and "/" not in k[len(folder):])
            print(f"\n-- {r['edid']} ({r['graph']}): {folder}  {len(files)} files")
            for k in files[:30]:
                line = f"   {k[len(folder):]}"
                if k.endswith(".afx"):
                    try:
                        ar, i = index[k]
                        dsc = agx.read_descriptor(ar.read(i))
                        line += f"  tag {dsc.get('tag')} file {dsc.get('filename')} state {dsc.get('is_state')}"
                    except Exception as e:                      # noqa: BLE001  (one odd descriptor must not stop it)
                        line += f"  ({type(e).__name__})"
                print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
