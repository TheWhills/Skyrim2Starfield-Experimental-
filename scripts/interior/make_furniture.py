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
(2026-11-09, CRAFTING; --no-crafting keeps them statics): Skyrim's cooking pots become a copy of Starfield's
invisible galley workbench (AnimFurnGalleyWorkbench + WorkbenchCookingKeyword, so E may open Starfield's cooking menu)
with the pot's model, alchemy labs the chem bench, the enchanter / forge / smelter the industrial bench (no script; the
research bench has one), the grindstone the weapon bench, the armor table the armor bench, the anvil the hammering
marker, the tanning rack the wall-wipe marker. Markers: the template's (Skyrim's crafting markers sit at the origin and its
animations do the stand-off; 2026-11-09, in game: Skyrim's put the player inside the lab, no menu). Quest furniture stays.
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
    # crafting stations (owner's survey 2026-11-08; Starfield keywords in the comments)
    "cook": ("000EFC6F", "Invisible_GalleyWorkbench01"),           # AnimFurnGalleyWorkbench, WorkbenchCookingKeyword
    "alchemy": ("002B6A61", "WorkbenchChem"),                      # AnimFurnPharmaWorkbench, chem lab recipes
    "workbench": ("001F50AD", "WorkbenchIndustrial"),              # AnimFurnIndustrialWorkbench (enchanter, forge,
                                                                   # smelter); WorkbenchResearch has a script
    "weapon_bench": ("002B6A63", "WorkbenchWeapon"),               # AnimFurnWeaponWorkbench (grindstone)
    "armor_bench": ("002B6A62", "WorkbenchArmor"),                 # AnimFurnArmorWorkbench (armor table)
    "scrape": ("0003C420", "NPCStanding_WipeWall"),                # AnimFurnStanding_WipeWall (tanning rack)
}
SPECIAL = {"bartender", "lean_counter", "lean_table", "hammer", "sweep", "arms_crossed", "browse", "arms_front", "stand",
           "scrape",
           # crafting stations (2026-11-09, owner: E on our alchemy lab put the player inside it facing away, no menu;
           # Starfield's own chem bench, same record but its own marker, worked): Skyrim's crafting NIFs all hold one
           # marker at the origin, heading 0, entry Behind (owner's furniture survey: cooking pot, alchemy lab and
           # tabletop, enchanter): Skyrim's crafting animations do the stand-off themselves. Starfield's benches stand
           # the player in front (WorkbenchChem: 0, -0.728, 0, every side), so they keep the template's markers.
           "cook", "alchemy", "workbench", "weapon_bench", "armor_bench"}
CRAFT_KINDS = {"cook", "alchemy", "workbench", "weapon_bench", "armor_bench"}   # still need their NIF (a real model)
# Skyrim crafting stations: keyword (lower case) or EditorID part -> kind
CRAFTING = [(("craftingcookpot", "issmallcookingpot", "cookingspit", "cookingpot"), "cook"),
            (("isalchemy", "wicraftingalchemy", "craftingalchemy"), "alchemy"),
            (("isenchanting", "wicraftingenchanting", "craftingenchanting"), "workbench"),
            (("craftingsmithingsharpeningwheel", "sharpeningwheel", "grindstone"), "weapon_bench"),
            (("craftingsmithingarmortable", "armortable"), "armor_bench"),
            (("craftingtanningrack", "tanningrack"), "scrape"),
            (("craftingsmithinganvil", "anvil"), "hammer"),
            (("craftingsmithingforge", "craftingsmelter", "forge", "smelter"), "workbench")]
# Skyrim idle-marker animations (IDLE EditorIDs, lower case) -> kind
IDLE_KINDS = [("sweep", "sweep"), ("armscrossed", "arms_crossed"), ("examine", "browse"), ("study", "browse"),
              ("warmhands", "arms_front")]
SIDES = {"Front": "Front", "Behind": "Rear", "Right": "Right", "Left": "Left", "Up": "Other"}


