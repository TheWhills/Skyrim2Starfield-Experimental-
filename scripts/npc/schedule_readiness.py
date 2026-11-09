"""Which of a batch's NPCs can be given their Skyrim schedules now, and what stops the others (read-only).

    python -I scripts\\npc\\schedule_readiness.py --skyrim "$sky\\Skyrim.esm" --starfield "$sf\\Data\\Starfield.esm" ^
        --work C:\\Modding\\work\\s2s\\riverwood_doors --faces "$face\\faces.json" --out C:\\Modding\\work\\packages

Every NPC placed (ACHR) in the batch's cells (<work>\\cells.txt) goes through make_schedule's own package conversion
(a dry run: the same rules the build uses), so per NPC: each package converted (template, schedule, location kind)
or left out and why (conditions / quest, a location outside the batch, no Starfield template); the furniture its
packages point at (make_furniture's kind, or "static" when it has no Starfield counterpart yet); whether face_fit has
made its face-test NPC (faces.json). Status: ready (every package converts), partial (some do), blocked (none), with
the blocking reasons counted over all NPCs, and the -Actors list for riverwood_doors.ps1. Writes readiness.json and
readiness.md.
"""
import argparse
import json
import os
import struct
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts", "interior"))

from fo4sf import packages, skyrimnpc  # noqa: E402
import make_schedule as MS  # noqa: E402


def reason_of(note):
    """A short, countable reason from a make_schedule note."""
    n = note.lower()
    if "quest / conditions" in n:
        return "conditions / quest-owned"
    if "outside the batch" in n:
        return "location outside the converted cells"
    if "has no starfield template" in n:
        return "no Starfield package template"
    if "not translated yet" in n:
        return "location type not translated"
    if "without a starfield counterpart" in n:
        return "some inputs kept vanilla"
    return note.split(":", 1)[-1].strip()[:60]


