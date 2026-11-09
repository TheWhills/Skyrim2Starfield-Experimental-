"""Skyrim furniture and idle markers in the converted interiors as Starfield furniture NPCs can use (docs/npc/furniture.md).

    python -I scripts\\interior\\make_furniture.py --skyrim "$sky\\Skyrim.esm" --skyrim-data "$sky" ^
        --work C:\\Modding\\work\\s2s\\riverwood_doors

Writes <work>\\furniture.json, which PluginSpike reads (FURNITURE=<that file>): per Skyrim FURN / IDLM base placed in
the batch's cells (<work>\\cells.txt), the vanilla Starfield furniture to copy (TEMPLATES, chosen from the owner's
furniture_survey.py run 2026-11-08), the model (Skyrim's converted model for real furniture; none = the template's
invisible marker model) and the markers; and every placed reference (Skyrim position / rotation / scale).

Why this way (survey, 2026-11-08): Starfield picks a furniture's animation from its KEYWORDS (AnimFurnChair,
AnimFurnBench, AnimFurnBed, AnimFurnRailLeanHands, AnimFurnStanding_Sweep, ...) and puts the marker positions in the
record (SNAM: offset, rotation, entry / exit sides; z is 0 in every vanilla one); Skyrim keeps them in the NIF
(BSFurnitureMarkerNode). Starfield's idle-marker-like actions (sweeping, arms crossed, browsing) are invisible
marker-only furniture, not IDLM (Starfield has 18 IDLM). So each Skyrim base becomes a copy of a vanilla Starfield
furniture of the same kind: its keywords / flags / entry sides, our model, and per Skyrim marker an SNAM entry.
Markers: chairs, benches, beds ("regular") take the Skyrim marker's x / y (units / 70) and heading, z 0 (--marker-z
skyrim keeps Skyrim's seat height instead); Skyrim's special markers (lean counters, the hammer table, idle markers),
whose own animation does the stand-off, take the Starfield template's offsets as they are. Crafting stations
(cooking pot, alchemy, enchanting) and quest furniture stay statics for now.
Entry sides: Skyrim's (FNPR / NIF entry points minus the record's disabled ones; Behind -> Rear, Up -> Other), else the
template's. References a converted NPC's package names (actors.json "near_reference") are made persistent.
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

from fo4sf import packages, skyrimrefs  # noqa: E402
import furniture_survey as survey  # noqa: E402

U = 70.0
# Starfield.esm furniture to copy (owner's survey 2026-11-08: form, EditorID, uses in Starfield.esm, keywords)
TEMPLATES = {
    # real (drawn, player-usable) vanilla furniture, not the marker-only NPCInvChairSit_Free / NPCInvBenchSit (owner
    # 2026-11-08: chairs and benches made from those could not be used)
    "chair": ("001BF52D", "FoundCanvasChair01_Free"),              # AnimFurnChair, AnimFurnAllowEating (240 uses)
    "bench": ("001E426C", "Bench_UtilityA02"),                     # AnimFurnBench (203 uses)
    "bed": ("001FEE01", "FoundCanvasCot01"),                       # AnimFurnBed, IsSleepFurniture (100 uses)
    # bar counters (owner 2026-11-08: the rail lean put Orgnar's hands on the counter's lower shelf, off the bar):
    # Starfield's own bar furniture, marker at the origin like Skyrim's
    "bartender": ("0025ECE1", "NPCBartender_Standing"),            # AnimFurnBartender, behind the bar (69 uses)
    "lean_counter": ("0005151F", "NPCLeaningBartopFront"),         # AnimFurnLeaningBartopFront, a patron (57 uses)
    "lean_table": ("0002C326", "NPCDeskLean"),                     # AnimFurnDeskLean (71 uses)
    "hammer": ("0000A4B0", "NPCRepair_ToolStanding_Hammer"),       # AnimFurnRepair_Tool_HammerStanding
    "sweep": ("00190D67", "NPCSweeping"),                          # AnimFurnStanding_Sweep (326 uses)
    "arms_crossed": ("0003A05E", "NPCStanding_AnimFlavorArmsCrossedCasual"),
    "browse": ("003E921A", "NPCStanding_AnimFlavorWindowShopping"),
    "arms_front": ("003E9211", "NPCStanding_AnimFlavorArmsFrontCasual"),
    "stand": ("0021FE54", "NPCStanding"),                          # AnimFurnStanding (787 uses)
}
SPECIAL = {"bartender", "lean_counter", "lean_table", "hammer", "sweep", "arms_crossed", "browse", "arms_front", "stand"}
# Skyrim idle-marker animations (IDLE EditorIDs, lower case) -> kind
IDLE_KINDS = [("sweep", "sweep"), ("armscrossed", "arms_crossed"), ("examine", "browse"), ("study", "browse"),
              ("warmhands", "arms_front")]
SIDES = {"Front": "Front", "Behind": "Rear", "Right": "Right", "Left": "Left", "Up": "Other"}


def kind_of(rec):
    """Which Starfield template a Skyrim FURN / IDLM becomes; None = left as it is (a static, or nothing)."""
    edid = rec.get("edid") or ""
    if rec["type"] == "IDLM":
        anims = " ".join(rec.get("animations") or []).lower()
        return next((k for key, k in IDLE_KINDS if key in anims), "stand")
    if re.match(r"MQ\d", edid):
        return None                                            # quest furniture
    kw = {k.lower() for k in rec.get("keywords") or []}
    if "isbarcounter" in kw:
        return "bartender"
    if "furniturecounterleanmarker" in kw:
        return "lean_counter"
    if "isleantable" in kw:
        return "lean_table"
    if "ishammertable" in kw:
        return "hammer"
    if kw & {"craftingcookpot", "issmallcookingpot", "wicraftingalchemy", "wicraftingenchanting", "isalchemy",
             "isenchanting"}:
        return None             # crafting stations: their Skyrim animation stands off the model; no Starfield match yet
    anims = {m.get("anim") for m in rec.get("nif_markers") or [] if isinstance(m, dict)}
    anims |= {e["type"] for e in rec.get("entry_points") or []}
    if "Sleep" in anims or "Has Sleep Marker" in (rec.get("mnam") or {}).get("flags", []):
        return "bed"
    if "Lean" in anims:
        return "lean_counter"
    if "istable" in kw or "bench" in edid.lower():
        return "bench"
    if "Sit" in anims:
        return "chair"
    return None


def markers(rec, kind, marker_z):
    """Per Skyrim marker: offset (m), rotation (degrees), entry sides; [] = use the template's SNAM unchanged."""
    if kind in SPECIAL:
        return []
    nm = [m for m in rec.get("nif_markers") or [] if isinstance(m, dict) and "offset" in m]
    disabled = {m["index"]: set(m.get("disabled") or []) for m in rec.get("markers") or []}
    out = []
    for i, m in enumerate(nm):
        sides = [SIDES[s] for s in m.get("entry") or [] if s not in disabled.get(i, set()) and s in SIDES]
        z = round(m["offset"][2] / U, 3) if marker_z == "skyrim" else 0.0
        out.append({"offset_m": [round(m["offset"][0] / U, 3), round(m["offset"][1] / U, 3), z],
                    "rot_deg": m["heading_deg"], "entry": sides})
    return out


