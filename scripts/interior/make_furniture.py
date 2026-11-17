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
from typing import Optional

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
    # 2026-11-16 (owner, in game: Alvor stands by our forge and never uses it; the player's E on it does nothing, as
    # on Starfield's own chem bench placed in the inn on 2026-11-09). SfInspect (verified): WorkbenchIndustrial has no
    # FurnitureClassWork keyword (NPCs' work sandboxing uses furniture of that class: the tanner, Embry's sweeping and
    # Orgnar's bar, on such templates, work in game), while NPCRepair_ToolStanding_Hammer is IgnoredBySandbox. So the
    # forge and the grindstone, which play our Skyrim clips, become NPC work furniture on the wall-wipe template
    # (FurnitureClassWork, not ignored by sandbox; the tanning rack's): Starfield's crafting menu is lost (it did not
    # open anyway); Skyrim's animations, props and spot are kept
    # 2026-11-16 (owner's A/B, verified: Hilde tans by herself once the forge is not on her rack's template): two of
    # our sets on one Starfield template stop NPCs walking into either, so the forge has one of its own: the welder,
    # standing NPC work furniture (FurnitureClassWork, AnimFurnWelder; work_templates.py, furniture_anim_survey)
    "forge": ("0025B9D1", "NPCWelder"),                            # Skyrim's blacksmith forge (Forge set)
    # 2026-11-16 (owner: "Let's add the grindstone now ... so everything he can do is added"): a template of its own,
    # the standing repair spot (FurnitureClassWork, AnimFurnRepair_ToolStanding, enter / exit through geometry;
    # furniture\repair_toolstanding: Enter / EnterInstant / Exit / QuickExit, Idle, 9 flavors), FurnitureSpecial added
    "grindstone": ("0007BDAA", "NPCRepairImpactWrench_Standing"),  # Skyrim's sharpening wheel (Grindstone set)
}
SPECIAL = {"bartender", "lean_counter", "lean_table", "hammer", "sweep", "arms_crossed", "browse", "arms_front", "stand",
           "scrape", "forge", "grindstone",
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
            # (removed 15:02, back 21:19 on a template of its own: owner, "Let's add the grindstone now")
            (("craftingsmithingsharpeningwheel", "sharpeningwheel", "grindstone"), "grindstone"),
            (("craftingsmithingarmortable", "armortable"), "armor_bench"),
            (("craftingtanningrack", "tanningrack"), "scrape"),
            (("craftingsmithinganvil", "anvil"), "hammer"),
            (("craftingsmelter", "issmelter", "smelter"), "workbench"),
            (("craftingsmithingforge", "isblacksmithforge", "forge"), "forge")]
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


def markers(rec, kind, marker_z, special_ok=False):
    """Per Skyrim marker: offset (m), rotation (degrees), entry sides; [] = use the template's SNAM unchanged.
    special_ok: also for SPECIAL kinds (Skyrim's markers, for furniture playing our Skyrim clips: skyrim_markers)."""
    if kind in SPECIAL and not special_ok:
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
# Which Skyrim furniture plays which of our animation sets (furniture_anim_pack.SETS): (kinds, EditorID regex or None,
# set), first match. The lean markers share one Starfield template (lean_counter) but Skyrim gives each its own clips.
ANIM_SET_RULES = (
    (("chair", "bench"), None, "Sit"),
    (("lean_counter",), r"wall", "WallLean"),
    (("lean_counter",), r"rail", "RailLean"),
    (("lean_counter", "bartender"), r"counter", "Counter"),
    (("lean_table",), None, "LeanTable"),
    (("sweep",), None, "Sweep"),
    (("alchemy",), None, "Alchemy"),
    (("workbench",), r"enchant", "Enchant"),
    (("cook",), None, "Cook"),
    (("scrape",), r"tanning", "Tanning"),
    (("forge",), None, "Forge"),
    (("grindstone",), None, "Grindstone"),
)
# Sets whose Skyrim clips stand at Skyrim's own marker even on a crafting station (whose Starfield template's marker
# is kept otherwise): the forge's sequence (fire, anvil, trough) is laid out around Skyrim's forge marker, the clips
# carry no root motion, and its spot is the marker's (2026-11-16)
# 2026-11-16 (owner, in game): forced in (cf "Actor.SnapIntoInteraction") Alvor plays the whole forge sequence, but on his
# work schedule he never uses the forge: "he seems to hit a weird walk before he goes back to his neutral position"
# (an approach that fails), while Hilde, her chair disabled, leans on her rail. Skyrim's crafting markers allow one
# side only (Behind), and the forge's own model (pit, trough, anvil) stands around that spot: these sets' spots may be
# entered from every side, so the AI can take whichever approach it can path (supported hypothesis, owner's test).
ANY_SIDE_SETS = {"Forge", "Tanning", "Grindstone"}
# 2026-11-16 (owner, in game, energy fixed, invisible-marker A/B too): Alvor never chooses the forge or his tanning
# rack, Hilde her rack only when nothing else is left; forced in, both play. Starfield's bartender furniture (Orgnar
# uses ours) carries FurnitureSpecial and so do Skyrim's crafting stations, for the sandbox's "Allow Special Furniture"
# (on in Alvor's and Hilde's packages); the wall-wipe and welder templates do not (supported hypothesis, owner's test)
SPECIAL_SETS = {"Forge", "Tanning", "Grindstone"}
ALL_SIDES = ["Front", "Rear", "Left", "Right"]
SKYRIM_SPOT_SETS = {"Forge", "Grindstone"}           # the wheel's clips stand at Skyrim's wheel marker too
ANIM_SETS = sorted({st for _k, _e, st in ANIM_SET_RULES})


