"""A Skyrim NPC's AI packages as Starfield packages, and the NPC placed in its converted interior (docs/npc/schedules.md).

    python -I scripts\\npc\\make_schedule.py --skyrim "<Skyrim SE>\\Data\\Skyrim.esm" --starfield "<Starfield>\\Data\\Starfield.esm" ^
        --npc Orgnar --work C:\\Modding\\work\\s2s\\riverwood_doors --faces "<S2S Face Test>\\faces.json"

Writes <work>\\actors.json, which PluginSpike reads (ACTORS=<that file>) while it builds the interiors into FO4Port.esm.
Per NPC: its name, sex, the Skyrim cell (must be one of the batch's: <work>\\cells.txt lists them), its Skyrim position /
rotation (units, as cell.json), the vanilla Starfield NPC to copy (the template face_fit.py used for that NPC, from
faces.json; else one of the same sex there), and its packages in order. Each package: same schedule; the Starfield
package template for the Skyrim one (SKY_TO_SF, else the same EditorID); and the inputs that carry over, matched by input
NAME between the two templates (a template lists its inputs as UNAM index + BNAM name; a package's values come in the
order of its own UNAM indexes). Locations: "near reference" keeps the Skyrim reference (PluginSpike points at our placed
copy, or places a Starfield XMarker at its spot when we did not place it) with the radius in metres; "in cell" becomes
our cell. Inputs Starfield's template has and Skyrim's does not keep the values of the vanilla package PluginSpike copies.
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

from fo4sf import packages, skyrimnpc, skyrimrefs  # noqa: E402

U = 70.0
FACE_PLUGIN = "S2SFaceTest.esm"           # face_fit.py --test-plugin's output, next to its faces.json
# Skyrim package templates -> Starfield's (owner's package_survey.py 2026-11-08: Starfield has Sandbox (577 uses),
# Travel, Sit, Sleep, ...; Skyrim's SandboxWorking = travel, unlock doors, sandbox: Starfield's Sandbox procedure list)
SKY_TO_SF = {"sandboxworking": "Sandbox", "sandbox": "Sandbox", "sleep": "Sleep", "travel": "Travel", "sit": "Sit",
             "eat": "Sandbox", "sandboxworkingmultilocation": "Sandbox", "carryanddropitem": "Sandbox"}
# 2026-11-15 (owner: Faendal stays inside all day; his actors.json: FaendalWork7x12, SandboxWorkingMultiLocation, and
# three CarryFirewood runs, CarryAndDropItem, left out for want of a Starfield template): Starfield has no
# multi-location sandbox or carry procedure, so these become a Sandbox at their FIRST location input (the work spot /
# the woodpile); later location inputs are skipped (noted).
FIRST_LOCATION_ONLY = {"sandboxworkingmultilocation", "carryanddropitem"}
# Skyrim input -> Starfield input of another name, per Skyrim template (normalized names). 2026-11-17 (owner's build
# log: every Eat package listed "Eat Location (Location)" as kept vanilla, so FaendalEatStump / LucanRiverwoodEatInn
# ran at the copied vanilla package's location, not the stump / the inn; FaendalCarryFirewood had no input at all:
# its Carry Start is a reference, not a Location). Until carry-and-drop is rebuilt, its sandbox is at the carry start
# (the woodpile), CARRY_RADIUS_M around it (an assumption: Skyrim's carry has no radius).
INPUT_ALIAS = {"eat": {"eatlocation": "location"}, "carryanddropitem": {"carrystart": "location"}}
CARRY_RADIUS_M = 2.0
# inputs set on the Starfield side whatever Skyrim had (by normalized Starfield input name): Starfield has no Eat
# template; its NPCs eat while sandboxing (Allow Eating / Allow Sitting)
FORCE = {"eat": {"alloweating": True, "allowsitting": True}}
# until furniture / idle markers are converted (beds, chairs, the bar-lean marker are statics in our interiors) a sandbox
# whose Skyrim inputs allow only furniture / idle markers has nothing to do inside its radius, and the NPC leaves it
# (owner 2026-11-08: Orgnar stood behind the bar for a moment, then walked off): let it wander inside the radius
NO_FURNITURE = {"allowwandering": True}
# Skyrim's sandbox Energy is 0-100 (vanilla 50), and so is Starfield's: 2026-11-16 (owner's energy_survey.py on
# Starfield.esm, verified): 519 of its 577 Sandbox packages use 50, the rest 0-60 (a few 200 / 500); every Sleep and
# SandboxAndKeepEyeOn package 50. The earlier x 0.01 (from ShopkeeperSchedules.esm, a mod's 0.1-0.8) gave our NPCs 0.5,
# next to no energy: Hilde kept her chair, Alvor his standing spot (owner, in game). Kept as is, within 0-100.
# 2026-11-17 (owner: "let's do as the player sees it most of the game, with a note that the goal eventually is to
# convert them all after other aspects of the conversion are fleshed out"): a package with conditions is converted
# when its conditions hold in Riverwood as a player finds it after arriving - the arrival quests finished, every other
# quest not started - and left out (noted) when they fail there, depend on play (time, weather, distance: Starfield
# conditions not written yet) or on a script's state. Quest-driven packages come back when quests are converted.
SETTLED_QUESTS = ("MQ102", "MQ102A", "DialogueRiverwoodIntroScene", "DialogueRiverwood_Revised")
ENERGY_SCALE = 1.0
ENERGY_MAX = 100.0


def sf_schedule(s):
    """A Skyrim PSDT schedule as Starfield's: xEdit (wbDefinitionsCommon wbPackagePSDTMonthValueToStr) stores the month
    one higher in records of form version >= 122 (Starfield's are 582): Skyrim's -1 "any" is Starfield's 0, and a -1
    written into a Starfield package is no month at all (verified against ShopkeeperSchedules.esm: all 297 packages,
    the always-on ones too, have month 0). Day of week, date, hour, minute, duration carry over."""
    if not s:
        return s
    out = dict(s)
    out["month"] = s["month"] + 1 if s["month"] >= -1 else 0
    return out


def norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def value_indexes(p):
    """The UNAM index of each data input value of a parsed package / template, in value order."""
    return [n["index"] for n in p["input_names"] if n["name"] is None][:len(p["inputs"])]


def definitions(p):
    """{UNAM index: name} of a template's inputs."""
    return {n["index"]: n["name"] for n in p["input_names"] if n["name"] is not None}


def ref_place(ix, fid):
    """(position units, rotation radians) of a placed reference."""
    d = next((d for s, d in ix.subs(fid) if s == b"DATA" and len(d) >= 24), None)
    if d is None:
        return None, None
    v = struct.unpack_from("<6f", d)
    return [round(c, 3) for c in v[:3]], [round(c, 5) for c in v[3:]]


def exterior_cells(sky, formids_path):
    """{Skyrim exterior CELL FormID} holding at least one reference the installed exterior converted (its formids.json
    "refs": Skyrim ref key "XXXXXX:Skyrim.esm" -> our FormID): the converted outdoors, where a package location may
    point (2026-11-12, owner: "can we convert outside stuff, so they can walk around Riverwood, go inside and out")."""
    with open(formids_path, encoding="utf-8") as fh:
        refs = json.load(fh).get("refs") or {}
    out = set()
    for k in refs:
        m = re.match(r"^([0-9A-Fa-f]{6}):Skyrim\.esm$", k)
        if m:
            c = sky.cell_of.get(int(m.group(1), 16))
            if c is not None:
                out.add(c)
    return out


def moment_world(sky, skyrim_path, moment="settled"):
    """skyrimdialog.World of a new game (quests, globals, form lists from Skyrim.esm); 'settled': SETTLED_QUESTS
    finished. sky: a packages.Index of the same file (for the quests' FormIDs)."""
    from fo4sf import skyrimdialog as SD
    w = SD.world_from(skyrim_path)
    if moment == "settled":
        w.settled = {f for f in (sky.find_edid(b"QUST", q) for q in SETTLED_QUESTS) if f is not None}
    return w


def package_ctda(sky, pack_fid) -> list:
    """The package's own conditions (CTDA before its data inputs), parsed (skyrimdialog.parse_condition)."""
    from fo4sf import skyrimdialog as SD
    out = []
    for sig, d in sky.subs(pack_fid):
        if sig in (b"PKCU", b"ANAM", b"PLDT", b"PTDA"):
            break
        if sig == b"CTDA":
            c = SD.parse_condition(d)
            if c:
                out.append(c)
    return out


def condition_verdict(sky, pack_fid, world, speaker):
    """('keep' | 'ambient' | 'drop', reasons) of a package's conditions in the world (skyrimdialog.verdict)."""
    from fo4sf import skyrimdialog as SD
    return SD.verdict({"conditions": package_ctda(sky, pack_fid)}, speaker or {}, world)


def convert_package(sky, sf_tpls, pack_fid, cell_names, notes, keep_conditioned=False, keep_furniture_only=False,
                    ext_cells=None, world=None, speaker=None):
    p = packages.parse_pack(sky.subs(pack_fid))
    if not keep_conditioned and p["owner_quest"]:
        notes.append(f"{p['edid']}: left out (quest / conditions decide when Skyrim runs it: owned by a quest)")
        return None
    if not keep_conditioned and p["conditions"]:
        if world is None:
            notes.append(f"{p['edid']}: left out (quest / conditions decide when Skyrim runs it: "
                         f"{p['conditions']} conditions)")
            return None
        v, why = condition_verdict(sky, pack_fid, world, speaker)
        if v == "keep":
            notes.append(f"{p['edid']}: its {p['conditions']} conditions hold in settled Riverwood; converted without "
                         f"them")
        else:
            kinds = " ".join(why)
            what = ("needs its script" if " script" in kinds else
                    "needs Starfield conditions (time / weather / distance), not written yet" if v == "ambient" else
                    "does not run in settled Riverwood (quest-only or intro)")
            notes.append(f"{p['edid']}: left out, {what} ({'; '.join(why)})")
            return None
    tpl = packages.parse_pack(sky.subs(p["template"])) if p["template"] else None
    tname = (tpl or {}).get("edid") or ""
    sf_name = SKY_TO_SF.get(tname.lower(), tname)
    sf = sf_tpls.get(sf_name.lower())
    if sf is None:
        notes.append(f"{p['edid']}: Skyrim template {tname!r} has no Starfield template {sf_name!r}; left out")
        return None
    sky_names = definitions(tpl) if tpl else {}
    sf_names = definitions(sf["pack"])
    sf_values = value_indexes(sf["pack"])
    by_name = {}
    for i in sf_values:
        by_name.setdefault(norm(sf_names.get(i)), i)
    inputs, skipped, drop = {}, [], None
    first_loc = tname.lower() in FIRST_LOCATION_ONLY
    alias = INPUT_ALIAS.get(tname.lower(), {})
    for k, (inp, idx) in enumerate(zip(p["inputs"], value_indexes(p))):
        name = sky_names.get(idx)
        target = by_name.get(alias.get(norm(name), norm(name)))
        v = inp["value"]
        if (alias.get(norm(name)) == "location" and (inp["type"] or "").lower() == "singleref"
                and isinstance(v, dict) and v.get("type") == 0 and v.get("value")):
            # a specific reference standing in for a location (carry start): near that reference
            inp = dict(inp, type="Location")
            v = {"type": 0, "value": v["value"], "radius": CARRY_RADIUS_M * U, "type_name": "Near reference"}
        if first_loc and inp["type"].lower() == "location":
            if "location" not in by_name or str(by_name["location"]) in inputs:
                skipped.append(f"{name or idx} (Location: only the first is kept)")
                continue
            target = by_name["location"]
        if target is None:
            skipped.append(f"{name or idx} ({inp['type']})")
            continue
        t = inp["type"].lower()
        if t == "bool":
            inputs[str(target)] = {"kind": "bool", "value": bool(v), "skyrim": name}
        elif t == "float":
            f = float(v)
            if norm(name) == "energy":
                f = round(min(max(f * ENERGY_SCALE, 0.0), ENERGY_MAX), 4)
            inputs[str(target)] = {"kind": "float", "value": f, "skyrim": name}
        elif t in ("int", "integer"):
            inputs[str(target)] = {"kind": "int", "value": int(v), "skyrim": name}
        elif t == "location" and isinstance(v, dict):
            loc = {"kind": "location", "radius_m": round((v.get("radius") or 0) / U, 3), "skyrim": name}
            if v["type"] == 0 and v["value"]:
                pos, rot = ref_place(sky, v["value"])
                info = sky.name_of(v["value"])
                where = (info.get("cell") or {}).get("edid")
                if where not in cell_names:
                    if ext_cells and sky.cell_of.get(v["value"]) in ext_cells and pos is not None:
                        # outdoors, in the converted exterior: PluginSpike places a persistent XMarker there (EXTERIOR_DIR)
                        loc.update(type="near_exterior_reference", source=skyrimrefs.formkey(v["value"], "Skyrim.esm"),
                                   pos=pos, rot=rot, base=(info.get("base") or {}).get("edid"), cell="exterior")
                        inputs[str(target)] = loc
                        continue
                    drop = f"its location {name} is near a reference in {where or 'the exterior'}, outside the batch"
                    continue
                loc.update(type="near_reference", source=skyrimrefs.formkey(v["value"], "Skyrim.esm"), pos=pos, rot=rot,
                           base=(info.get("base") or {}).get("edid"),
                           cell=(info.get("cell") or {}).get("edid"))
            elif v["type"] == 1 and v["value"]:
                e = sky.edid(v["value"])
                if e not in cell_names:
                    drop = f"its location {name} is the cell {e}, outside the batch"
                    continue
                loc.update(type="in_cell", cell=e)
            elif v["type"] in (2, 3, 12):
                loc.update(type={2: "near_package_start", 3: "near_editor_location", 12: "near_self"}[v["type"]])
            else:
                notes.append(f"{p['edid']}: location type {v['type_name']} not translated yet; vanilla value kept")
                continue
            inputs[str(target)] = loc
        else:
            skipped.append(f"{name or idx} ({inp['type']})")
    if drop:
        notes.append(f"{p['edid']}: left out: {drop} (NPCs outside the converted interiors come later)")
        return None
    extra = dict(FORCE.get(tname.lower(), {}))
    if sf_name.lower().startswith("sandbox") and not keep_furniture_only:
        extra.update(NO_FURNITURE)
    for k, val in extra.items():
        if k in by_name:
            inputs[str(by_name[k])] = {"kind": "bool", "value": val, "skyrim": f"({sf_names.get(by_name[k])} set)"}
    if skipped:
        notes.append(f"{p['edid']}: inputs without a Starfield counterpart kept vanilla: {skipped}")
    return {"edid": "S2S_" + p["edid"], "skyrim": p["edid"], "schedule": sf_schedule(p["schedule"]),
            "skyrim_schedule": p["schedule"], "speed": p["speed"],
            "skyrim_template": tname, "sf_template": sf_name, "sf_template_form": f"{sf['form']:08X}",
            "conditions_dropped": p["conditions"], "inputs": inputs}


def target_index(sf_tpl):
    """The UNAM index of a Starfield template's first single-reference input (Sit: the furniture to use), or None."""
    for idx, inp in zip(value_indexes(sf_tpl["pack"]), sf_tpl["pack"]["inputs"]):
        if (inp.get("type") or "").lower() in ("singleref", "target"):
            return idx
    return None


def parse_sit_at(specs) -> dict:
    """--sit-at NPC=SKYRIMREF:HOUR:MINUTES ... -> {npc lower: [(ref formkey, hour, minutes)]}."""
    out = {}
    for spec in specs or []:
        npc, _, rest = spec.partition("=")
        parts = rest.split(":")
        if not npc or len(parts) != 3:
            raise ValueError(f"--sit-at {spec!r}: expected NPC=SKYRIMREF:HOUR:MINUTES, e.g. Alvor=0D6987:8:720")
        ref = parts[0].upper().rjust(6, "0")
        out.setdefault(npc.strip().lower(), []).append((f"{ref}:Skyrim.esm", int(parts[1]), int(parts[2])))
    return out


def location_indexes(sf_tpl) -> list:
    """The UNAM indexes of a Starfield template's Location inputs."""
    return [idx for idx, inp in zip(value_indexes(sf_tpl["pack"]), sf_tpl["pack"]["inputs"])
            if (inp.get("type") or "").lower() == "location"]


def sit_package(npc_edid, ref, hour, minutes, sf_tpl, n=0, place=None):
    """A package of Starfield's Sit template that sends the NPC into one furniture reference for a time of day
    (2026-11-16, work_spot_usage.py on Starfield.esm: its own NPCs reach work spots through Sit packages naming the
    reference, e.g. UC07_Gel_Sit_Weld on a welder, and linked references; a sandbox only places Alvor in his forge
    during a passtime). PluginSpike resolves the Skyrim reference to the furniture it places for it."""
    idx = target_index(sf_tpl)
    if idx is None:
        return None
    inputs = {str(idx): {"kind": "ref", "source": ref, "skyrim": "(--sit-at)"}}
    # 2026-11-16 (owner, in game: with the Sit package running Alvor stood wherever he was put and never set off): the
    # copied vanilla package keeps its own Location inputs (somewhere in its own world) unless they are set; every one
    # goes to the furniture's spot (place: a location input as convert_package writes them)
    if place:
        for li in location_indexes(sf_tpl):
            inputs[str(li)] = dict(place, skyrim="(--sit-at place)")
    return {"edid": f"S2S_{npc_edid}SitAt{ref.split(':')[0]}" + (f"_{n}" if n else ""), "skyrim": None,
            "schedule": {"month": 0, "day_of_week": -1, "date": 0, "hour": hour, "minute": -1, "duration_min": minutes},
            "skyrim_schedule": None, "speed": 0, "skyrim_template": None, "sf_template": "Sit",
            "sf_template_form": f"{sf_tpl['form']:08X}", "conditions_dropped": 0,
            "inputs": inputs}


def load_sf_templates(path):
    """({template EditorID lower: {form, pack}}, XMarker STAT FormID or None) of Starfield.esm."""
    ix = packages.Index(path)
    out, xmarker = {}, None
    try:
        for fid in ix.by_type.get(b"PACK", []):
            p = packages.parse_pack(ix.subs(fid), starfield=True)
            if p["type"] == packages.TEMPLATE and p["edid"]:
                out.setdefault(p["edid"].lower(), {"form": fid, "pack": p})
        if ix.kind(0x3B) == "STAT" and (ix.edid(0x3B) or "").lower() == "xmarker":
            xmarker = 0x3B
        else:
            xmarker = ix.find_edid(b"STAT", "XMarker")
    finally:
        ix.close()
    return out, xmarker


def pick_template(faces, edid, female):
    rows = [r for r in (faces or {}).get("npcs", []) if isinstance(r.get("test_npc"), dict)
            and r["test_npc"].get("template_form_id")]
    for r in rows:
        if r.get("edid", "").lower() == edid.lower():
            return r["test_npc"]["template_form_id"], f"faces.json: {edid}'s own template"
    for r in rows:
        if bool(r.get("female")) == female:
            return r["test_npc"]["template_form_id"], f"faces.json: {r.get('edid')}'s template (same sex)"
    return None, "no template in faces.json"


def face_npc(faces, edid, faces_path, plugin=""):
    """The NPC's own face-test NPC (face_fit.py --test-plugin: face, Skyrim hair, outfit, name, voice type and greetings):
    {"plugin", "path", "form_id"}; None when faces.json has no test NPC of its own for it."""
    for r in (faces or {}).get("npcs", []):
        t = r.get("test_npc")
        if r.get("edid", "").lower() == edid.lower() and isinstance(t, dict) and t.get("form_id"):
            path = plugin or os.path.join(os.path.dirname(os.path.abspath(faces_path)), FACE_PLUGIN)
            return {"plugin": os.path.basename(path), "path": path, "form_id": t["form_id"]}
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--npc", action="append", required=True)
    ap.add_argument("--work", required=True, help="the interior batch work folder (cells.txt; actors.json is written there)")
    ap.add_argument("--faces", default="", help="face_fit.py's faces.json (vanilla template NPC per test NPC)")
    ap.add_argument("--moment", choices=("settled", "start", "none"), default="settled",
                    help="which moment of Skyrim conditioned packages are read at: settled (default: the Riverwood "
                         "arrival done, other quests not started), start (a new game), none (leave them all out)")
    ap.add_argument("--keep-conditioned", action="store_true",
                    help="keep packages with conditions / an owner quest (their conditions are not converted)")
    ap.add_argument("--keep-furniture-only", action="store_true",
                    help="keep Skyrim's Allow Wandering off on sandboxes (only once furniture / idle markers are converted)")
    ap.add_argument("--template-npc", default="", help="Starfield NPC FormID to copy instead (hex)")
    ap.add_argument("--face-plugin", default="", help="the face-test plugin (default: S2SFaceTest.esm next to --faces)")
    ap.add_argument("--exterior", default="", help="the installed exterior's staging folder (formids.json): package "
                                                   "locations near references in its converted cells are kept (NPCs "
                                                   "go outdoors); without it they are left out as before")
    ap.add_argument("--sit-at", action="append", default=[], metavar="NPC=SKYRIMREF:HOUR:MINUTES",
                    help="also give the NPC a Starfield Sit package into this Skyrim furniture reference for that time, "
                         "ahead of its own packages (A/B, 2026-11-16: does Alvor walk into his forge when a package "
                         "names it?), e.g. Alvor=0D6987:8:720")
    a = ap.parse_args(argv)
    sit_at = parse_sit_at(a.sit_at)
    notes = []
    cells_txt = os.path.join(a.work, "cells.txt")
    cell_names = set()
    if os.path.exists(cells_txt):
        with open(cells_txt, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    with open(line, encoding="utf-8") as c:
                        cell_names.add(json.load(c)["cell"])
    faces = None
    if a.faces:
        with open(a.faces, encoding="utf-8") as fh:
            faces = json.load(fh)
    sf_tpls, xmarker = load_sf_templates(a.starfield)
    if xmarker is None:
        notes.append("Starfield.esm has no STAT XMarker: package locations near Skyrim markers will not work")
    sky = packages.Index(a.skyrim)
    world = None
    if a.moment != "none":
        try:
            world = moment_world(sky, a.skyrim, a.moment)
            notes.append(f"moment {a.moment}: quests taken as finished: {sorted(sky.edid(q) for q in world.settled)}")
        except Exception as e:                                       # noqa: BLE001
            notes.append(f"moment {a.moment}: no world ({type(e).__name__}: {e}); conditioned packages left out")
    ext_cells = None
    if a.exterior:
        fp = os.path.join(a.exterior, "formids.json")
        if os.path.exists(fp):
            ext_cells = exterior_cells(sky, fp)
            notes.append(f"exterior: {len(ext_cells)} converted Skyrim cells (package locations there are kept)")
        else:
            notes.append(f"exterior: no {fp}; outdoor package locations left out")
    actors = []
    try:
        for edid in [e.strip() for n in a.npc for e in n.split(",") if e.strip()]:
            fid = sky.find_edid(b"NPC_", edid)
            if fid is None:
                notes.append(f"{edid}: no such Skyrim NPC")
                continue
            npc = skyrimnpc.parse_npc(sky.subs(fid), fid)
            src = npc
            if npc["template"] and npc["template_flags"] & skyrimnpc.TEMPLATE_AI_PACKAGES and \
                    sky.kind(npc["template"]) == "NPC_":
                src = skyrimnpc.parse_npc(sky.subs(npc["template"]), npc["template"])
            placed = []
            for r in sky.by_type.get(b"ACHR", []):
                if next((struct.unpack_from("<I", d)[0] for s, d in sky.subs(r) if s == b"NAME" and len(d) == 4),
                        None) == fid:
                    placed.append(r)
            spot = None
            for r in placed:
                c = sky.edid(sky.cell_of.get(r, 0) or 0)
                if c in cell_names:
                    pos, rot = ref_place(sky, r)
                    spot = {"cell": c, "pos": pos, "rot": rot, "source": skyrimrefs.formkey(r, "Skyrim.esm")}
                    break
            if spot is None and ext_cells:
                # 2026-11-15 (owner: only Embry, Delphine and Orgnar are in game, "not the rest of Riverwood"): an NPC
                # Skyrim places outdoors, in a converted exterior cell, stands at its Skyrim spot in the exterior
                # world (PluginSpike: the world's persistent cell, ExtPos), as the outdoor furniture
                for r in placed:
                    if sky.cell_of.get(r) in ext_cells:
                        pos, rot = ref_place(sky, r)
                        if pos is not None:
                            spot = {"cell": "exterior", "pos": pos, "rot": rot,
                                    "source": skyrimrefs.formkey(r, "Skyrim.esm")}
                            break
            if spot is None:
                notes.append(f"{edid}: not placed in any cell of the batch ({sorted(cell_names)})"
                             + ("" if ext_cells else " (outdoors needs --exterior)") + "; left out")
                continue
            tpl, why = (a.template_npc, "--template-npc") if a.template_npc else \
                pick_template(faces, edid, npc["female"])
            if not tpl:
                notes.append(f"{edid}: {why}; give --faces or --template-npc")
                continue
            pk = [convert_package(sky, sf_tpls, p, cell_names, notes, a.keep_conditioned,
                                  a.keep_furniture_only, ext_cells, world, npc) for p in src["packages"]]
            for n, (ref, hour, minutes) in enumerate(sit_at.get(edid.lower(), [])):
                rfid = int(ref.split(":")[0], 16)
                rpos, rrot = ref_place(sky, rfid)
                place = None
                if rpos is not None:
                    rcell = sky.edid(sky.cell_of.get(rfid, 0) or 0)
                    if rcell in cell_names:
                        place = {"kind": "location", "radius_m": 1.0, "type": "near_reference", "source": ref,
                                 "pos": rpos, "rot": rrot, "cell": rcell}
                    elif ext_cells and sky.cell_of.get(rfid) in ext_cells:
                        place = {"kind": "location", "radius_m": 1.0, "type": "near_exterior_reference",
                                 "source": ref, "pos": rpos, "rot": rrot, "cell": "exterior"}
                if "sit" in sf_tpls:
                    ins = [f"{i}:{(inp.get('type') or '?')}" for i, inp in
                           zip(value_indexes(sf_tpls["sit"]["pack"]), sf_tpls["sit"]["pack"]["inputs"])]
                    notes.append(f"{edid}: --sit-at {ref}: Sit template inputs {ins}; place "
                                 f"{place['type'] if place else 'none'}")
                sp = sit_package(edid, ref, hour, minutes, sf_tpls["sit"], n, place) if "sit" in sf_tpls else None
                if sp is None:
                    notes.append(f"{edid}: --sit-at {ref}: Starfield.esm has no Sit template with a reference input")
                else:
                    pk.insert(n, sp)
            name = npc.get("full_name") or edid
            ac = {"skyrim": edid, "skyrim_form": f"{fid:08X}", "name": name, "female": npc["female"],
                  "template_npc": tpl, "template_why": why, **spot, "packages": [p for p in pk if p]}
            fn = face_npc(faces, edid, a.faces, a.face_plugin) if a.faces else None
            if fn:
                ac["face_npc"] = fn
            else:
                notes.append(f"{edid}: no face-test NPC of its own in faces.json (run face_fit.py with --npc {edid}); "
                             "a generic copy of the template")
            actors.append(ac)
    finally:
        sky.close()
    out = os.path.join(a.work, "actors.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"actors": actors, "notes": notes,
                   "xmarker": None if xmarker is None else f"{xmarker:08X}"}, fh, indent=1)
    for ac in actors:
        look = (f"its face-test NPC {ac['face_npc']['form_id']} in {ac['face_npc']['plugin']}" if ac.get("face_npc")
                else f"copy of Starfield NPC {ac['template_npc']}: {ac['template_why']}")
        print(f"{ac['skyrim']} in {ac['cell']} at {ac['pos']} ({look}):")
        for p in ac["packages"]:
            s = p["schedule"] or {}
            ins = ", ".join(f"{v['skyrim']}={v.get('value', v.get('type', v.get('source')))}" for v in p["inputs"].values())
            print(f"  {p['edid']}: {p['skyrim_template'] or '(added)'} -> {p['sf_template']}, hour {s.get('hour')} for "
                  f"{s.get('duration_min')} min; inputs {ins}")
    for n in notes:
        print("  note: " + n)
    print(f"XMarker in Starfield.esm: {'none' if xmarker is None else f'{xmarker:08X}'}")
    print(f"-> {out}")
    return 0 if actors else 1


if __name__ == "__main__":
    sys.exit(main())
