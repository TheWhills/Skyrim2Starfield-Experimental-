"""Skyrim's placed food, drink, potions, ingredients and clutter (MiscItem) in the converted interiors as real Starfield items (docs/interior/items.md
"Placed items").

    python -I scripts\\interior\\make_items.py --skyrim "$sky\\Skyrim.esm" --skyrim-data "$sky" --starfield "$sf" ^
        --work C:\\Modding\\work\\s2s\\riverwood_doors

Run after the batch's models are converted (make_skyrim_objects.py convert) and before PluginSpike, which reads
<work>\\items.json (ITEMS=<that file>). Owner, 2026-11-21 (after the wine test worked as a loose item: "yes" to making
Riverwood's tables and shelves real items first, the items' own physics shapes and Skyrim's effects later).

Per Skyrim ALCH / INGR / MISC base placed in the batch's cells (<work>\\cells.txt; the refs PluginSpike would otherwise place
as statics):
  - its kind: drink (food flag and a bottle / jug / wine / mead / ale word), food (other food, every ingredient), potion
    (not food: potions and poisons), misc (MISC clutter: plates, tankards, baskets, tools; 2026-11-21);
  - a DONOR: the vanilla Starfield ALCH of the same kind (its EditorID's prefix: Drink_, Food_, Aid_ / Med_ / Chem_; for
    misc a Starfield MISC that is not a resource, credits, contraband, quest, featured or scripted item)
    whose size (its own geometry's bounds; its OBND when the NIF has none) is closest to our converted model's (height against height, the two flat sides against each other, on a
    log scale), among those whose world model has a physics body. The item is a copy of the donor's record (its
    effects, sounds, keywords, value, weight: Starfield's own, items.md step 5), with the Skyrim name and our model;
  - our model with the donor's dynamic body (item_test.with_physics, verified on the wine bottle 2026-11-21), written
    next to the static as <model>_item.nif. The donor's hull is the donor's shape, so our geometry is moved to sit on
    it: the centre of its flat sides and its bottom on the donor's bounds (--no-align leaves it where it is); the
    reference is shifted back by the same amount (origin_offset_m), so the item stands where Skyrim put it.
Each reference keeps Skyrim's position, rotation, scale, Initially Disabled and Don't Havok Settle flags; its owner
(XOWN) is recorded but not written yet (no ownership: taking is not stealing).
"""
import argparse
import json
import math
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts", "npc"))

from fo4sf import nif as nifmod, sfplugin  # noqa: E402
import item_test  # noqa: E402

U = 70.0                                        # Skyrim units per metre
ITEM_TYPES = ("Ingestible", "Ingredient", "MiscItem")   # cell.json types made items (MiscItem: 2026-11-21, clutter)
FOOD, MEDICINE, POISON = 0x2, 0x10000, 0x20000  # ALCH ENIT flags (Skyrim and Starfield; Mutagen's Ingestible.Flag)
NO_SETTLE, DISABLED = 0x20000000, 0x800         # REFR record flags: Don't Havok Settle, Initially Disabled
DRINK_RX = r"wine|mead|\bale\b|ale$|beer|bottle|jug|flask|brandy|milk|skooma|spirit|tankard|honningbrew|blackbriar"
SKIP_DONOR_RX = r"test|notplayable|dummy|template|deprecated|^zz|^cut|_cut\b|debug"
# 2026-11-21 (owner's second -Items run): by size alone Skyrim's 0.4 m wine bottles copied a TerraBrew coffee cup (no
# Starfield drink is that tall) and cabbages / potatoes packaged meals (box bodies that never roll). A Skyrim item of
# these sorts prefers donors of the matching Starfield family when there are any; size decides within it.
ALCOHOL_RX = r"wine|mead|\bale\b|ale$|beer|brandy|spirit|honningbrew|blackbriar|\brum\b|whisk"
PRODUCE_RX = (r"cabbage|potato|leek|apple|garlic|carrot|tomato|gourd|lettuce|pear|berr|egg|root|radish|onion|melon|"
              r"corn|wheat")
