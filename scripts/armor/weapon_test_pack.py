"""Build a test mod with one Skyrim weapon of each type (the iron set) usable in Starfield, for the melee port.

On the owner's PC, in one run (docs/armor/animation-port.md, "Iron weapon test pack"):
  1. reads the iron weapons from Skyrim.esm (model path, value / weight / damage / speed / reach for the report);
  2. converts each model from the Skyrim archives with the Skyrim object converter (mesh, materials, textures),
     moved into Starfield's WEAPON frame so the handle sits in the fist with the clips this repo converts
     (fo4sf.skyrimweapon; the scabbard is left out);
  3. copies a vanilla Starfield one-handed melee weapon record (keyword AnimSword if present, else
     WeaponTypeMelee1H) once per iron weapon into S2SWeapons.esm with its own EditorID, name and model;
  4. packs the converted files into "S2SWeapons - Main.ba2" / "S2SWeapons - Textures.ba2" with the Creation Kit's
     Archive2 (Starfield loads a plugin's archives by name), or leaves them loose when Archive2 is missing.
The output folder is an MO2 mod. Animations come from whichever Nordic pack is enabled (all weapons use the
one-handed slot for now). Read-only on both games.

    python -I scripts\\armor\\weapon_test_pack.py --skyrim-data "<Skyrim Special Edition>\\Data"
        --starfield "<Starfield folder>" --texconv "<texconv.exe>" --out "<MO2 mods>\\S2S Iron Weapons"
"""
import argparse
import json
import os
import re
import shutil
import struct
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.dirname(HERE))

from fo4sf import bsa, sfnif, sfplugin, skyrimconvert, skyrimweapon  # noqa: E402
from fo4sf import nif as nifmod  # noqa: E402

PLUGIN = "S2SWeapons.esm"
MAIN_BA2 = "S2SWeapons - Main.ba2"
TEX_BA2 = "S2SWeapons - Textures.ba2"
PREFIX = "s2s"
TEMPLATE_KEYWORDS = ("AnimSword", "WeaponTypeMelee1H", "AnimOneHanded")


def skyrim_weapons(skyrim_data: str, weapons=skyrimweapon.IRON_SET) -> list:
    """The weapon list with Skyrim.esm's model path and stats where the record is found."""
    esm = os.path.join(skyrim_data, "Skyrim.esm")
    found = {}
    if os.path.isfile(esm):
        want = {w["edid"].lower() for w in weapons}
        for _t, _h, subs, fid in sfplugin.records(esm, [b"WEAP"]):
            e = sfplugin.edid(subs).lower()
            if e in want:
                found[e] = dict(skyrimweapon.skyrim_weapon_stats(subs), form_id=f"{fid:08X}")
    out = []
    for w in weapons:
        st = found.get(w["edid"].lower(), {})
        model = st.get("model") or w["model"]
        out.append(dict(w, skyrim=st, model=model))
    return out


def pick_template(weaps, kw_names, prefer=TEMPLATE_KEYWORDS, edid_rx=None):
    """(template record, reason): a vanilla WEAP carrying the first available keyword of `prefer` (by EditorID),
    or matching edid_rx when given."""
    if edid_rx:
        rx = re.compile(edid_rx, re.I)
        for r in weaps:
            if rx.search(sfplugin.edid(r[2])):
                return r, f"EditorID matches {edid_rx}"
        raise SystemExit(f"no WEAP EditorID matches {edid_rx}")
    by_name = {v.lower(): k for k, v in kw_names.items()}
    for kw in prefer:
        k = by_name.get(kw.lower())
        if k is None:
            continue
        hits = sorted((r for r in weaps if k in sfplugin.keywords(r[2])), key=lambda r: sfplugin.edid(r[2]))
        if hits:
            return hits[0], f"keyword {kw} ({len(hits)} weapons carry it)"
    raise SystemExit("no vanilla one-handed melee weapon found to copy (keywords " + ", ".join(prefer) + ")")


