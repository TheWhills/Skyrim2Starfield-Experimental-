"""Survey vanilla Starfield load doors: what a working interior load door looks like, to compare with ours.

    python -I scripts\\interior\\door_survey.py --esm "<Starfield>\\Data\\Starfield.esm" --out <folder> [--max 2000]

Reads every reference with a teleport (XTEL) in the CELL top group and writes <out>\\door_survey.json:
  - xtel: size histogram, flag histogram, the 4 bytes after the flags (how often set, and what record they name)
  - semantics: for door A whose XTEL names door B, how far A's XTEL position is from B (Skyrim: the landing spot
    in front of B) and from A itself when both sit in the same cell; how often B's XTEL names A back
  - fields: which subrecords load-door references carry (and how often), reference record flags
  - bases: the record type of the doors' bases; for DOOR bases the FNAM flags, the component types (BFCB) and the
    other subrecords, plus a few examples with editor ids and models
Owner's run (Oct 2026): a converted load door teleports once, then its prompt disappears until the save is reloaded,
and the return trip lands at the wrong end. Our doors carry NAME, XTEL, DATA only, on a DOOR base with EDID / MODL /
FNAM 0 and nothing else; this shows what vanilla adds.
"""
import argparse
import collections
import json
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import fo4land  # noqa: E402

PERSISTENT = 0x400


def parse_xtel(d):
    """XTEL: destination door, position (3 floats), rotation (3 floats), flags, then any extra bytes (raw)."""
    if len(d) < 32:
        return None
    door, px, py, pz, rx, ry, rz, flags = struct.unpack_from("<I6fI", d)
    return {"door": door, "pos": [px, py, pz], "rot": [rx, ry, rz], "flags": flags, "extra": bytes(d[32:])}


def walk_refs(p, limit):
    """{ref fid: {cell, base, pos, flags, fields: [sigs], xtel}} for references with XTEL, plus every record's type by
    fid for the formids the XTELs and bases name (filled later)."""
    top = next((it for it in fo4land.iter_items(p.buf, p.body, len(p.buf)) if it[0] == "GRUP" and it[3] == b"CELL"),
               None)
    refs = {}
    if top is None:
        return refs

    def walk(start, end, cell):
        for it in fo4land.iter_items(p.buf, start, end):
            if len(refs) >= limit:
                return
            if it[0] == "GRUP":
                gtype = it[4]
                # cell children groups (6 / 8 / 9 / 10) carry the owning cell's fid as their label
                child_cell = struct.unpack("<I", it[3])[0] if gtype in (6, 8, 9, 10) else cell
                walk(it[1] + 24, it[2], child_cell)
                continue
            typ, off, flags, fid = it
            if typ != b"REFR":
                continue
            fields = list(fo4land.iter_subrecords(fo4land.record_data(p.buf, off)))
            x = next((parse_xtel(d) for s, d in fields if s == b"XTEL"), None)
            if x is None:
                continue
            ref = fo4land.parse_ref(fields)
            refs[fid] = {"cell": cell, "base": ref["base"], "pos": ref["pos"], "flags": flags,
                         "fields": [s.decode("ascii", "replace") for s, _d in fields], "xtel": x}
    walk(top[1] + 24, top[2], None)
    return refs


def record_index(p, wanted):
    """{fid: (type, fields)} for the wanted form ids found anywhere outside the CELL / WRLD groups (bases), and
    {fid: type} for wanted ids found as cells."""
    found, types = {}, {}
    stack = [(p.body, len(p.buf))]
    while stack:
        start, end = stack.pop()
        for it in fo4land.iter_items(p.buf, start, end):
            if it[0] == "GRUP":
                if it[4] == 0 and it[3] in (b"WRLD", b"DIAL", b"QUST", b"NAVI"):
                    continue
                if it[4] in (6, 8, 9, 10):                     # cell children: only the CELL records themselves
                    continue
                stack.append((it[1] + 24, it[2]))
                continue
            typ, off, _flags, fid = it
            if fid in wanted:
                types[fid] = typ.decode("ascii", "replace")
                if typ != b"CELL":
                    found[fid] = list(fo4land.iter_subrecords(fo4land.record_data(p.buf, off)))
    return found, types


