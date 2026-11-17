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


def package_conditions(sky, pack_fid, npc_row, world):
    """[{text, verdict, kind}] for a Skyrim package's own conditions (CTDA before its data inputs): the function and
    its parameters by name, and skyrimdialog.evaluate's reading at the start of a new game (kind 'start': decided,
    'ambient': varies in play - time, weather, chance -, 'story' / 'player' / 'unknown'). 2026-11-17 (owner: "what are
    we dropping aspects of these? Our goal is a faithful conversion"): a conditioned package was left out with only
    a count; this says what each condition is, so each can be converted rather than dropped."""
    from fo4sf import skyrimdialog as SD
    ops = {0: "==", 1: "!=", 2: ">", 3: ">=", 4: "<", 5: "<="}
    out = []
    for sig, d in sky.subs(pack_fid):
        if sig in (b"PKCU", b"ANAM", b"PLDT", b"PTDA"):
            break
        if sig != b"CTDA":
            continue
        c = SD.parse_condition(d)
        if not c:
            continue
        name = SD.NAME_OF.get(c["function"], f"function {c['function']}")
        args = [sky.edid(x) or f"{x:06X}" for x in (c["param1"], c["param2"]) if x and sky.kind(x)]
        if c["param1"] and not sky.kind(c["param1"]):
            args.insert(0, str(c["param1"]))
        val = (f"global {sky.edid(int(c['value'])) or int(c['value'])}" if c["use_global"] else f"{c['value']:g}")
        run = {0: "", 1: " (on target)", 2: f" (on {sky.edid(c['reference']) or hex(c['reference'])})"}.get(
            c["run_on"], f" (run on {c['run_on']})")
        got, kind = SD.evaluate(c, npc_row, world) if world is not None else (None, "unknown")
        out.append({"text": f"{name}({', '.join(args)}){run} {ops.get(c['op'], '?')} {val}"
                            + (" OR" if c["or"] else ""),
                    "at_start": got, "kind": kind})
    return out


def assess(sky, sf_tpls, fid, cell_names, faces_edids, ext_cells=None, world=None):
    npc = skyrimnpc.parse_npc(sky.subs(fid), fid)
    src = npc
    if npc["template"] and npc["template_flags"] & skyrimnpc.TEMPLATE_AI_PACKAGES and sky.kind(npc["template"]) == "NPC_":
        src = skyrimnpc.parse_npc(sky.subs(npc["template"]), npc["template"])
    edid = sky.edid(fid)
    row = {"edid": edid, "name": npc.get("full_name") or edid, "female": npc["female"],
           "face_test_npc": edid.lower() in faces_edids, "packages": [], "furniture": Counter()}
    for p in src["packages"]:
        notes = []
        got = MS.convert_package(sky, sf_tpls, p, cell_names, notes, False, True, ext_cells)
        pr = {"edid": sky.edid(p), "converted": got is not None,
              "reasons": sorted({reason_of(n) for n in notes})}
        if got is None:
            raw = packages.parse_pack(sky.subs(p))
            pr["skyrim_template"] = sky.edid(raw["template"]) if raw.get("template") else None
            pr["schedule"] = raw.get("schedule")
            if raw.get("owner_quest"):
                pr["owner_quest"] = sky.edid(raw["owner_quest"])
            if raw.get("conditions"):
                pr["conditions"] = package_conditions(sky, p, npc, world)
        if got is not None:
            pr.update(template=f"{got['skyrim_template']} -> {got['sf_template']}",
                      hour=(got["schedule"] or {}).get("hour"), duration_min=(got["schedule"] or {}).get("duration_min"))
            for v in got["inputs"].values():
                if isinstance(v, dict) and v.get("type") in ("near_reference", "near_exterior_reference"):
                    ref = packages_ref_form(v.get("source"))
                    base = ref_base(sky, ref) if ref is not None else None
                    k = furniture_kind(sky, base) if base is not None else None
                    if k:
                        row["furniture"][k] += 1
                    pr["near"] = v.get("base")
                    pr["near_kind"] = k
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
    lines += ["", "## Packages per NPC", "",
              "Converted: Skyrim template -> Starfield's, start hour, minutes, the object the area is centred on "
              "(its furniture kind; static = no Starfield counterpart yet). Left out: why.", ""]
    for r in rows:
        lines.append(f"- **{r['name']}**")
        for p in r["packages"]:
            if p["converted"]:
                h = p.get("hour")
                near = f", near {p['near']}" + (f" ({p['near_kind']})" if p.get("near_kind") else "") if p.get(
                    "near") else ""
                lines.append(f"  - {p['edid']}: {p.get('template')}, {'any time' if h is None or h < 0 else f'{h}:00'}"
                             f" for {p.get('duration_min')} min{near}")
            else:
                lines.append(f"  - {p['edid']}: left out ({'; '.join(p['reasons'])})"
                             + (f", template {p['skyrim_template']}" if p.get("skyrim_template") else "")
                             + (f", quest {p['owner_quest']}" if p.get("owner_quest") else ""))
                for c in p.get("conditions") or []:
                    at = {True: "true", False: "false", None: "?"}[c["at_start"]]
                    lines.append(f"    - `{c['text']}`: {c['kind']}, at game start {at}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--work", required=True, help="the interior batch work folder (cells.txt)")
    ap.add_argument("--faces", default="", help="face_fit.py's faces.json (who has a face-test NPC)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--exterior", default="", help="the installed exterior's staging folder (formids.json), as the "
                                                   "build passes it: package locations outdoors are then kept")
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
    ext_cells = None
    fp = os.path.join(a.exterior, "formids.json") if a.exterior else ""
    if fp and os.path.exists(fp):
        ext_cells = MS.exterior_cells(sky, fp)
    elif fp:
        print(f"no {fp}: outdoor package locations counted as outside")
    try:
        try:
            from fo4sf import skyrimdialog as SD
            world = SD.world_from(a.skyrim)
        except Exception as e:                                       # noqa: BLE001
            print(f"no game-start world ({type(e).__name__}: {e}): conditions listed without a verdict")
            world = None
        rows = [assess(sky, sf_tpls, fid, cell_names, faces_edids, ext_cells, world)
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