def weapon_record(template, index: int, edid: str, name: str, model: str):
    typ, header, subs, _fid = template
    new = sfplugin.edit(subs, {b"EDID": sfplugin.zs(edid), b"FULL": sfplugin.zs(name), b"MODL": sfplugin.zs(model)},
                        drop=(b"DESC",))
    return (typ, header, new, sfplugin.new_form_id(index))


APPAREL_TEMPLATE = r"^Clothes_Nightwear_01$"    # a vanilla outfit community mods copy successfully (robes reference)
MODEL_SIGS = (b"MOD2", b"MOD3", b"MOD4", b"MOD5")   # ARMA male / female worn, male / female first person


def form_refs(subs, ids) -> list:
    """[(sig, byte offset)] of every 4-byte-aligned u32 in subs that is one of ids."""
    import struct
    out = []
    for s, d in subs:
        for o in range(0, len(d) - 3, 4):
            if struct.unpack_from("<I", d, o)[0] in ids:
                out.append((s, o))
    return out


def only_addon(subs, keep: int):
    """ARMO subrecords with every armor-addon entry (INDX + its MODL form ID) dropped except the one pointing at `keep`
    (renumbered 0). Vanilla Clothes_Nightwear_01 lists more than one addon (Starfield ARMOs: 716 INDX / MODL pairs on
    300 records): the left blade's copy kept the outfit's other parts (owner's run 2026-10-26: pants gone)."""
    import struct
    out, i = [], 0
    while i < len(subs):
        s, d = subs[i]
        if s == b"INDX":
            j = next((k for k in range(i + 1, len(subs)) if subs[k][0] in (b"MODL", b"INDX")), None)
            if j is not None and subs[j][0] == b"MODL" and len(subs[j][1]) == 4:
                if struct.unpack("<I", subs[j][1])[0] == keep:
                    out.append((b"INDX", struct.pack("<H", 0)))
                    out.extend(subs[i + 1:j + 1])
                i = j + 1
                continue
        out.append((s, d))
        i += 1
    return out


def replace_refs(subs, old: int, new: int):
    import struct
    out = []
    for s, d in subs:
        b = bytearray(d)
        for o in range(0, len(b) - 3, 4):
            if struct.unpack_from("<I", b, o)[0] == old:
                struct.pack_into("<I", b, o, new)
        out.append((s, bytes(b)))
    return out


def pick_apparel(armo, arma, edid_rx=APPAREL_TEMPLATE):
    """(ARMO record, ARMA record it uses): the first ARMO whose EditorID matches, with the first ARMA it references."""
    import struct
    rx = re.compile(edid_rx, re.I)
    by_fid = {r[3]: r for r in arma}
    for r in armo:
        if rx.search(sfplugin.edid(r[2])):
            for s, d in r[2]:
                for o in range(0, len(d) - 3, 4):
                    v = struct.unpack_from("<I", d, o)[0]
                    if v in by_fid:
                        return r, by_fid[v]
    raise SystemExit(f"no ARMO matching {edid_rx} with an ARMA")


# Keyword on the left blade's ARMO: S2SCombat switches to the dual-wield moveset while something carrying it is worn
# (S2SCombat.ini sDualWornKeyword; the Dual stance of S2SStances.esm).
LEFT_BLADE_KEYWORD = "S2S_LeftBlade"


def with_keyword(subs, kw: int):
    """Subrecords with `kw` added to KWDA (KSIZ kept in step); KSIZ + KWDA after FULL (else EDID) when there are none."""
    import struct
    have = sfplugin.keywords(subs)
    if kw in have:
        return list(subs)
    new = have + [kw]
    kwda = struct.pack(f"<{len(new)}I", *new)
    ksiz = struct.pack("<I", len(new))
    if any(s == b"KWDA" for s, _ in subs):
        out = [(s, kwda if s == b"KWDA" else ksiz if s == b"KSIZ" else d) for s, d in subs]
        if not any(s == b"KSIZ" for s, _ in subs):
            at = next(i for i, (s, _d) in enumerate(out) if s == b"KWDA")
            out[at:at] = [(b"KSIZ", ksiz)]
        return out
    out = list(subs)
    at = next((i + 1 for i, (s, _d) in enumerate(out) if s == b"FULL"),
              next((i + 1 for i, (s, _d) in enumerate(out) if s == b"EDID"), 0))
    out[at:at] = [(b"KSIZ", ksiz), (b"KWDA", kwda)]
    return out