def crafting_kind(rec):
    """The kind of a Skyrim crafting station (CRAFTING: by keyword, else by a part of its EditorID), or None."""
    kw = {k.lower() for k in rec.get("keywords") or []}
    edid = (rec.get("edid") or "").lower()
    for keys, kind in CRAFTING:
        if kw & set(keys) or any(k in edid for k in keys):
            return kind
    return None


# Skyrim work / creature furniture whose markers are "Sit" but which is no seat (2026-11-13, owner's Riverwood build:
# once the persistent outdoor references came in, 16 dragon perches, mining spots, chopping blocks, buckets, a lever,
# the sawmill and wood piles all became Starfield canvas chairs). Left alone: a real model stays the exterior's static.
WORK_FURNITURE_RE = re.compile(r"dragon|perch|pickaxe|mining|woodchop|chopping|bucket|lever|sawmill|woodpile|"
                               r"resourceobject|oremine|orevein|fishing|butter|churn", re.I)


def kind_of(rec, crafting=True):
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
    craft = crafting_kind(rec)
    if craft is not None or (rec.get("bench_type") or 0) > 0:
        return craft if crafting else None      # --no-crafting: crafting stations stay statics
    anims = {m.get("anim") for m in rec.get("nif_markers") or [] if isinstance(m, dict)}
    anims |= {e["type"] for e in rec.get("entry_points") or []}
    if "Sleep" in anims or "Has Sleep Marker" in (rec.get("mnam") or {}).get("flags", []):
        return "bed"
    if "Lean" in anims:
        return "lean_counter"
    if "istable" in kw or "bench" in edid.lower():
        return "bench"
    if WORK_FURNITURE_RE.search(edid) or any(WORK_FURNITURE_RE.search(k) for k in kw):
        return None                                            # work / creature furniture: no Starfield match yet
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


# Skyrim's own animations on our furniture (docs/npc/furniture.md "Animations", 2026-11-13): kind -> animation set.
# A set is a keyword in S2SStances.esm (stance_plugin.FURNITURE_SETS) whose HumanRace entries put a folder of
# converted Skyrim clips first; the furniture carries the keyword (PluginSpike, "anim_keyword").
ANIM_SETS = {"chair": "Sit", "bench": "Sit"}


def anim_keyword_edid(anim_set: str) -> str:
    return f"S2S_AnimFurnSkyrim{anim_set}"


def add_anim_keywords(out, plugin_path, read_keywords=None):
    """Give each base whose kind has an animation set its keyword's FormKey from the animations plugin (S2SStances.esm):
    "anim_keyword" ("XXXXXX:S2SStances.esm"), "anim_set". Returns {set: count}; sets whose keyword the plugin lacks are
    reported under "missing"."""
    if read_keywords is None:
        from fo4sf import sfplugin

        def read_keywords(path):
            return {sfplugin.edid(r[2]): r[3] for r in sfplugin.records(path, [b"KYWD"]) if sfplugin.edid(r[2])}
    kws = {k.lower(): v for k, v in read_keywords(plugin_path).items()}
    name = re.split(r"[\\/]", plugin_path)[-1]           # a Windows path read anywhere
    done, missing = {}, set()
    for b in out["bases"].values():
        st = ANIM_SETS.get(b.get("kind"))
        if not st:
            continue
        fid = kws.get(anim_keyword_edid(st).lower())
        if fid is None:
            missing.add(st)
            continue
        b["anim_keyword"] = f"{fid & 0xFFFFFF:06X}:{name}"
        b["anim_set"] = st
        done[st] = done.get(st, 0) + 1
    if missing:
        done["missing"] = sorted(missing)
    return done