# clutter families (same run: tankards copied RobotMachinePart01, plates GeneticSampler01, so their value / scrap parts
# were a robot part's and a lab tool's): Skyrim's dishes prefer Starfield's kitchen / bar / dish items, its tools Tool_
KITCHEN_RX = r"plate|bowl|tankard|cup|mug|goblet|fork|knife|spoon|ladle|pot\b|pot\d|potmedium|potsmall|kettle|pitcher|jug|flagon|cauldron|platter"
TOOL_RX = r"hammer|tongs|saw\b|saw\d|pickaxe|shovel|broom|hoe\b|pitchfork|chisel|axe\b|woodaxe|lockpick|shears"
PREFER = {"alcohol": r"^drink_alc_", "produce": r"^food_produce_",
          "kitchen": r"^(kitchen_|bar_|fooddrink_|dish|plate|mug|cup|tray|bowl)", "tool": r"^tool_"}
# MISC donors (2026-11-21, owner: "lets do clutter next"): Starfield's loose misc items, not its resources (a plate must not
# count as iron for crafting), credits / digipicks, contraband, quest or featured items, or scripted ones
# owner's first clutter run (2026-11-21): MissionCargoType15 (troll skull) and FFParadisoZ01_Parts (kettle) slipped
# through: mission cargo and FF... (Freestar / faction quest) items are left out too
MISC_SKIP_RX = (r"^(inorg|org|mfg|res_|resource|credits|digipick|ammo|ff)|contraband|quest|mission|cargo|"
                r"^(mq|sq|uc|fc|ri|cf|bq|lc|se|oe|city|com|dlc|sfbgs|ecs|rad|mb|tm|crs)\d*_")
MISC_SKIP_KEYWORD_RX = r"contraband|resource|unique|collectible|quest"
SKYRIM_MISC_SKIP_RX = r"^gold0"                 # Skyrim's gold: Starfield's credits, a step of its own (left static)
KINDS = ("drink", "food", "potion", "misc")
MAX_TRIES = 12                                  # donors whose NIF is read for a body, best fit first


def u32(d, p=0):
    return struct.unpack_from("<I", d, p)[0] if len(d) >= p + 4 else 0


def skyrim_kind(sig: str, edid: str, model: str, flags: int) -> str:
    """drink / food / potion of a Skyrim ALCH ("ALCH") or INGR ("INGR") by its ENIT flags and words; misc for MISC."""
    if sig == "MISC":
        return "misc"
    if sig == "INGR":
        return "food"
    if not flags & FOOD:
        return "potion"
    return "drink" if re.search(DRINK_RX, f"{edid} {model}", re.I) else "food"


def skyrim_family(kind: str, edid: str) -> str:
    """alcohol / produce / "" : the Starfield donor family a Skyrim item prefers (PREFER), by its EditorID."""
    if kind == "drink" and re.search(ALCOHOL_RX, edid, re.I):
        return "alcohol"
    if kind == "food" and re.search(PRODUCE_RX, edid, re.I) and not re.search(r"baked|grilled|cooked|soup|stew", edid, re.I):
        return "produce"
    if kind == "misc" and re.search(KITCHEN_RX, edid, re.I):
        return "kitchen"
    if kind == "misc" and re.search(TOOL_RX, edid, re.I):
        return "tool"
    return ""


def pretty_name(edid: str) -> str:
    """A name from an EditorID, for Skyrim records without FULL (owner's clutter run: "BasicFork01", "BasicKnife01"):
    the Basic / Common prefix and trailing digits dropped, words split ("BasicWoodenBowl01" -> "Wooden Bowl")."""
    e = re.sub(r"\d+[A-Za-z]?$", "", re.sub(r"^(Basic|Common|Clutter)", "", edid)) or edid
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", e).strip() or edid


def starfield_kinds(edid: str, model: str = "", flags: int = 0) -> set:
    """The kinds a vanilla Starfield ALCH can stand in for (empty: none), by its EditorID's prefix: Drink_ / Food_ /
    Aid_ Med_ Chem_. 2026-11-21 (owner's first -Items run): words matched on model paths too put 269 of 343 ALCH in
    "drink" (Skyrim's wine copied a seaweed pack and a cereal box) and flags / words made ShipRepairKit and
    LegendaryCatalyst "potions"; Starfield's EditorIDs name the kind."""
    if re.search(SKIP_DONOR_RX, edid, re.I):
        return set()
    if re.match(r"drink_", edid, re.I):
        return {"drink"}
    if re.match(r"food_", edid, re.I):
        return {"food"}
    if re.match(r"(aid|med|chem)_", edid, re.I):
        return {"potion"}
    return set()