# The game's two worn layers by keyword (owner's spacesuit check 2026-10-27: Clothes_Nightwear_01 carries
# ArmorTypeApparelOrNakedBody, a spacesuit body ArmorTypeSpacesuitBody). With the outfit's keyword the blade was
# hidden under a shown spacesuit; without it, never drawn at all (owner's run 2026-10-27, verified). So the blade
# carries both: drawn with either layer, to test.
# With ArmorTypeSpacesuitBody the blade showed with and without a suit, but without a suit the player's body vanished
# (owner's run 2026-10-27: the game took the blade for a spacesuit body, which covers the body). A spacesuit part
# that covers nothing instead: the backpack's layer (supported by the name; the pack lists every ArmorType keyword).
OUTFIT_LAYER_KEYWORDS = ("ArmorTypeApparelOrNakedBody",)
SUIT_LAYER_KEYWORDS = ("ArmorTypeSpacesuitBackpack",)


def without_keywords(subs, drop: set):
    """Subrecords with the keyword IDs in `drop` removed from KWDA (KSIZ kept in step)."""
    import struct
    have = sfplugin.keywords(subs)
    keep = [k for k in have if k not in drop]
    if keep == have:
        return list(subs)
    out = []
    for s_, d in subs:
        if s_ == b"KWDA":
            if keep:
                out.append((s_, struct.pack(f"<{len(keep)}I", *keep)))
        elif s_ == b"KSIZ":
            if keep:
                out.append((s_, struct.pack("<I", len(keep))))
        else:
            out.append((s_, d))
    return out


def used_slots(records) -> int:
    """The biped slot bits (BO64, u64) any of these ARMO / ARMA records uses."""
    import struct
    used = 0
    for _t, _h, subs, _f in records:
        for s, d in subs:
            if s == b"BO64" and len(d) >= 8:
                used |= struct.unpack_from("<Q", d)[0]
    return used


def free_slot(records, top: int = 61, bottom: int = 0) -> int:
    """A biped slot (bit index) in [bottom, top] no vanilla ARMO / ARMA uses, the highest: the left blade there does
    not take an outfit's or a spacesuit's place (owner's run 2026-10-26: the nightwear copy removed the outfit, the
    legs and could not be worn with a spacesuit)."""
    used = used_slots(records)
    for bit in range(top, bottom - 1, -1):
        if not used >> bit & 1:
            return bit
    raise SystemExit(f"every biped slot {bottom}-{top} is used by some vanilla apparel")


# Starfield's two sets of biped slots (xEdit's wbDefinitionsSF1: 0-31 the outfit's, 32-63 "SS ..." the spacesuit's).
# Owner's run 2026-10-26: with a spacesuit on, the game hid the left blade the same way as the outfit under it (NiAVObject
# flag bit 0 on the blade's and the outfit's nodes, before the plugin touched them). Supported, not verified: the game
# shows one set at a time (the suit's while it is shown, else the outfit's), so the blade gets an addon in each.
OUTFIT_SLOTS = (0, 31)
SUIT_SLOTS = (32, 61)
SHARED_SLOT = {OUTFIT_SLOTS: 15, SUIT_SLOTS: 47}   # "Misc 3" / "SS Misc 3" when every slot of the set is used


def slot_in(records, span) -> tuple:
    """(bit, shared): a free slot of the set `span` (lowest, highest), else its Misc 3 slot (shared = True: the blade
    then takes off whatever vanilla item uses it)."""
    try:
        return free_slot(records, span[1], span[0]), False
    except SystemExit:
        return SHARED_SLOT[span], True


def with_slot(subs, bit: int):
    """BO64 set to the single slot `bit` (appended after EDID when missing)."""
    import struct
    return sfplugin.edit(subs, {b"BO64": struct.pack("<Q", 1 << bit)})