def batch_cells(work):
    names = set()
    path = os.path.join(work, "cells.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    with open(line, encoding="utf-8") as c:
                        names.add(json.load(c)["cell"])
    return names


def placed_npcs(sky, cell_names):
    """{npc form: [(achr, cell EditorID)]} for the NPCs placed in the given cells."""
    out = {}
    for r in sky.by_type.get(b"ACHR", []):
        cell = sky.edid(sky.cell_of.get(r, 0) or 0)
        if cell not in cell_names:
            continue
        base = next((struct.unpack_from("<I", d)[0] for s, d in sky.subs(r) if s == b"NAME" and len(d) == 4), None)
        if base is not None and sky.kind(base) == "NPC_":
            out.setdefault(base, []).append((r, cell))
    return out


def furniture_kind(sky, fid):
    """make_furniture's kind for a Skyrim base (FURN / IDLM), 'static' when it has none, None for other records."""
    if sky.kind(fid) not in ("FURN", "IDLM"):
        return None
    import furniture_survey
    import make_furniture
    rec = furniture_survey.base_record(sky, fid, starfield=False)
    return make_furniture.kind_of(rec) or "static"


def assess(sky, sf_tpls, fid, cell_names, faces_edids):
    npc = skyrimnpc.parse_npc(sky.subs(fid), fid)
    src = npc
    if npc["template"] and npc["template_flags"] & skyrimnpc.TEMPLATE_AI_PACKAGES and sky.kind(npc["template"]) == "NPC_":
        src = skyrimnpc.parse_npc(sky.subs(npc["template"]), npc["template"])
    edid = sky.edid(fid)
    row = {"edid": edid, "name": npc.get("full_name") or edid, "female": npc["female"],
           "face_test_npc": edid.lower() in faces_edids, "packages": [], "furniture": Counter()}
    for p in src["packages"]:
        notes = []
        got = MS.convert_package(sky, sf_tpls, p, cell_names, notes, False, True)
        pr = {"edid": sky.edid(p), "converted": got is not None,
              "reasons": sorted({reason_of(n) for n in notes})}
        if got is not None:
            pr.update(template=f"{got['skyrim_template']} -> {got['sf_template']}",
                      hour=(got["schedule"] or {}).get("hour"), duration_min=(got["schedule"] or {}).get("duration_min"))
            for v in got["inputs"].values():
                if isinstance(v, dict) and v.get("type") == "near_reference":
                    ref = packages_ref_form(v.get("source"))
                    base = ref_base(sky, ref) if ref is not None else None
                    k = furniture_kind(sky, base) if base is not None else None
                    if k:
                        row["furniture"][k] += 1
                    pr["near"] = v.get("base")
        row["packages"].append(pr)
    n_ok = sum(p["converted"] for p in row["packages"])
    row["status"] = ("no packages" if not row["packages"] else "ready" if n_ok == len(row["packages"])
                     else "partial" if n_ok else "blocked")
    row["furniture"] = dict(row["furniture"])
    return row


def packages_ref_form(formkey):
    """The FormID of a 'XXXXXX:Skyrim.esm' form key (make_schedule's source)."""
    if not formkey:
        return None
    try:
        return int(str(formkey).split(":")[0], 16)
    except ValueError:
        return None


def ref_base(sky, ref):
    return next((struct.unpack_from("<I", d)[0] for s, d in sky.subs(ref) if s == b"NAME" and len(d) == 4), None)


def report_md(rows, counts, actors):
    lines = ["# Schedule readiness", "", f"Ready for the build: `-Actors {','.join(actors)}`" if actors else
             "No NPC is fully ready.", "", "| NPC | status | packages converted | why not | furniture | face test |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        why = sorted({x for p in r["packages"] if not p["converted"] for x in p["reasons"]})
        conv = sum(p["converted"] for p in r["packages"])
        fur = ", ".join(f"{k} x{v}" for k, v in sorted(r["furniture"].items()))
        lines.append(f"| {r['name']} ({r['edid']}) | {r['status']} | {conv}/{len(r['packages'])} | {'; '.join(why)} | "
                     f"{fur} | {'yes' if r['face_test_npc'] else 'no'} |")
    lines += ["", "Packages left out, by reason:", ""] + [f"- {k}: {v}" for k, v in counts.most_common()]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--work", required=True, help="the interior batch work folder (cells.txt)")
    ap.add_argument("--faces", default="", help="face_fit.py's faces.json (who has a face-test NPC)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    cell_names = batch_cells(a.work)
    if not cell_names:
        ap.error(f"no cells in {os.path.join(a.work, 'cells.txt')}")
    faces_edids = set()
    if a.faces and os.path.exists(a.faces):
        with open(a.faces, encoding="utf-8") as fh:
            faces_edids = {r["edid"].lower() for r in json.load(fh).get("npcs", [])
                           if isinstance(r.get("test_npc"), dict)}          # a string = why none was made
    sf_tpls, _x = MS.load_sf_templates(a.starfield)
    sky = packages.Index(a.skyrim)
    try:
        rows = [assess(sky, sf_tpls, fid, cell_names, faces_edids)
                for fid in sorted(placed_npcs(sky, cell_names))]
    finally:
        sky.close()
    rows.sort(key=lambda r: ({"ready": 0, "partial": 1, "blocked": 2}.get(r["status"], 3), r["edid"]))
    counts = Counter(x for r in rows for p in r["packages"] if not p["converted"] for x in p["reasons"])
    actors = [r["edid"] for r in rows if r["status"] in ("ready", "partial")]
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "readiness.json"), "w", encoding="utf-8") as fh:
        json.dump({"cells": sorted(cell_names), "npcs": rows, "left_out_by_reason": dict(counts),
                   "actors_ready_or_partial": actors}, fh, indent=1)
    with open(os.path.join(a.out, "readiness.md"), "w", encoding="utf-8") as fh:
        fh.write(report_md(rows, counts, actors))
    st = Counter(r["status"] for r in rows)
    print(f"{len(rows)} NPCs placed in {len(cell_names)} cells: " + ", ".join(f"{k} {v}" for k, v in st.items()))
    for k, v in counts.most_common():
        print(f"  left out: {k}: {v}")
    print(f"  -Actors {','.join(actors)}")
    print(f"-> {os.path.join(a.out, 'readiness.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