def geometry_bounds(nif_bytes: bytes):
    """[[min], [max]] metres (the NIF's own frame) of a Starfield NIF's BSGeometry boxes (centre + half extents, as
    sfnif.bounds_from_points writes them), each through its node's world transform; None when it has none. Used for a
    donor's size first; its OBND agrees (owner's second run, 2026-11-21: all 283 donors sized from geometry gave the
    same metres as OBND had, e.g. Food_Generic_CerealBox 0.136 x 0.136 x 0.195), so OBND stays the fallback."""
    from fo4sf import sfnif
    n = nifmod.parse(nif_bytes)
    world = nifmod.world_transforms(n)
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    for i in range(len(n.blocks)):
        if n.type_of(i) != "BSGeometry":
            continue
        try:
            box = sfnif.parse_bsgeometry(n.blocks[i]).box
        except (nifmod.NifError, struct.error):
            continue
        if not all(math.isfinite(v) and abs(v) < 1e4 for v in box) or min(box[3:]) < 0:
            continue
        t, r, sc = world(i)
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    v = (box[0] + sx * box[3], box[1] + sy * box[4], box[2] + sz * box[5])
                    w = [sc * sum(r[3 * a + k] * v[k] for k in range(3)) + t[a] for a in range(3)]
                    lo = [min(lo[a], w[a]) for a in range(3)]
                    hi = [max(hi[a], w[a]) for a in range(3)]
    return [lo, hi] if lo[0] <= hi[0] else None


def obnd(d: bytes):
    """[[min], [max]] metres of a Starfield OBND (6 floats); None for any other layout."""
    if len(d) != 24:
        return None
    v = struct.unpack("<6f", d)
    if not all(math.isfinite(x) for x in v):
        return None
    return [list(v[:3]), list(v[3:])]


def dims(b):
    """(flat side a, flat side b, height) metres of [[min], [max]], the flat sides sorted, each at least 5 mm."""
    x, y, z = (max(0.005, b[1][i] - b[0][i]) for i in range(3))
    return (*sorted((x, y)), z)


def fit(ours, donor) -> float:
    """How far apart two sizes are: sum of |log ratio| of height and of the sorted flat sides (0 = the same)."""
    a, b = dims(ours), dims(donor)
    return sum(abs(math.log(p / q)) for p, q in zip(a, b))


def align_offset(ours, donor):
    """(dx, dy, dz) metres moving our geometry so its flat centre and bottom sit on the donor's bounds."""
    return tuple(round(v, 4) for v in ((donor[0][0] + donor[1][0] - ours[0][0] - ours[1][0]) / 2,
                                       (donor[0][1] + donor[1][1] - ours[0][1] - ours[1][1]) / 2,
                                       donor[0][2] - ours[0][2]))


def shift_children(nif_bytes: bytes, d) -> bytes:
    """Our static's geometry moved by d (metres, the root's frame): d added to every direct child of the root."""
    if not any(d):
        return nif_bytes
    n = nifmod.parse(nif_bytes)
    for c in nifmod.node_children(n, 0):
        blk = n.blocks[c]
        _name, nextra = struct.unpack_from("<iI", blk, 0)
        p = 8 + 4 * nextra + 8
        t = struct.unpack_from("<3f", blk, p)
        n.blocks[c] = blk[:p] + struct.pack("<3f", *(t[i] + d[i] for i in range(3))) + blk[p + 12:]
    return nifmod.serialize(n)


def item_model_name(model: str) -> str:
    return re.sub(r"\.nif$", "", model, flags=re.I) + "_item.nif"