def left_blade_records(armo_t, arma_t, first_index: int, edid: str, name: str, model: str, keyword: int = None,
                       slot: int = None, suit_slot: int = None, drop_keywords: set = frozenset()):
    """(ARMA, ARMO) copies: the ARMA's worn and first-person models -> the left blade, the ARMO named and pointing at
    the new ARMA (and carrying `keyword` when given; both on biped slot `slot` when given). With `suit_slot`: (ARMA,
    ARMO, ARMA on suit_slot), the ARMO listing both addons (the blade drawn with and without a spacesuit shown) and
    covering both slots."""
    import struct
    ta, ha, sa, fa = arma_t
    new_arma = sfplugin.new_form_id(first_index)
    m = sfplugin.zs(model)
    sa2 = sfplugin.edit(sa, {b"EDID": sfplugin.zs(edid + "_AA"), **{k: m for k in MODEL_SIGS if any(s == k for s, _ in sa)}})
    to, ho, so, _fo = armo_t
    so2 = replace_refs(sfplugin.edit(so, {b"EDID": sfplugin.zs(edid), b"FULL": sfplugin.zs(name)}, drop=(b"DESC",)),
                       fa, new_arma)
    so2 = without_keywords(only_addon(so2, new_arma), set(drop_keywords))
    if keyword is not None:
        so2 = with_keyword(so2, keyword)
    if slot is not None:
        sa2, so2 = with_slot(sa2, slot), with_slot(so2, slot)
    armo = (to, ho, so2, sfplugin.new_form_id(first_index + 1))
    if suit_slot is None:
        return (ta, ha, sa2, new_arma), armo
    suit_arma = sfplugin.new_form_id(first_index + 2)
    sa3 = with_slot(sfplugin.edit(sa2, {b"EDID": sfplugin.zs(edid + "_SS_AA")}), suit_slot)
    so3 = []
    for s_, d in so2:                         # the second addon right after the first (INDX 0 + MODL, as the first)
        indexed = bool(so3) and so3[-1][0] == b"INDX"
        so3.append((s_, d))
        if s_ == b"MODL" and d == struct.pack("<I", new_arma):
            so3 += [(b"INDX", struct.pack("<H", 0))] * indexed + [(b"MODL", struct.pack("<I", suit_arma))]
    bits = (1 << slot if slot is not None else 0) | 1 << suit_slot
    so3 = sfplugin.edit(so3, {b"BO64": struct.pack("<Q", bits)})
    return (ta, ha, sa2, new_arma), (to, ho, so3, armo[3]), (ta, ha, sa3, suit_arma)


# Node of the pair weapon's model holding the left blade (in the left wrist's frame): S2SCombat.ini sLeftHandNode,
# moved onto the L_Wrist bone each frame. Owner's run 2026-10-26: a skinned left blade in a weapon model is not bound
# to the actor's bones (drawn loose by the right hand), so the blade is rigid under this node instead.
LEFT_HAND_NODE = b"S2S_LeftHand"


def _armo_summary(rec, kw_names) -> dict:
    import struct
    t, header, subs, fid = rec
    bo = next((struct.unpack_from("<Q", d)[0] for s_, d in subs if s_ == b"BO64" and len(d) >= 8), 0)
    flags = struct.unpack_from("<I", header, 8)[0] if len(header) >= 12 else None   # after the type and size
    return {"edid": sfplugin.edid(subs), "form_id": f"{fid:08X}", "record_flags": f"{flags:08X}" if flags is not None
            else None, "biped_slots": [b for b in range(64) if bo >> b & 1],
            "keywords": [kw_names.get(k, f"{k:08X}") for k in sfplugin.keywords(subs)],
            "subrecords": sorted({s_.decode("latin-1") for s_, _d in subs})}


def spacesuit_check(outfit, armo, kw_names) -> dict:
    """The outfit ARMO the left blade copies and the first vanilla ARMO on the spacesuit body slot (35) whose EditorID
    says spacesuit: keywords, record flags, slots, subrecord types, to compare."""
    import struct
    suit = next((r for r in armo if re.search("spacesuit", sfplugin.edid(r[2]), re.I) and any(
        s_ == b"BO64" and len(d) >= 8 and struct.unpack_from("<Q", d)[0] >> 35 & 1 for s_, d in r[2])), None)
    return {"outfit": _armo_summary(outfit, kw_names), "spacesuit": _armo_summary(suit, kw_names) if suit else None}