def components(fields):
    """Component type names of a Starfield base record (BFCB strings)."""
    return [fo4land.zstring(d) for s, d in fields if s == b"BFCB"]


def survey(esm, limit):
    with fo4land.Plugin(esm) as p:
        refs = walk_refs(p, limit)
        bases = {r["base"] for r in refs.values() if r["base"] is not None}
        extras = {struct.unpack_from("<I", r["xtel"]["extra"])[0] for r in refs.values()
                  if len(r["xtel"]["extra"]) >= 4} - {0}
        found, types = record_index(p, bases | extras)

    xsize, xflags, extra_set, extra_types = (collections.Counter() for _ in range(4))
    field_counts, ref_flags, base_types = collections.Counter(), collections.Counter(), collections.Counter()
    to_dest, same_cell_self, mutual, dest_known = [], [], 0, 0
    for fid, r in refs.items():
        x = r["xtel"]
        xsize[32 + len(x["extra"])] += 1
        xflags[x["flags"]] += 1
        if len(x["extra"]) >= 4:
            e = struct.unpack_from("<I", x["extra"])[0]
            extra_set["set" if e else "zero"] += 1
            if e:
                extra_types[types.get(e, "not found")] += 1
        for s in set(r["fields"]):
            field_counts[s] += 1
        ref_flags["persistent" if r["flags"] & PERSISTENT else "temporary"] += 1
        base_types[types.get(r["base"], "not found")] += 1
        dest = refs.get(x["door"])
        if dest is None or dest["pos"] is None:
            continue
        dest_known += 1
        to_dest.append(math.dist(x["pos"], dest["pos"]))
        if dest["xtel"]["door"] == fid:
            mutual += 1
        if dest["cell"] == r["cell"] and r["pos"] is not None:
            same_cell_self.append(math.dist(x["pos"], r["pos"]))

    door_fnam, door_comps, door_fields, examples = (collections.Counter(), collections.Counter(),
                                                   collections.Counter(), [])
    for fid in sorted(bases):
        if types.get(fid) != "DOOR" or fid not in found:
            continue
        f = found[fid]
        fnam = next((d for s, d in f if s == b"FNAM"), b"")
        door_fnam[fnam.hex() or "(none)"] += 1
        for c in set(components(f)):
            door_comps[c] += 1
        for s in {s for s, _d in f}:
            door_fields[s.decode("ascii", "replace")] += 1
        if len(examples) < 15:
            examples.append({"fid": f"{fid:08X}", "edid": next((fo4land.zstring(d) for s, d in f if s == b"EDID"), ""),
                             "model": next((fo4land.zstring(d) for s, d in f if s == b"MODL"), ""),
                             "fnam": fnam.hex(), "components": components(f),
                             "fields": [s.decode("ascii", "replace") for s, _d in f]})

    def top(c, n=25):
        return [[k, v] for k, v in c.most_common(n)]

    def stats(v):
        v = sorted(v)
        return {"n": len(v), "min": v[0] if v else None, "median": v[len(v) // 2] if v else None,
                "max": v[-1] if v else None}
    return {"load_door_refs": len(refs), "destinations_found": dest_known, "mutual_pairs": mutual,
            "xtel": {"sizes": top(xsize), "flags": top(xflags), "extra": top(extra_set),
                     "extra_record_types": top(extra_types)},
            "semantics": {"xtel_pos_to_destination_door_units": stats(to_dest),
                          "xtel_pos_to_own_door_units_same_cell": stats(same_cell_self)},
            "ref_fields": top(field_counts, 40), "ref_flags": top(ref_flags),
            "base_types": top(base_types),
            "door_bases": {"count": sum(door_fnam.values()), "fnam": top(door_fnam), "components": top(door_comps, 40),
                           "fields": top(door_fields, 40), "examples": examples}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--esm", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max", type=int, default=2000)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    report = survey(a.esm, a.max)
    with open(os.path.join(a.out, "door_survey.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    s = report["semantics"]["xtel_pos_to_destination_door_units"]
    print(f"{report['load_door_refs']} load doors, {report['mutual_pairs']} mutual; XTEL position to destination door "
          f"median {s['median']}; base types {report['base_types'][:4]}; DOOR FNAM {report['door_bases']['fnam'][:4]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
