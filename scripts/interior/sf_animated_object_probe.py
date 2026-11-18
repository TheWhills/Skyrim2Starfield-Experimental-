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
    ... --match Fan_Yard_03 --dump Fan_Yard_03 --calumi "<CALUMI.Animation.dll>" --extract-to C:\\Modding\\work\\fan
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


def dump_fields(subs) -> list:
    """Every subrecord: signature, size, its text (printable runs) or, when short and not text, its hex."""
    out = []
    for sig, d in subs:
        t = " | ".join(texts(d))
        out.append(f"     {sig.decode('latin-1')} {len(d):5d}  " + (t[:200] if t else d[:48].hex(" ")))
    return out


def axis_angle(q) -> tuple:
    """(unit axis, degrees) of an x y z w quaternion."""
    import math
    x, y, z, w = (float(v) for v in q)
    s = math.sqrt(max(1e-12, x * x + y * y + z * z))
    ang = 2 * math.degrees(math.atan2(s, w))
    return (round(x / s, 3), round(y / s, 3), round(z / s, 3)), round(ang, 2)


def track_lines(calumi: str, rig_bytes: bytes, clip: bytes, work: str) -> list:
    """Through CALUMI: the clip's frames, and per bone its key count and the rotation from the first key to each
    quarter of the clip as (axis, degrees): a looping spin shows one axis and a steadily growing angle."""
    from fo4sf import af_writer
    from fo4sf.retarget import qinv, qmul
    import numpy as np
    os.makedirs(work, exist_ok=True)
    rig, af = os.path.join(work, "probe.rig"), os.path.join(work, "probe.af")
    with open(rig, "wb") as fh:
        fh.write(rig_bytes)
    with open(af, "wb") as fh:
        fh.write(clip)
    rb = af_writer.read_back(calumi, af, rig)
    out = [f"     {rb['frames']} frames, bones {rb['bones']}"]
    for b in rb["bones"]:
        keys = rb["rotations"].get(b) or []
        tr = rb["translations"].get(b) or []
        line = f"     {b}: {len(keys)} rotation keys, {len(tr)} translation keys"
        if len(keys) > 1:
            q0 = np.asarray(keys[0][1], float)
            for frac in (0.25, 0.5, 0.75, 1.0):
                f, q = keys[min(len(keys) - 1, int(round(frac * (len(keys) - 1))))]
                line += f"; frame {f}: {axis_angle(qmul(qinv(q0), np.asarray(q, float)))}"
        out.append(line)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--starfield", required=True, help="the Starfield install (with Data)")
    ap.add_argument("--types", default=TYPES)
    ap.add_argument("--match", default="", help="regex on EditorID / model / graph: list these records' clips too")
    ap.add_argument("--max-clips", type=int, default=12, help="graphs whose folders are listed (loopy / match first)")
    ap.add_argument("--dump", default="", help="regex on EditorID: print every subrecord of these records")
    ap.add_argument("--calumi", help="CALUMI.Animation.dll: with --match, each listed .af's bones and rotation")
    ap.add_argument("--extract-to", default="", help="with --match: copy the records' model, rig and clips here "
                                                      "(outside the repository: game files stay out of Git)")
    a = ap.parse_args(argv)
    data = os.path.join(a.starfield, "Data")
    esm = os.path.join(data, "Starfield.esm")
    if a.dump:
        dmp = re.compile(a.dump, re.I)
        for typ, _h, subs, fid in sfplugin.records(esm, [t.encode() for t in a.types.split(",")]):
            r = scan_record(subs)
            if r["edid"] and dmp.search(r["edid"]):
                print(f"== {typ.decode('latin-1')} {fid:08X} {r['edid']}")
                print("\n".join(dump_fields(subs)))
    rows = survey(esm, a.types.split(","))
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
            rig_key = SAS.norm("meshes\\" + r["rig"]) if not r["rig"].lower().startswith("meshes") else SAS.norm(r["rig"])
            rig_bytes = index[rig_key][0].read(index[rig_key][1]) if rig_key in index else None
            if a.extract_to and match:
                _extract(a.extract_to, index, [rig_key, SAS.norm("meshes\\" + r["model"])] + files)
            if rig_bytes is not None:
                from creature_probe import rig_names
                print(f"   rig {rig_key}: bones {rig_names(rig_bytes)}")
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
                if a.calumi and match and k.endswith(".af") and rig_bytes is not None:
                    try:
                        ar, i = index[k]
                        print("\n".join(track_lines(a.calumi, rig_bytes, ar.read(i),
                                                     os.path.join(os.environ.get("TEMP", "/tmp"), "s2s_probe"))))
                    except Exception as e:                      # noqa: BLE001
                        print(f"     tracks unreadable: {type(e).__name__}: {e}")
    return 0


def _extract(out_dir: str, index, keys):
    repo = os.path.abspath(REPO)
    out = os.path.abspath(out_dir)
    if out == repo or out.startswith(repo + os.sep):
        raise SystemExit("--extract-to must be outside the repository (game files stay out of Git)")
    os.makedirs(out, exist_ok=True)
    for k in keys:
        if k in index:
            ar, i = index[k]
            with open(os.path.join(out, k.replace("/", "_")), "wb") as fh:
                fh.write(ar.read(i))


if __name__ == "__main__":
    sys.exit(main())