def starfield_donors(recs, keyword_edids=None):
    """[{fid, sig, edid, model, bounds, kinds, scripted}] of Starfield ALCH / MISC records with a model that can be donors.
    keyword_edids: {KYWD FormID: EditorID} (MISC donors with a contraband / resource / unique keyword are left out)."""
    kw = keyword_edids or {}
    out = []
    for t, _h, subs, fid in recs:
        if t not in (b"ALCH", b"MISC"):
            continue
        d = {}
        for s, v in subs:
            d.setdefault(s, bytes(v))
        model = d.get(b"MODL", b"").split(b"\0")[0].decode("latin-1")
        if not model:
            continue
        e = sfplugin.edid(subs)
        if t == b"ALCH":
            kinds = starfield_kinds(e, model, u32(d.get(b"ENIT", b""), 4))
        else:
            kws = d.get(b"KWDA", b"")
            names = [kw.get(u32(kws, i), "") for i in range(0, len(kws) - 3, 4)]
            ok = not (b"VMAD" in d or b"FIMD" in d or re.search(SKIP_DONOR_RX, e, re.I)
                      or re.search(MISC_SKIP_RX, e, re.I)
                      or any(re.search(MISC_SKIP_KEYWORD_RX, n, re.I) for n in names))
            kinds = {"misc"} if ok else set()
        if not kinds:
            continue
        out.append({"fid": fid, "sig": t.decode(), "edid": e, "model": model, "bounds": obnd(d.get(b"OBND", b"")),
                    "kinds": kinds, "scripted": b"VMAD" in d})
    return out


def rank_donors(ours, kind, donors, family=""):
    """Donors for one item, best first: its kind (else any), within it its family (PREFER) when any donor is of it,
    sized ones by fit, unscripted before scripted."""
    pool = [x for x in donors if kind in x["kinds"]] or list(donors)
    if family in PREFER:
        pool = [x for x in pool if re.match(PREFER[family], x["edid"], re.I)] or pool

    def key(x):
        return (x["bounds"] is None, x["scripted"], fit(ours, x["bounds"]) if x["bounds"] else 0.0, x["edid"].lower())
    return sorted(pool, key=key)


def skyrim_base(subs):
    """{edid, name (string id or text), model, value, weight, flags, bounds (metres from OBND)} of a Skyrim ALCH / INGR."""
    d = {}
    for s, v in subs:
        d.setdefault(s, bytes(v))
    full = d.get(b"FULL", b"")
    name = u32(full) if len(full) == 4 else full.split(b"\0")[0].decode("latin-1")
    enit = d.get(b"ENIT", b"")
    ob = d.get(b"OBND", b"")
    bounds = None
    if len(ob) == 12:
        v = struct.unpack("<6h", ob)
        bounds = [[x / U for x in v[:3]], [x / U for x in v[3:]]]
    return {"edid": d.get(b"EDID", b"").split(b"\0")[0].decode("latin-1"), "name": name,
            "model": d.get(b"MODL", b"").split(b"\0")[0].decode("latin-1"),
            "value": (struct.unpack_from("<i", enit)[0] if len(enit) >= 4
                      else struct.unpack_from("<i", d[b"DATA"])[0] if len(d.get(b"DATA", b"")) == 8 else 0),
            "flags": u32(enit, 4),
            # ALCH DATA: weight; MISC / INGR DATA: value, weight
            "weight": (struct.unpack_from("<f", d[b"DATA"])[0] if len(d.get(b"DATA", b"")) == 4
                       else struct.unpack_from("<f", d[b"DATA"], 4)[0] if len(d.get(b"DATA", b"")) == 8 else 0.0),
            "bounds": bounds}


def ref_info(subs):
    """(base FormID, owner FormID or None) of a placed reference's subrecords."""
    base = owner = None
    for s, v in subs:
        if s == b"NAME" and len(v) == 4:
            base = u32(v)
        elif s == b"XOWN" and len(v) >= 4:
            owner = u32(v)
    return base, owner