def anim_set_for(base) -> Optional[str]:
    """The animation set for a furniture base {kind, edid}, or None (Starfield's own animations)."""
    kind, edid = base.get("kind"), base.get("edid") or ""
    for kinds, rx, st in ANIM_SET_RULES:
        if kind in kinds and (rx is None or re.search(rx, edid, re.I)):
            return st
    return None


# The spot an actor takes when the Skyrim base has no marker NIF (an idle marker, IDLM): the reference itself, facing
# its heading, as Skyrim plays idle markers.
AT_THE_REFERENCE = [{"offset_m": [0.0, 0.0, 0.0], "rot_deg": 0.0, "entry": ["Front"]}]


def skyrim_markers(rec, kind, marker_z):
    """Skyrim's own spots for a base, whatever its kind: its NIF's furniture markers, or the reference itself
    (AT_THE_REFERENCE) for one without. Used in place of a SPECIAL template's markers when the base plays our Skyrim
    clips (add_anim_keywords): 2026-11-15 (owner, in game): Hilde leaned facing along the walkway instead of at the
    rail, Hod stood ~0.3 m off the post he leans on; both had the bartop-lean template's marker (another stand-off and
    facing), while chairs and benches, on Skyrim's markers, sit right."""
    return markers(rec, kind, marker_z, special_ok=True) or [dict(m) for m in AT_THE_REFERENCE]


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
        st = anim_set_for(b)
        if not st:
            continue
        fid = kws.get(anim_keyword_edid(st).lower())
        if fid is None:
            missing.add(st)
            continue
        b["anim_keyword"] = f"{fid & 0xFFFFFF:06X}:{name}"
        b["anim_set"] = st
        if st in SKYRIM_SPOT_SETS and b.get("skyrim_markers"):
            b["markers"] = b["skyrim_markers"]
        elif b.get("skyrim_markers") and not b.get("markers") and b.get("kind") not in CRAFT_KINDS:
            b["markers"] = b["skyrim_markers"]           # our Skyrim clips stand at Skyrim's spot
            # ... without DEFAULT_SHIFT, measured for Starfield's bar-lean animation at the counter face (2026-11-15,
            # owner: Hod ~0.3 m in front of his post, Hilde ~0.3 m back from the rail: the +0.30 m along the
            # furniture's +y, ahead of Hod (facing 0) and behind Hilde (facing 180)). A shift given on the command
            # line (different from the default) stays.
            if b.get("shift_m") is not None and list(b["shift_m"]) == list(DEFAULT_SHIFT.get(b.get("kind"), [])):
                del b["shift_m"]
        if st in SPECIAL_SETS:
            b["extra_keywords"] = ["FurnitureSpecial"]
        if st in ANY_SIDE_SETS and b.get("markers"):
            b["markers"] = [dict(m, entry=list(ALL_SIDES)) for m in b["markers"]]
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


