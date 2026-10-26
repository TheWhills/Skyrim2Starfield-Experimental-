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
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.dirname(HERE))

from fo4sf import bsa, sfplugin, skyrimconvert, skyrimweapon  # noqa: E402

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


def left_blade_records(armo_t, arma_t, first_index: int, edid: str, name: str, model: str, keyword: int = None):
    """(ARMA, ARMO) copies: the ARMA's worn and first-person models -> the left blade, the ARMO named and pointing at
    the new ARMA (and carrying `keyword` when given)."""
    ta, ha, sa, fa = arma_t
    new_arma = sfplugin.new_form_id(first_index)
    m = sfplugin.zs(model)
    sa2 = sfplugin.edit(sa, {b"EDID": sfplugin.zs(edid + "_AA"), **{k: m for k in MODEL_SIGS if any(s == k for s, _ in sa)}})
    to, ho, so, _fo = armo_t
    so2 = replace_refs(sfplugin.edit(so, {b"EDID": sfplugin.zs(edid), b"FULL": sfplugin.zs(name)}, drop=(b"DESC",)),
                       fa, new_arma)
    if keyword is not None:
        so2 = with_keyword(so2, keyword)
    return (ta, ha, sa2, new_arma), (to, ho, so2, sfplugin.new_form_id(first_index + 1))


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
        conv.shape_hook = skyrimweapon.left_weapon_shapes
        res = conv.convert_nif("meshes\\" + re.sub(r"^meshes[\\/]", "", lw["model"].replace("/", "\\"), flags=re.I),
                               skin_bone="WeaponLeft", out_suffix="_left")
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
            aa, ao = left_blade_records(armo_t, arma_t, len(recs), edid, name, model, keyword=kw_fid)
            recs += [aa, ao]
            row["keyword"] = {"edid": LEFT_BLADE_KEYWORD, "form_id_in_plugin": f"{kw_fid & 0xFFFFFF:06X}"}
            row.update(starfield_model=model, form_id_in_plugin=f"{ao[3] & 0xFFFFFF:06X}", editor_id=edid, name=name,
                       test_with_pack="dual_" + lw["pack"].replace("1h_", ""), worn=True,
                       apparel_template={"armo": sfplugin.edid(armo_t[2]), "arma": sfplugin.edid(arma_t[2]),
                                         "arma_subrecords": [f"{x.decode('latin-1')}:{len(d)}" for x, d in arma_t[2]]})
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
                  "with a dual-wield Nordic pack. It copies a vanilla outfit's records, so it replaces your outfit",
                  "while worn (a test shortcut)."]
    lines += ["", f"Copied from the vanilla weapon {report['template']['edid']} ({report['template']['why']}): stats,",
              "sounds and keywords are that weapon's for now; only the model and name change."]
    with open(os.path.join(out, "README.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    shutil.rmtree(staging, ignore_errors=True)
    print("\n".join(lines))
    print(f"\nreport: {os.path.join(out, 'weapon_test_pack.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