def build(cells, ix, manifest, donors, names, convert_dir, read_physics, bounds_of, align=True):
    """items.json content and the item NIFs to write ({path relative to meshes: bytes}).
    cells: [cell.json dicts]; ix: Skyrim Index (subs / records / kind); manifest: {"meshes\\<skyrim model>" lower: our
    model}; donors: starfield_donors(); names: Skyrim string id -> text; read_physics(donor) -> with_physics args or
    None; bounds_of(our model) -> [[min], [max]] or None."""
    bases, refs, skipped, nifs, bodies = {}, [], [], {}, {}
    for cell in cells:
        for r in cell["refs"]:
            if r.get("type") not in ITEM_TYPES or not r.get("model"):
                continue
            try:
                fid = int(r["formkey"].split(":")[0], 16)
            except ValueError:
                continue
            base, owner = ref_info(ix.subs(fid))
            if base is None:
                continue
            key = f"{base & 0xFFFFFF:06X}:Skyrim.esm"
            if key not in bases and key not in skipped_keys(skipped):
                got = make_base(key, base, ix, manifest, donors, names, convert_dir, read_physics, bounds_of,
                                align, nifs, bodies)
                if isinstance(got, str):
                    skipped.append({"base": key, "edid": ix.edid(base), "why": got})
                    continue
                bases[key] = got
            if key not in bases:
                continue
            flags = ix.records.get(fid, (None, 0, 0))[2]
            refs.append({"formkey": r["formkey"], "cell": cell["cell"], "base": key, "pos": r["pos"], "rot": r["rot"],
                         "scale": r.get("scale") or 1.0, "disabled": bool(r.get("disabled")) or bool(flags & DISABLED),
                         "no_settle": bool(flags & NO_SETTLE),
                         "owner": f"{owner & 0xFFFFFF:06X}:Skyrim.esm" if owner else None})
    return {"bases": bases, "refs": refs, "skipped": skipped}, nifs


def skipped_keys(skipped):
    return {s["base"] for s in skipped}


def make_base(key, base, ix, manifest, donors, names, convert_dir, read_physics, bounds_of, align, nifs, bodies):
    sig = ix.kind(base)
    info = skyrim_base(ix.subs(base))
    ours_model = manifest.get(("meshes\\" + info["model"].lstrip("\\")).lower()) if info["model"] else None
    if not ours_model:
        return f"model {info['model'] or '(none)'} not converted"
    ours = bounds_of(ours_model) or info["bounds"]
    if not ours:
        return f"no bounds for {ours_model}"
    if sig == "MISC" and re.search(SKYRIM_MISC_SKIP_RX, info["edid"], re.I):
        return "gold: becomes Starfield credits in a later step"
    kind = skyrim_kind(sig, info["edid"], info["model"], info["flags"])
    family = skyrim_family(kind, info["edid"])
    donor = phys = None
    tried = []
    for dn in rank_donors(ours, kind, donors, family)[:MAX_TRIES]:
        if dn["fid"] not in bodies:
            bodies[dn["fid"]] = read_physics(dn)
        if bodies[dn["fid"]] is None:
            tried.append(dn["edid"])
            continue
        donor, phys = dn, bodies[dn["fid"]]
        break
    if donor is None:
        return f"no {kind} donor with a physics body (tried {', '.join(tried) or 'none'})"
    src = os.path.join(convert_dir, "meshes", *ours_model.replace("\\", "/").split("/"))
    with open(src, "rb") as fh:
        nif = fh.read()
    d = align_offset(ours, donor["bounds"]) if align and donor["bounds"] else (0.0, 0.0, 0.0)
    nif = item_test.with_physics(shift_children(nif, d), *phys)
    model = item_model_name(ours_model)
    nifs[model] = nif
    bounds = [[ours[0][i] + d[i] for i in range(3)], [ours[1][i] + d[i] for i in range(3)]]
    name = (names.get(info["name"]) if isinstance(info["name"], int) else info["name"]) or pretty_name(info["edid"])
    out = {"edid": info["edid"], "name": name, "skyrim_type": sig, "kind": kind, "family": family,
           "record": donor.get("sig", "ALCH"), "donor": f"{donor['fid']:08X}",
           "donor_edid": donor["edid"], "donor_model": donor["model"], "model": model,
           "bounds": [[round(v, 4) for v in b] for b in bounds], "origin_offset_m": [-v for v in d],
           "fit": round(fit(ours, donor["bounds"]), 3) if donor["bounds"] else None,
           "size_m": [round(v, 3) for v in dims(ours)],
           "donor_size_m": [round(v, 3) for v in dims(donor["bounds"])] if donor["bounds"] else None,
           "skyrim_value": info["value"], "skyrim_weight": round(info["weight"], 3)}
    if tried:
        out["donors_without_body"] = tried
    return out