def actor_targets(work):
    path = os.path.join(work, "actors.json")
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as fh:
        a = json.load(fh)
    return {v.get("source") for ac in a.get("actors", []) for p in ac.get("packages", [])
            for v in p.get("inputs", {}).values() if isinstance(v, dict) and v.get("type") == "near_reference"}


def parse_shift(items):
    """["bartender=0,0.2,0", ...] -> {kind: [dx, dy, dz]} (metres, in the furniture's own frame: +y = its facing)."""
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        xyz = [float(x) for x in v.split(",")]
        if k not in TEMPLATES or len(xyz) != 3:
            raise ValueError(f"--shift {it!r}: want <kind>=dx,dy,dz with kind one of {sorted(TEMPLATES)}")
        out[k] = xyz
    return out


def build(ix, cells, archives, marker_z="floor", targets=(), shift=None):
    cell_ids = {}
    for c in cells:
        f = ix.find_edid(b"CELL", c)
        if f is not None:
            cell_ids[f] = c
    refs, base_recs = [], {}
    for r, c in sorted(ix.cell_of.items()):
        if c not in cell_ids or ix.kind(r) != "REFR":
            continue
        b = survey.ref_base(ix, r)
        if b is None or ix.kind(b) not in ("FURN", "IDLM"):
            continue
        if b not in base_recs:
            rec = survey.base_record(ix, b, starfield=False)
            if archives is not None and rec.get("model") and rec["type"] == "FURN":
                data = archives.mesh(rec["model"])
                try:
                    rec["nif_markers"] = survey.nif_markers(data) if data is not None else []
                except (ValueError, struct.error):
                    rec["nif_markers"] = []
            base_recs[b] = rec
        ref = next(((d, s) for s, d in ix.subs(r) if s == b"DATA" and len(d) >= 24), None)
        if ref is None:
            continue
        v = struct.unpack_from("<6f", ref[0])
        scale = next((struct.unpack_from("<f", d)[0] for s, d in ix.subs(r) if s == b"XSCL" and len(d) == 4), 1.0)
        key = skyrimrefs.formkey(r, "Skyrim.esm")
        refs.append({"formkey": key, "cell": cell_ids[c], "base": skyrimrefs.formkey(b, "Skyrim.esm"),
                     "pos": [round(x, 3) for x in v[:3]], "rot": [round(x, 5) for x in v[3:]], "scale": round(scale, 4),
                     "persistent": key in targets})
    bases, skipped = {}, []
    for b, rec in base_recs.items():
        kind = kind_of(rec)
        key = skyrimrefs.formkey(b, "Skyrim.esm")
        if kind is None:
            skipped.append(f"{rec['edid']}: no Starfield furniture for it (left as a static)")
            continue
        form, tedid = TEMPLATES[kind]
        nm = rec.get("nif_markers")
        if kind not in SPECIAL and not nm:
            skipped.append(f"{rec['edid']}: {kind} but no marker positions in its NIF (no --skyrim-data?); left as a static")
            continue
        real_model = rec["type"] == "FURN" and not rec["is_marker"]
        bases[key] = {"edid": rec["edid"], "type": rec["type"], "kind": kind, "template": form, "template_edid": tedid,
                      "model": rec.get("model") if real_model else None, "markers": markers(rec, kind, marker_z)}
        if (shift or {}).get(kind):
            bases[key]["shift_m"] = shift[kind]
    refs = [r for r in refs if r["base"] in bases]
    return {"bases": bases, "refs": refs, "skipped": skipped, "marker_z": marker_z}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True, help="Skyrim.esm")
    ap.add_argument("--skyrim-data", required=True, help="Skyrim Data folder (archives): marker positions from the NIFs")
    ap.add_argument("--work", required=True, help="interior batch work folder (cells.txt; furniture.json is written there)")
    ap.add_argument("--marker-z", choices=("floor", "skyrim"), default="floor",
                    help="marker height: floor (as every vanilla Starfield SNAM) or Skyrim's seat height")
    ap.add_argument("--shift", action="append", default=[], metavar="KIND=DX,DY,DZ",
                    help="move every marker of a kind, metres in the furniture's frame (+y forward), e.g. "
                         "bartender=0,0.2,0 (furniture_standoff.py measures how far)")
    a = ap.parse_args(argv)
    try:
        shift = parse_shift(a.shift)
    except ValueError as e:
        ap.error(str(e))
    cells = survey.batch_cells(a.work, [])
    if not cells:
        ap.error(f"no cells.txt in {a.work}")
    from fo4sf import bsa
    archives = bsa.SkyrimArchives(a.skyrim_data)
    ix = packages.Index(a.skyrim)
    try:
        out = build(ix, cells, archives, a.marker_z, actor_targets(a.work), shift)
    finally:
        ix.close()
    path = os.path.join(a.work, "furniture.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    by_kind = {}
    for b in out["bases"].values():
        n = sum(1 for r in out["refs"] if out["bases"].get(r["base"]) is b)
        by_kind.setdefault(b["kind"], []).append(f"{b['edid']} x{n}")
    print(f"{len(out['refs'])} furniture references from {len(out['bases'])} Skyrim bases in {len(cells)} cells "
          f"({sum(r['persistent'] for r in out['refs'])} persistent: named by an NPC package)")
    for k, v in sorted(by_kind.items()):
        print(f"  {k} -> {TEMPLATES[k][1]}: {', '.join(v)}")
    for s in out["skipped"]:
        print("  skipped: " + s)
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