# Beds (2026-11-15, owner, in game: NPCs sleep sideways across Skyrim's beds). Skyrim's bed markers and the template
# cot's (FoundCanvasCot01) read the same: rotation 0, entered from the left / right (owner's furniture survey), and
# Skyrim's double bed puts its two sleepers side by side along x, so its beds run along the marker's y; Starfield's
# sleep animation lies across that on our markers, i.e. along the marker's x. A quarter turn: in the owner's screenshot
# the head pointed at the wall with the pillow to the left, a quarter turn counter-clockwise seen from above, -90 in
# Bethesda's clockwise z (supported; if the head ends at the foot, --turn bed=90).
DEFAULT_TURN = {"bed": -90.0}


def parse_turn(items):
    """["bed=90", ...] -> {kind: degrees} on top of DEFAULT_TURN (a kind given replaces its default; "bed=0" off)."""
    out = dict(DEFAULT_TURN)
    for it in items or []:
        k, _, v = it.partition("=")
        if k not in TEMPLATES:
            raise ValueError(f"--turn {it!r}: want <kind>=degrees with kind one of {sorted(TEMPLATES)}")
        out[k] = float(v)
    return out


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


def build(ix, cells, archives, marker_z="floor", targets=(), shift=None, crafting=True, ext_refs=(), turn=None,
          skip_kinds=()):
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
        if kind in skip_kinds:                 # --skip-kind (A/B, 2026-11-16: the tanning rack without the forge)
            skipped.append(f"{rec['edid']}: {kind} skipped (--skip-kind; left as a static)")
            continue
        form, tedid = TEMPLATES[kind]
        nm = rec.get("nif_markers")
        if (kind not in SPECIAL or kind in CRAFT_KINDS) and not nm:
            skipped.append(f"{rec['edid']}: {kind} but no marker positions in its NIF (no --skyrim-data?); left as a static")
            continue
        real_model = rec["type"] == "FURN" and not rec["is_marker"]
        bases[key] = {"edid": rec["edid"], "type": rec["type"], "kind": kind, "template": form, "template_edid": tedid,
                      "model": rec.get("model") if real_model else None, "markers": markers(rec, kind, marker_z)}
        if (kind in SPECIAL and kind not in CRAFT_KINDS) or anim_set_for(bases[key]) in SKYRIM_SPOT_SETS:
            bases[key]["skyrim_markers"] = skyrim_markers(rec, kind, marker_z)
        if (shift or {}).get(kind):
            bases[key]["shift_m"] = shift[kind]
        if (turn or {}).get(kind):
            for m in bases[key]["markers"]:
                m["rot_deg"] = round((m["rot_deg"] + turn[kind] + 180.0) % 360.0 - 180.0, 1) + 0.0
            bases[key]["turn_deg"] = turn[kind]
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
    ap.add_argument("--turn", action="append", default=[], metavar="KIND=DEG",
                    help="turn every marker of a kind (degrees, Bethesda's clockwise z) on top of DEFAULT_TURN "
                         "(bed -90: Starfield's sleep animation lies across Skyrim's beds); bed=0 turns it off")
    ap.add_argument("--skip-kind", action="append", default=[], metavar="KIND",
                    help="leave this kind as statics (repeatable; A/B: 2026-11-16, owner: the tanning rack was used "
                         "before the forge joined its template, so a build without the forge)")
    ap.add_argument("--no-crafting", action="store_true",
                    help="leave crafting stations (cooking pots, alchemy, enchanting, smithing) as statics")
    ap.add_argument("--anim-plugin", help="S2SStances.esm (stance_plugin.py): chairs / benches get its Skyrim-animation "
                                          "keyword (docs/npc/furniture.md \"Animations\")")
    ap.add_argument("--no-exterior", action="store_true",
                    help="ignore <work>\\exterior_furniture.json (the outdoor furniture from batch --exterior-furniture)")
    a = ap.parse_args(argv)
    try:
        shift = parse_shift(a.shift)
        turn = parse_turn(a.turn)
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
        out = build(ix, cells, archives, a.marker_z, actor_targets(a.work), shift, not a.no_crafting, ext_refs, turn,
                    set(a.skip_kind))
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