def pair_model(staging: str, right_model: str, left_model: str) -> str:
    """The pair weapon's NIF in staging: the right weapon's model with the left blade's (rigid, L_Wrist frame) shapes
    under a node LEFT_HAND_NODE (sfnif.merge_under_node); returns its model path (as in WEAP MODL)."""
    def path(m):
        return os.path.join(staging, "meshes", *m.split("\\"))
    with open(path(right_model), "rb") as fh:
        base = nifmod.parse(fh.read())
    with open(path(left_model), "rb") as fh:
        left = nifmod.parse(fh.read())
    model = re.sub(r"\.nif$", "", right_model, flags=re.I) + "_pair.nif"
    with open(path(model), "wb") as fh:
        fh.write(nifmod.serialize(sfnif.merge_under_node(base, left, LEFT_HAND_NODE)))
    return model


def pair_weapon(staging: str, template, recs: list, right: dict, lw: dict, left_model: str, keyword: int) -> dict:
    """Dual wield as one weapon (Starfield equips one weapon at a time): a WEAP copy whose model holds both blades,
    the left one under LEFT_HAND_NODE (S2SCombat moves it onto the left hand), carrying the dual keyword (S2SCombat
    switches to the Dual stance; verified 2026-10-26). `left_model`: the left blade as a static model in L_Wrist's
    frame."""
    row = {"key": lw["key"] + "_pair", "ok": False}
    try:
        model = pair_model(staging, right["starfield_model"], left_model)
    except (OSError, nifmod.NifError, struct.error) as e:
        row["reason"] = f"{type(e).__name__}: {e}"
        return row
    edid = "S2S_" + lw["edid"] + "_Pair"
    name = lw["name"] + "s (Skyrim, pair)"
    rec = weapon_record(template, len(recs), edid, name, model)
    rec = (rec[0], rec[1], with_keyword(rec[2], keyword), rec[3])
    recs.append(rec)
    row.update(ok=True, starfield_model=model, form_id_in_plugin=f"{rec[3] & 0xFFFFFF:06X}", editor_id=edid,
               name=name, test_with_pack="dual_" + lw["pack"].replace("1h_", ""), pair=True)
    return row