def read_cells(work):
    path = os.path.join(work, "cells.txt")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                with open(line.strip(), encoding="utf-8") as c:
                    out.append(json.load(c))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True, help="Skyrim.esm")
    ap.add_argument("--skyrim-data", required=True, help="Skyrim Data folder (the name strings)")
    ap.add_argument("--starfield", required=True, help="Starfield install folder (Data\\Starfield.esm and archives)")
    ap.add_argument("--work", required=True, help="interior batch work folder, converted (cells.txt, convert\\)")
    ap.add_argument("--no-align", action="store_true", help="leave our geometry where it is on the donor's body")
    a = ap.parse_args(argv)
    if os.path.abspath(a.work).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--work must be outside the repository")
    cells = read_cells(a.work)
    if not cells:
        ap.error(f"no cells.txt in {a.work}")
    convert_dir = os.path.join(a.work, "convert")
    man_path = os.path.join(convert_dir, "manifest.json")
    if not os.path.exists(man_path):
        sys.exit(f"{man_path} missing: convert the batch first")
    with open(man_path, encoding="utf-8") as fh:
        manifest = {i["source"].replace("/", "\\").lower(): i["model"] for i in json.load(fh).get("items", [])}
    from fo4sf import bsa, packages, skyrimlod
    import item_physics_probe as P
    import npc_records
    sf_data = os.path.join(a.starfield, "Data")
    sf_recs = sfplugin.records(os.path.join(sf_data, "Starfield.esm"), [b"ALCH", b"MISC", b"KYWD"])
    kw = {fid: sfplugin.edid(subs) for t, _h, subs, fid in sf_recs if t == b"KYWD"}
    donors = starfield_donors(sf_recs, kw)
    print(f"Starfield donors: {len(donors)} ALCH / MISC with a model "
          + ", ".join(f"{k} {sum(k in d['kinds'] for d in donors)}" for k in KINDS))
    arcs = P.Archives(sf_data)
    physics = {}
    for dn in donors:                     # each donor's NIF once: its body, and its size from its own geometry
        try:
            data = arcs.read("meshes\\" + dn["model"])
            physics[dn["fid"]] = item_test.donor_physics(data)
            geo = geometry_bounds(data)
        except Exception:                                      # noqa: BLE001 (missing / unreadable donor NIF)
            physics[dn["fid"]], geo = None, None
        dn["size_from"] = "geometry" if geo else ("obnd" if dn["bounds"] else None)
        dn["bounds"] = geo or dn["bounds"]
    donors = [dn for dn in donors if physics[dn["fid"]] is not None]
    print(f"  with a physics body: " + ", ".join(f"{k} {sum(k in d['kinds'] for d in donors)}" for k in KINDS)
          + f"; sized from their geometry {sum(d['size_from'] == 'geometry' for d in donors)}")

    def read_physics(dn):
        return physics.get(dn["fid"])

    def bounds_of(model):
        try:
            return skyrimlod.model_bounds(convert_dir, model)
        except (OSError, ValueError, struct.error):
            return None
    names = npc_records.skyrim_names(bsa.SkyrimArchives(a.skyrim_data))
    ix = packages.Index(a.skyrim)
    try:
        out, nifs = build(cells, ix, manifest, donors, names, convert_dir, read_physics, bounds_of, not a.no_align)
    finally:
        ix.close()
    for model, data in nifs.items():
        path = os.path.join(convert_dir, "meshes", *model.replace("\\", "/").split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
    path = os.path.join(a.work, "items.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    by_base = {}
    for r in out["refs"]:
        by_base[r["base"]] = by_base.get(r["base"], 0) + 1
    print(f"{len(out['refs'])} placed items from {len(out['bases'])} Skyrim bases in {len(cells)} cells "
          f"({sum(r['owner'] is not None for r in out['refs'])} owned in Skyrim: not yet owned here)")
    for k, b in sorted(out["bases"].items(), key=lambda kv: (kv[1]["kind"], kv[1]["edid"])):
        print(f"  {(b['family'] or b['kind']):7} {b['edid'][:28]:28} x{by_base.get(k, 0):<3} -> {b['donor_edid'][:40]:40} "
              f"size {b['size_m']} vs {b['donor_size_m']} (fit {b['fit']})")
    for s in out["skipped"]:
        print(f"  skipped {s['edid']}: {s['why']} (left as a static)")
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