def add_bounds(out, convert_dir, bounds_of=None):
    """Object bounds (metres, [[min], [max]]) for each base with a converted model (the batch's convert/manifest.json):
    "bounds" in its furniture.json entry, which PluginSpike writes as the furniture's OBND. 2026-11-13 (owner, in game):
    with no bounds the Sit / Sleep prompt came up only when looking at the furniture's very centre. Returns how many."""
    man = os.path.join(convert_dir, "manifest.json")
    if not os.path.exists(man):
        return 0
    with open(man, encoding="utf-8") as fh:
        items = {i["source"].replace("/", "\\").lower(): i["model"] for i in json.load(fh).get("items", [])}
    if bounds_of is None:
        from fo4sf import skyrimlod

        def bounds_of(model):
            try:
                return skyrimlod.model_bounds(convert_dir, model)
            except (OSError, ValueError, struct.error):
                return None
    n = 0
    for b in out["bases"].values():
        if not b.get("model"):
            continue
        model = items.get(("meshes\\" + b["model"].lstrip("\\")).lower())
        bb = bounds_of(model) if model else None
        if bb:
            b["bounds"] = bb
            n += 1
    return n


def actor_targets(work):
    path = os.path.join(work, "actors.json")
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as fh:
        a = json.load(fh)
    return {v.get("source") for ac in a.get("actors", []) for p in ac.get("packages", [])
            for v in p.get("inputs", {}).values() if isinstance(v, dict) and v.get("type") == "near_reference"}


# Measured with furniture_standoff.py on each game's own placements (owner's run 2026-11-08): Skyrim's bar-lean markers
# stand 0.32 m (CounterBarLeanMarker, 24 refs) / 0.31 m (CounterLeanMarker) from the counter's face; Starfield's
# bartender / bartop-lean markers stand AT the face (0.00-0.03 m on straight counters; medians -0.12 / -0.04 with
# hits inside big L-shaped counter boxes). Counter tops are the same in both games: 1.10 m. So these markers move
# 0.30 m forward, onto the counter face where Starfield's animation expects it.
DEFAULT_SHIFT = {"bartender": [0.0, 0.30, 0.0], "lean_counter": [0.0, 0.30, 0.0]}


def parse_shift(items):
    """["bartender=0,0.2,0", ...] -> {kind: [dx, dy, dz]} (metres, in the furniture's own frame: +y = its facing),
    on top of DEFAULT_SHIFT (a kind given here replaces its default; "bartender=0,0,0" turns it off)."""
    out = {k: list(v) for k, v in DEFAULT_SHIFT.items()}
    for it in items or []:
        k, _, v = it.partition("=")
        xyz = [float(x) for x in v.split(",")]
        if k not in TEMPLATES or len(xyz) != 3:
            raise ValueError(f"--shift {it!r}: want <kind>=dx,dy,dz with kind one of {sorted(TEMPLATES)}")
        out[k] = xyz
    return out


EXTERIOR = "exterior"     # the "cell" of an outdoor reference (exterior_furniture.json; PluginSpike puts it outside)