def pack(staging: str, out: str, starfield: str, archive2: str = None) -> dict:
    """BA2 archives with Archive2 when present (as deploy_starfield), else the files loose in the mod folder."""
    tool = archive2 or os.path.join(starfield, "Tools", "Archive2", "Archive2.exe")
    main = [d for d in ("meshes", "geometries", "materials") if os.path.isdir(os.path.join(staging, d))]
    tex = [d for d in ("textures",) if os.path.isdir(os.path.join(staging, d))]
    if os.path.isfile(tool):
        import deploy_starfield
        a = types.SimpleNamespace(starfield=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(tool)))),
                                  staging=staging)                    # build_archive finds Tools/Archive2 from there
        if main:
            deploy_starfield.build_archive(a, os.path.join(out, MAIN_BA2), main, "General")
        if tex:
            deploy_starfield.build_archive(a, os.path.join(out, TEX_BA2), tex, "DDS")
        return {"archives": [MAIN_BA2] * bool(main) + [TEX_BA2] * bool(tex)}
    for d in main + tex:
        shutil.copytree(os.path.join(staging, d), os.path.join(out, d), dirs_exist_ok=True)
    return {"loose": main + tex, "note": "Archive2 not found: files left loose (needs loose files enabled in "
                                         "StarfieldCustom.ini, as for the animation packs)"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True, help="the Starfield folder (holds Data and Tools)")
    ap.add_argument("--texconv", required=True, help="texconv.exe (docs/SETUP.md: the copy in xEdit's Edit Scripts)")
    ap.add_argument("--out", required=True, help="the mod folder to create (outside the repository)")
    ap.add_argument("--content-resources", help="default: <Starfield>/Tools/ContentResources.zip")
    ap.add_argument("--archive2", help="default: <Starfield>/Tools/Archive2/Archive2.exe")
    ap.add_argument("--template", help="EditorID regex of the vanilla weapon to copy (default: by keyword)")
    ap.add_argument("--only", help="comma list of keys from the iron set (dagger,sword,waraxe,mace,greatsword,...)")
    ap.add_argument("--left-blade", default="sword",
                    help="iron weapon also made as a worn left-hand blade for dual wield ('' = none)")
    ap.add_argument("--left-slot", type=int,
                    help="outfit biped slot bit (0-31) for the left blade (default: a free one)")
    ap.add_argument("--left-suit-slot", type=int,
                    help="spacesuit biped slot bit (32-63) for the left blade's second addon (default: a free one)")
    ap.add_argument("--left-layers", default="both", choices=["both", "outfit", "none"],
                    help="worn-layer keywords on the left blade: both (outfit + spacesuit body), the outfit's only, "
                         "or none (owner 2026-10-27: outfit = hidden under a spacesuit, none = never drawn)")
    ap.add_argument("--left-suit-layer", default=SUIT_LAYER_KEYWORDS[0],
                    help="the spacesuit-layer keyword added with --left-layers both (ArmorTypeSpacesuitBody hid the "
                         "player's body without a suit)")
    ap.add_argument("--left-bone", default="L_Wrist", choices=["L_Wrist", "WeaponLeft"],
                    help="bone the left blade is skinned to: L_Wrist (stays in the hand in every clip) or WeaponLeft")
    ap.add_argument("--apparel-template", default=APPAREL_TEMPLATE,
                    help="EditorID regex of the vanilla outfit whose ARMO / ARMA the left blade copies")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    os.makedirs(out, exist_ok=True)
    staging = os.path.join(out, "_staging")
    shutil.rmtree(staging, ignore_errors=True)
    cr = a.content_resources or os.path.join(a.starfield, "Tools", "ContentResources.zip")
    esm = os.path.join(a.starfield, "Data", "Starfield.esm")
    for p, what in ((cr, "ContentResources.zip (Creation Kit)"), (esm, "Starfield.esm"),
                    (os.path.join(a.skyrim_data, "Skyrim.esm"), "Skyrim.esm")):
        if not os.path.isfile(p):
            sys.exit(f"{what} not found: {p}")

    weapons = skyrim_weapons(a.skyrim_data)
    if a.only:
        keep = {k.strip().lower() for k in a.only.split(",")}
        weapons = [w for w in weapons if w["key"] in keep]
    conv = skyrimconvert.SkyrimConverter(bsa.SkyrimArchives(a.skyrim_data, loose=False), staging, a.texconv, cr,
                                         collision_template=None, prefix=PREFIX,
                                         shape_hook=skyrimweapon.weapon_shapes)
    report = {"weapons": [], "plugin": PLUGIN}
    info = sfplugin.header_info(esm)
    sf = sfplugin.records(esm, [b"WEAP", b"KYWD"] + ([b"ARMO", b"ARMA"] if a.left_blade else []))
    kw_names = {fid: sfplugin.edid(s) for t, _h, s, fid in sf if t == b"KYWD"}
    weaps = [r for r in sf if r[0] == b"WEAP"]
    template, why = pick_template(weaps, kw_names, edid_rx=a.template)
    report["template"] = {"edid": sfplugin.edid(template[2]), "form_id": f"{template[3]:08X}", "why": why,
                          "subrecords": [f"{s.decode('latin-1')}:{len(d)}" for s, d in template[2]],
                          "model": next((d.rstrip(b'\0').decode('latin-1') for s, d in template[2] if s == b"MODL"),
                                        None),
                          "keywords": [kw_names.get(k, f"{k:08X}") for k in sfplugin.keywords(template[2])]}
    recs = []
    for w in weapons:
        res = conv.convert_nif("meshes\\" + re.sub(r"^meshes[\\/]", "", w["model"].replace("/", "\\"), flags=re.I))
        row = {"key": w["key"], "skyrim": w["skyrim"], "model": w["model"], "ok": res["ok"],
               "reason": res.get("reason"), "scabbard_shapes_dropped": res.get("scabbard_shapes_dropped"),
               "fallback_materials": res.get("fallback_materials")}
        if res["ok"]:
            model = res["out_name"].replace("/", "\\") + ".nif"
            rec = weapon_record(template, len(recs), "S2S_" + w["edid"], w["name"] + " (Skyrim)", model)
            recs.append(rec)
            row.update(starfield_model=model, form_id_in_plugin=f"{rec[3] & 0xFFFFFF:06X}",
                       editor_id="S2S_" + w["edid"], name=w["name"] + " (Skyrim)", test_with_pack=w["pack"])
        report["weapons"].append(row)
    if not recs:
        sys.exit("no weapon converted: " + json.dumps(report["weapons"], indent=1))
    lw = next((w for w in weapons if a.left_blade and w["key"] == a.left_blade), None)
    if lw is not None:
        on_wrist = a.left_bone.lower() == "l_wrist"
        conv.shape_hook = skyrimweapon.left_wrist_shapes if on_wrist else skyrimweapon.left_weapon_shapes
        res = conv.convert_nif("meshes\\" + re.sub(r"^meshes[\\/]", "", lw["model"].replace("/", "\\"), flags=re.I),
                               skin_bone="L_Wrist" if on_wrist else "WeaponLeft", out_suffix="_left")
        row = {"key": lw["key"] + "_left", "ok": res["ok"], "reason": res.get("reason")}
        if res["ok"]:
            armo_t, arma_t = pick_apparel([r for r in sf if r[0] == b"ARMO"], [r for r in sf if r[0] == b"ARMA"],
                                          a.apparel_template)
            model = res["out_name"].replace("/", "\\") + ".nif"
            edid = "S2S_" + lw["edid"] + "_Left"
            name = lw["name"] + " (Skyrim, left hand)"
            kywd_t = next(r for r in sf if r[0] == b"KYWD")
            kw_fid = sfplugin.new_form_id(len(recs))
            recs.append((b"KYWD", kywd_t[1], sfplugin.edit(kywd_t[2], {b"EDID": sfplugin.zs(LEFT_BLADE_KEYWORD)},
                                                           drop=(b"FULL", b"DESC")), kw_fid))
            apparel = [r for r in sf if r[0] in (b"ARMO", b"ARMA")]
            slot, shared = (a.left_slot, False) if a.left_slot is not None else slot_in(apparel, OUTFIT_SLOTS)
            suit, suit_shared = ((a.left_suit_slot, False) if a.left_suit_slot is not None
                                 else slot_in(apparel, SUIT_SLOTS))
            aa, ao, aa_suit = left_blade_records(armo_t, arma_t, len(recs), edid, name, model, keyword=kw_fid,
                                                 slot=slot, suit_slot=suit)
            if a.left_layers == "both":                   # a spacesuit layer's keyword too
                suit_kw = [k for k, n in kw_names.items() if n == a.left_suit_layer]
                if not suit_kw:
                    row["layer_missing"] = a.left_suit_layer
                for k in suit_kw:
                    ao = (ao[0], ao[1], with_keyword(ao[2], k), ao[3])
            elif a.left_layers == "none":
                layer = {k for k, n in kw_names.items() if n in OUTFIT_LAYER_KEYWORDS}
                ao = (ao[0], ao[1], without_keywords(ao[2], layer), ao[3])
            row["armor_type_keywords"] = sorted(n for n in kw_names.values() if n.startswith("ArmorType"))
            row["layer_keywords"] = [kw_names.get(k, f"{k:08X}") for k in sfplugin.keywords(ao[2])
                                     if kw_names.get(k, "").startswith("ArmorType")]
            row["biped_slot"] = {"bit": slot, "suit_bit": suit, "shared_with_vanilla": [b for b, sh in
                                 ((slot, shared), (suit, suit_shared)) if sh],
                                 "vanilla_slots_used": f"{used_slots(apparel):016X}"}
            recs += [aa, ao, aa_suit]
            row["keyword"] = {"edid": LEFT_BLADE_KEYWORD, "form_id_in_plugin": f"{kw_fid & 0xFFFFFF:06X}"}
            # what the game may tell outfits and spacesuits apart by (owner's runs 2026-10-27: the blade is hidden
            # under a spacesuit even with an addon on a spacesuit slot): the copied outfit's keywords and record
            # flags, next to a vanilla spacesuit body's
            row["spacesuit_check"] = spacesuit_check(armo_t, [r for r in sf if r[0] == b"ARMO"], kw_names)
            row.update(starfield_model=model, form_id_in_plugin=f"{ao[3] & 0xFFFFFF:06X}", editor_id=edid, name=name,
                       test_with_pack="dual_" + lw["pack"].replace("1h_", ""), worn=True,
                       apparel_template={"armo": sfplugin.edid(armo_t[2]), "arma": sfplugin.edid(arma_t[2]),
                                         "arma_subrecords": [f"{x.decode('latin-1')}:{len(d)}" for x, d in arma_t[2]]})
            right = next((w for w in report["weapons"] if w["key"] == lw["key"] and w.get("ok")), None)
            if right is not None and on_wrist:
                report["weapons"].append(row)
                conv.shape_hook = skyrimweapon.left_wrist_shapes        # the same blade, rigid (static model)
                rigid = conv.convert_nif("meshes\\" + re.sub(r"^meshes[\\/]", "", lw["model"].replace("/", "\\"),
                                                            flags=re.I), out_suffix="_left_rigid")
                if rigid["ok"]:
                    row = pair_weapon(staging, template, recs, right, lw,
                                      rigid["out_name"].replace("/", "\\") + ".nif", kw_fid)
                else:
                    row = {"key": lw["key"] + "_pair", "ok": False, "reason": rigid.get("reason")}
        report["weapons"].append(row)
    with open(os.path.join(out, PLUGIN), "wb") as fh:
        fh.write(sfplugin.build(recs, info))
    report["packing"] = pack(staging, out, a.starfield, a.archive2)
    report["converter"] = {"stats": conv.stats, "material_errors": conv.material_errors}
    with open(os.path.join(out, "weapon_test_pack.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    lines = ["S2S Iron Weapons: one Skyrim weapon of each type for testing the melee port.", "",
             "Enable this mod and ONE Nordic animation pack in MO2. In game, open the console (~) and run:",
             '  help "(Skyrim)" 4      - lists the weapons with their FormIDs', "  player.additem <FormID> 1", "",
             "Weapon            FormID ending   test with pack"]
    for r in report["weapons"]:
        if r["ok"]:
            lines.append(f"  {r['name']:<24} ..{r['form_id_in_plugin'][-3:]}          {r['test_with_pack']}")
        else:
            lines.append(f"  {r['key']}: not converted ({r['reason']})")
    if any(r.get("worn") for r in report["weapons"]):
        lines += ["", "The left-hand blade is worn (equip it like clothing) next to the same weapon in the right hand,",
                  "with the Dual stance moveset (S2SStances.esm). It sits on a biped slot no vanilla apparel uses, so",
                  "it is worn alongside outfits and spacesuits."]
    if any(r.get("pair") for r in report["weapons"]):
        lines += ["", "The pair weapon holds both blades in one weapon (the left one moves with the left hand): equip only",
                  "it, nothing worn. It switches to the Dual stance moveset by itself."]
    lines += ["", f"Copied from the vanilla weapon {report['template']['edid']} ({report['template']['why']}): stats,",
              "sounds and keywords are that weapon's for now; only the model and name change."]
    with open(os.path.join(out, "README.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    shutil.rmtree(staging, ignore_errors=True)
    print("\n".join(lines))
    for r in report["weapons"]:
        if r.get("spacesuit_check"):
            print("\nspacesuit check (paste this back):")
            print(json.dumps({"slots": r.get("biped_slot"), "blade_layer_keywords": r.get("layer_keywords"),
                              "layer_missing": r.get("layer_missing"),
                              "armor_type_keywords": r.get("armor_type_keywords")}, indent=1))
    print(f"\nreport: {os.path.join(out, 'weapon_test_pack.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