def build(ix, cells, archives, marker_z="floor", targets=(), shift=None, crafting=True, ext_refs=()):
    cell_ids = {}
    for c in cells:
        f = ix.find_edid(b"CELL", c)
        if f is not None:
            cell_ids[f] = c
    refs, base_recs = [], {}

    def need_base(b):
        if b not in base_recs:
            rec = survey.base_record(ix, b, starfield=False)
            if archives is not None and rec.get("model") and rec["type"] == "FURN":
                data = archives.mesh(rec["model"])
                try:
                    rec["nif_markers"] = survey.nif_markers(data) if data is not None else []
                except (ValueError, struct.error):
                    rec["nif_markers"] = []
            base_recs[b] = rec
    for r, c in sorted(ix.cell_of.items()):
        if c not in cell_ids or ix.kind(r) != "REFR":
            continue
        b = survey.ref_base(ix, r)
        if b is None or ix.kind(b) not in ("FURN", "IDLM"):
            continue
        need_base(b)
        ref = next(((d, s) for s, d in ix.subs(r) if s == b"DATA" and len(d) >= 24), None)
        if ref is None:
            continue
        v = struct.unpack_from("<6f", ref[0])
        scale = next((struct.unpack_from("<f", d)[0] for s, d in ix.subs(r) if s == b"XSCL" and len(d) == 4), 1.0)
        key = skyrimrefs.formkey(r, "Skyrim.esm")
        refs.append({"formkey": key, "cell": cell_ids[c], "base": skyrimrefs.formkey(b, "Skyrim.esm"),
                     "pos": [round(x, 3) for x in v[:3]], "rot": [round(x, 5) for x in v[3:]], "scale": round(scale, 4),
                     "persistent": key in targets})
    # outdoor ones (2026-11-13, make_skyrim_interior.py batch --exterior-furniture): placed by PluginSpike in the
    # exterior world, in its persistent cell (always loaded; no Starfield cell lookup needed)
    for e in ext_refs:
        bk = e.get("base_formkey") or ""
        try:
            b = int(bk.split(":")[0], 16)
        except ValueError:
            continue
        if b not in ix.records or ix.kind(b) not in ("FURN", "IDLM"):
            continue
        need_base(b)
        refs.append({"formkey": e["formkey"], "cell": EXTERIOR, "base": skyrimrefs.formkey(b, "Skyrim.esm"),
                     "pos": [round(x, 3) for x in e["pos"]], "rot": [round(x, 5) for x in e["rot"]],
                     "scale": round(e.get("scale") or 1.0, 4), "persistent": True})
    bases, skipped = {}, []
    for b, rec in base_recs.items():
        kind = kind_of(rec, crafting)
        key = skyrimrefs.formkey(b, "Skyrim.esm")
        if kind is None:
            skipped.append(f"{rec['edid']}: no Starfield furniture for it (left as a static)")
            continue
        form, tedid = TEMPLATES[kind]
        nm = rec.get("nif_markers")
        if (kind not in SPECIAL or kind in CRAFT_KINDS) and not nm:
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
    ap.add_argument("--no-crafting", action="store_true",
                    help="leave crafting stations (cooking pots, alchemy, enchanting, smithing) as statics")
    ap.add_argument("--anim-plugin", help="S2SStances.esm (stance_plugin.py): chairs / benches get its Skyrim-animation "
                                          "keyword (docs/npc/furniture.md \"Animations\")")
    ap.add_argument("--no-exterior", action="store_true",
                    help="ignore <work>\\exterior_furniture.json (the outdoor furniture from batch --exterior-furniture)")
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
        ext_path = os.path.join(a.work, "exterior_furniture.json")
        ext_refs = []
        if os.path.exists(ext_path) and not a.no_exterior:
            with open(ext_path, encoding="utf-8") as fh:
                ext_refs = json.load(fh)["refs"]
        out = build(ix, cells, archives, a.marker_z, actor_targets(a.work), shift, not a.no_crafting, ext_refs)
    finally:
        ix.close()
    if a.anim_plugin:
        if os.path.exists(a.anim_plugin):
            got = add_anim_keywords(out, a.anim_plugin)
            print(f"Skyrim animation sets from {os.path.basename(a.anim_plugin)}: "
                  + (", ".join(f"{k} {v}" for k, v in got.items()) or "none"))
        else:
            print(f"--anim-plugin {a.anim_plugin}: not found (furniture keeps Starfield's animations)")
    nb = add_bounds(out, os.path.join(a.work, "convert"))
    if nb:
        print(f"object bounds from the converted models: {nb} bases")
    path = os.path.join(a.work, "furniture.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    by_kind = {}
    for b in out["bases"].values():
        n = sum(1 for r in out["refs"] if out["bases"].get(r["base"]) is b)
        by_kind.setdefault(b["kind"], []).append(f"{b['edid']} x{n}")
    n_out = sum(1 for r in out["refs"] if r["cell"] == EXTERIOR)
    if n_out:
        print(f"outdoors: {n_out} furniture references")
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
