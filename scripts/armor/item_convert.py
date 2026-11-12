"""Skyrim clothing converted per item, a male and a female version of each, with ids that stay put (S2SClothes.esm).

    python -I scripts\\armor\\item_convert.py --skyrim-data $sky --starfield $sf --npc Ysolda ^
        --out "$mods\\S2S Clothes" --test-npcs

Why (owner 2026-11-09): "we need to use however starfield does the male and female version of the same outfit ...
with the right id so everyone thats supposed to wear that clothing wears it, male or female, with it appearing as the
correct version". gear_fit.py converts per NPC: "Ysolda's outfit" is one model, fitted to her sex, whoever wears it.
Both games' armor addon (ARMA) holds a male and a female model (MOD2 / MOD3) and the engine picks by the wearer's sex;
Starfield adds a slider morph per sex (NAM4 / NAM6). So, per Skyrim armor (ARMO):
  1. gear_fit.py --stage, once per sex: the Skyrim addon's MALE model fitted to Starfield's male body, the FEMALE
     model (the male one when the addon has none) to the female body: part NIFs, slider morphs and textures, no
     records (meshes\\S2S\\Items\\<ARMO>_M\\ and _F\\);
  2. the two sexes' parts paired (the skin piece with the skin piece, then the same shape name, then the same slots);
     each pair is one ARMA with MOD2 + NAM4 (male) and MOD3 + NAM6 (female); a part only one sex has gets an ARMA with
     that sex's fields only (what the game shows the other sex then is to check in game);
  3. one ARMO per Skyrim ARMO (S2S_<EditorID>, Skyrim's name), one OTFT per Skyrim outfit (S2S_<EditorID>, its items),
     so every converted NPC with that Skyrim outfit (face_fit.py --items-plugin) wears the same items.
Ids: S2SClothes_ids.json in --out keeps every record's FormID by EditorID across runs (new ones only ever added), and
which records each Skyrim item / outfit owns; items converted in earlier runs stay in the plugin (--replace-all drops
them). --test-npcs: a male and a female test NPC (the fixed bodies the gear is fitted to, face_fit BODY_NPC) wearing
the outfit. --dry-run: the meshes each sex would use, nothing written.
"""
import argparse
import json
import os
import shlex
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts", "npc"))

from fo4sf import bsa, sfplugin, skyrimarmor, skyrimnpc  # noqa: E402

PLUGIN = "S2SClothes.esm"
IDS = "S2SClothes_ids.json"
SEXES = ("male", "female")
TAG = {"male": "M", "female": "F"}
TEST_NPC = "S2S_ItemTest"


class IdMap:
    """FormIDs by EditorID, kept in a JSON file: a known EditorID keeps its id, a new one gets the next free id, and
    an id is never given to another EditorID (2026-11-09: plugins pointing at the items, the NPCs, must not move)."""

    def __init__(self, path: str, masters: int = 1, seed=()):
        self.path, self.masters = path, masters
        self.ids, self.owned = {}, {}
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.ids = {k: int(v, 16) for k, v in data.get("ids", {}).items()}
            self.owned = {k: list(v) for k, v in data.get("owned", {}).items()}
        for edid, fid in seed:                    # an existing plugin without its map: its ids are kept
            self.ids.setdefault(edid, fid & 0xFFFFFF)

    def __call__(self, edid: str) -> int:
        if edid not in self.ids:
            self.ids[edid] = max(list(self.ids.values()) + [sfplugin.FIRST_OBJECT - 1]) + 1
        return (self.masters << 24) | self.ids[edid]

    def save(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"plugin": PLUGIN, "ids": {k: f"{v:06X}" for k, v in sorted(self.ids.items())},
                       "owned": self.owned}, fh, indent=1)


def pair_parts(male, female):
    """[{"key", "skin", "slots", "male": row or None, "female": row or None}] from the two sexes' stage rows: the skin
    piece with the skin piece, then gear by shape name (case-insensitive), then by slots; the rest one sex each. Slots:
    the male part's (else the female's), then made distinct over the pairs (gear_fit.distinct_slots)."""
    import gear_fit
    import os_export
    m_left, f_left = [r for r in male if not r.get("skin")], [r for r in female if not r.get("skin")]
    pairs = []
    ms, fs = [r for r in male if r.get("skin")], [r for r in female if r.get("skin")]
    if ms or fs:
        pairs.append({"key": gear_fit.SKIN_SHAPE.decode(), "skin": True, "slots": None,
                      "male": ms[0] if ms else None, "female": fs[0] if fs else None})
    gear = []
    for same in (lambda a, b: a["shape"].lower() == b["shape"].lower(),
                 lambda a, b: a.get("slots") and a.get("slots") == b.get("slots")):
        for m in list(m_left):
            f = next((x for x in f_left if same(m, x)), None)
            if f is not None:
                gear.append((m, f))
                m_left.remove(m)
                f_left.remove(f)
    gear += [(m, None) for m in m_left] + [(None, f) for f in f_left]
    keys = set()
    for m, f in gear:
        key = os_export.part_slug((m or f)["shape"])
        if m is None:
            key += "_F"
        elif f is None:
            key += "_M"
        while key.lower() in keys:
            key += "_2"
        keys.add(key.lower())
        pairs.append({"key": key, "skin": False, "slots": (m or f).get("slots"), "male": m, "female": f})
    gear_pairs = [p for p in pairs if not p["skin"]]
    slots, notes = gear_fit.distinct_slots({p["key"]: p["slots"] for p in gear_pairs}, [p["key"] for p in gear_pairs])
    for p in gear_pairs:
        p["slots"] = slots.get(p["key"], p["slots"])
    return pairs, notes


def skyrim_outfits(esm: str, outfit_edids=(), npc_edids=()):
    """[{"edid", "armor": [ARMO FormIDs], "skipped", "npcs"}] for the given outfits and the NPCs' default outfits."""
    import os_convert
    recs = {fid: (t, s) for t, _h, s, fid in sfplugin.records(esm, [b"OTFT", b"LVLI", b"ARMO"])}
    by_edid = {sfplugin.edid(s).lower(): fid for fid, (t, s) in recs.items() if t == b"OTFT"}
    out, notes = {}, []
    wanted = [(e, None) for e in outfit_edids]
    if npc_edids:
        npcs = {skyrimnpc.parse_npc(s, fid)["edid"].lower(): skyrimnpc.parse_npc(s, fid)
                for _t, _h, s, fid in sfplugin.records(esm, [b"NPC_"])}
        for e in npc_edids:
            n = npcs.get(e.lower())
            if n is None:
                notes.append(f"{e}: no NPC with this EditorID")
            elif n.get("outfit") not in recs:
                notes.append(f"{e}: no default outfit")
            else:
                wanted.append((sfplugin.edid(recs[n["outfit"]][1]), n["edid"]))
    for e, npc in wanted:
        fid = by_edid.get(e.lower())
        if fid is None:
            notes.append(f"{e}: no OTFT with this EditorID")
            continue
        o = out.get(fid)
        if o is None:
            armor, skipped = os_convert.outfit_items(recs, fid)
            o = out[fid] = {"edid": sfplugin.edid(recs[fid][1]), "armor": armor, "skipped": skipped, "npcs": []}
        if npc:
            o["npcs"].append(npc)
    return list(out.values()), notes


def item_name(a: dict, strings: dict) -> str:
    return a.get("full") or strings.get(a.get("full_id") if a.get("full_id") is not None else -1) or a["edid"]


def stage_report(out: str, name: str) -> str:
    import gear_fit
    return os.path.join(out, f"gear_fit_{gear_fit.safe_name(name)}.json")


def fit_item(a, edid: str, sex: str, fit_args) -> dict:
    """gear_fit.py --stage for one item and sex: {"rows": stage rows} or {"error": why}."""
    import gear_fit
    name = f"Items\\{edid}_{TAG[sex]}"
    argv = ["--skyrim-data", a.skyrim_data, "--starfield", a.starfield, "--armor", edid, "--sex", sex,
            "--race", a.race, "--name", name, "--out", a.out, "--stage"] + (["--helmets"] if a.helmets else []) \
        + list(fit_args)
    print(f"--- {edid} ({sex}): gear_fit.py {' '.join(argv[8:])}")
    try:
        code = gear_fit.main(argv)
    except SystemExit as e:
        return {"error": str(e.code) if e.code not in (None, 0) else "stopped"}
    path = stage_report(a.out, name)
    if code or not os.path.isfile(path):
        return {"error": f"gear_fit returned {code} (report {path})"}
    with open(path, encoding="utf-8") as fh:
        rep = json.load(fh)
    rows = (rep.get("records") or {}).get("stage")
    if rows is None:
        return {"error": f"no parts in {path}"}
    return {"rows": rows, "meshes": [m.get("mesh") for m in rep.get("meshes", [])]}


FIT_CACHE = "_fit_cache.json"        # in --out: the inputs each item / sex fit was made from
FIT_VERSION = 1


def fit_key(a, edid: str, sex: str, fit_args) -> str:
    """A key for one item / sex fit: what shapes it (item, sex, race, --helmets, --fit-args) and the fitting code
    (gear_fit.py, src/fo4sf/gearfit.py, FIT_VERSION), so a run reuses a fit only when nothing that made it changed
    (2026-11-12, owner: an outfit two NPCs wear is converted once, and done steps are not redone)."""
    import hashlib
    import gear_fit
    from fo4sf import gearfit
    h = hashlib.sha1(repr((edid.lower(), sex, a.race, bool(a.helmets), list(fit_args), FIT_VERSION)).encode())
    for mod in (gear_fit, gearfit):
        with open(mod.__file__, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()


def load_fit_cache(out: str) -> dict:
    try:
        with open(os.path.join(out, FIT_CACHE), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def fit_or_reuse(a, edid: str, sex: str, fit_args, cache: dict) -> dict:
    """fit_item, or its earlier result when the same fit is in the cache, its stage report is still there and the
    staged files were not dropped (--refit: always fit). Updates cache on a new fit."""
    name = f"Items\\{edid}_{TAG[sex]}"
    key = fit_key(a, edid, sex, fit_args)
    path = stage_report(a.out, name)
    if not a.refit and cache.get(name) == key and os.path.isfile(path) \
            and os.path.isdir(os.path.join(a.out, "_staging")):
        try:
            with open(path, encoding="utf-8") as fh:
                rep = json.load(fh)
            rows = (rep.get("records") or {}).get("stage")
            if rows is not None:
                return {"rows": rows, "meshes": [m.get("mesh") for m in rep.get("meshes", [])], "reused": True}
        except (OSError, ValueError):
            pass
    f = fit_item(a, edid, sex, fit_args)
    if f.get("rows") is not None:
        cache[name] = key
    else:
        cache.pop(name, None)
    return f


def kept_records(path: str, dropped) -> list:
    """The records of an existing plugin whose EditorID is not in `dropped`."""
    if not os.path.isfile(path):
        return []
    drop = {e.lower() for e in dropped}
    types = [b"ARMA", b"MRPH", b"ARMO", b"OTFT", b"NPC_"]
    return [r for r in sfplugin.records(path, types) if sfplugin.edid(r[2]).lower() not in drop]


def test_npcs(sf_esm: str, outfit_fid: int, fid_of, label: str):
    """Two NPCs, copies of face_fit's fixed body NPCs (male, female: the bodies the gear is fitted to) without their
    templates, scripts and gear, wearing `outfit_fid` as default and space outfit."""
    import face_fit
    npcs = {sfplugin.edid(s).lower(): (t, h, s) for t, h, s, _fid in sfplugin.records(sf_esm, [b"NPC_"])}
    out, rows = [], []
    for sex, tpl_edid in zip(SEXES, face_fit.BODY_NPC):
        tpl = npcs.get(tpl_edid.lower())
        if tpl is None:
            rows.append({"sex": sex, "note": f"no NPC {tpl_edid} in Starfield.esm"})
            continue
        edid = f"{TEST_NPC}_{TAG[sex]}"
        o = struct.pack("<I", outfit_fid)
        subs = face_fit.without_templates(sfplugin.edit(tpl[2], {b"EDID": sfplugin.zs(edid),
                                                                  b"FULL": sfplugin.zs(f"{label} ({sex})")},
                                                        drop=face_fit.STRIP + face_fit.STRIP_GEAR))
        subs = sfplugin.edit(subs, {b"DOFT": o, b"SOFT": o})
        fid = fid_of(edid)
        out.append((b"NPC_", tpl[1], subs, fid))
        rows.append({"sex": sex, "edid": edid, "NPC": f"{fid:08X}", "template": tpl_edid})
    return out, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True, help="Starfield install folder")
    ap.add_argument("--out", required=True, help="the mod folder (outside the repository), e.g. $mods\\S2S Clothes")
    ap.add_argument("--armor", action="append", default=[], help="Skyrim ARMO EditorID (repeatable)")
    ap.add_argument("--outfit", action="append", default=[], help="Skyrim OTFT EditorID: its items and the outfit")
    ap.add_argument("--npc", action="append", default=[], help="Skyrim NPC EditorID: its default outfit, as --outfit")
    ap.add_argument("--race", default="NordRace", help="the Skyrim race whose addons are fitted")
    ap.add_argument("--sexes", default="male,female")
    ap.add_argument("--helmets", action="store_true", help="also head gear (gear_fit.py --helmets)")
    ap.add_argument("--fit-args", default="", help="more gear_fit.py options, e.g. \"--conform\"")
    ap.add_argument("--test-npcs", action="store_true", help="a male and a female test NPC wearing the first outfit "
                                                             "(or all converted items)")
    ap.add_argument("--replace-all", action="store_true", help="drop items converted in earlier runs from the plugin "
                                                               "(their ids stay reserved in the id file)")
    ap.add_argument("--archive2", default="")
    ap.add_argument("--refit", action="store_true",
                    help="fit every item again (default: an item / sex fitted before with the same inputs and code "
                         "is reused)")
    ap.add_argument("--dry-run", action="store_true", help="list each item's meshes per sex; write nothing")
    a = ap.parse_args(argv)
    if os.path.abspath(a.out).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    sexes = [s.strip() for s in a.sexes.split(",") if s.strip() in SEXES]
    if not sexes:
        ap.error("--sexes: male and / or female")
    esm = os.path.join(a.skyrim_data, "Skyrim.esm")
    sf_data = os.path.join(a.starfield, "Data")
    sf_esm = os.path.join(sf_data, "Starfield.esm")
    inv = skyrimarmor.read_armor(esm)
    by_edid = {x["edid"].lower(): fid for fid, x in inv["armo"].items() if x.get("edid")}
    outfits, notes = skyrim_outfits(esm, a.outfit, a.npc)
    edids = list(a.armor) + [inv["armo"][f]["edid"] for o in outfits for f in o["armor"] if f in inv["armo"]]
    edids = list(dict.fromkeys(e for e in edids if e.lower() in by_edid))
    notes += [f"{e}: no ARMO with this EditorID" for e in a.armor if e.lower() not in by_edid]
    for o in outfits:
        notes += [f"outfit {o['edid']}: {x} (not armor)" for x in o["skipped"]]
    for n in notes:
        print("  " + n)
    if not edids:
        sys.exit("nothing to convert (--armor / --outfit / --npc)")
    import os_convert
    if a.dry_run:
        for e in edids:
            for sex in sexes:
                m = os_convert.worn_meshes(inv, [by_edid[e.lower()]], a.race, sex == "female")
                print(f"{e} ({sex}): " + (", ".join(f"{x['mesh']} (addon {x['addon']}, slots {x['slots']})"
                                                     for x in m) or "no worn mesh"))
        for o in outfits:
            print(f"outfit {o['edid']}: {len(o['armor'])} items" + (f", worn by {', '.join(o['npcs'])}"
                                                                    if o["npcs"] else ""))
        return 0
    os.makedirs(a.out, exist_ok=True)
    plugin_path = os.path.join(a.out, PLUGIN)
    seed = [(sfplugin.edid(r[2]), r[3]) for r in kept_records(plugin_path, ())]
    ids = IdMap(os.path.join(a.out, IDS), 1, seed)
    staging = os.path.join(a.out, "_staging")
    if a.replace_all:
        shutil.rmtree(staging, ignore_errors=True)
    sky = bsa.SkyrimArchives(a.skyrim_data)
    import npc_records
    strings = npc_records.skyrim_names(sky)
    fit_args = shlex.split(a.fit_args)
    items, rep = [], {"items": {}, "notes": notes}
    fit_cache = {} if a.replace_all else load_fit_cache(a.out)
    for e in edids:
        armo = inv["armo"][by_edid[e.lower()]]
        fits = {sex: fit_or_reuse(a, armo["edid"], sex, fit_args, fit_cache) for sex in sexes}
        rows = {sex: fits[sex].get("rows") or [] for sex in sexes}
        pairs, slot_notes = pair_parts(rows.get("male", []), rows.get("female", []))
        rep["items"][armo["edid"]] = {"fits": {s: {k: v for k, v in f.items() if k != "rows"} for s, f in fits.items()},
                                      "slot_moves": slot_notes}
        if pairs:
            items.append({"edid": armo["edid"], "full": item_name(armo, strings), "pairs": pairs})
    import os_export
    _material, tpl_vertices = os_export.template_model(sf_data)
    recs, prep = os_export.item_records(sf_esm, items, [{"edid": o["edid"], "items": [
        inv["armo"][f]["edid"] for f in o["armor"] if f in inv["armo"]]} for o in outfits], ids, tpl_vertices)
    new_edids = [sfplugin.edid(r[2]) for r in recs]
    # what this run's items and outfits wrote last time goes (renamed parts too); everything else in the plugin stays
    old_owned = {x.lower() for k in list(edids) + [o["edid"] for o in outfits] for x in ids.owned.get(k, [])}
    for it in items:
        base = f"S2S_{it['edid']}".lower()
        ids.owned[it["edid"]] = [x for x in new_edids if x.lower() == base or x.lower().startswith(base + "_")]
    for o in outfits:
        ids.owned[o["edid"]] = [f"S2S_{o['edid']}"]
    tests = []
    if a.test_npcs:
        first = next((o for o in prep["outfits"] if o["OTFT"]), None)
        if first is not None:
            o_fid, label = int(first["OTFT"], 16), f"S2S {first['edid']}"
        else:
            o_fid = ids(f"{TEST_NPC}_Outfit")
            recs.append(os_export.outfit_record(os_export.part_templates(sf_esm), f"{TEST_NPC}_Outfit",
                                                [int(i["ARMO"], 16) for i in prep["items"] if i["ARMO"]], o_fid))
            label = "S2S item test"
        t_recs, tests = test_npcs(sf_esm, o_fid, ids, label)
        recs += t_recs
    new = {sfplugin.edid(r[2]).lower() for r in recs}
    keep = [] if a.replace_all else [r for r in kept_records(plugin_path, old_owned)
                                     if sfplugin.edid(r[2]).lower() not in new]
    info = sfplugin.header_info(sf_esm)
    with open(plugin_path, "wb") as fh:
        fh.write(sfplugin.build(keep + recs, info, author="Skyrim2Starfield clothes", masters=["Starfield.esm"]))
    ids.save()
    with open(os.path.join(a.out, FIT_CACHE), "w", encoding="utf-8") as fh:
        json.dump(fit_cache, fh, indent=1)
    reused = [f"{e} ({s_})" for e, r in rep["items"].items() for s_, f in r["fits"].items() if f.get("reused")]
    if reused:
        print(f"{len(reused)} item fits unchanged, reused (--refit to fit again): {', '.join(reused)}")
    packed = None
    if os.path.isdir(staging):
        import hair_pack
        base = os.path.splitext(PLUGIN)[0]
        packed = hair_pack.pack(staging, a.out, a.starfield, a.archive2 or None, f"{base} - Main.ba2",
                                f"{base} - Textures.ba2")
    rep.update(records=prep, test_npcs=tests, kept_from_plugin=len(keep), packed=packed,
               outfits=[{k: v for k, v in o.items() if k != "armor"} for o in outfits])
    with open(os.path.join(a.out, "item_convert.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1, default=str)
    print(f"{PLUGIN}: {len(recs)} records written, {len(keep)} kept from earlier runs; ids in {IDS}")
    for it in prep["items"]:
        print(f"{it['edid']} \"{it.get('full')}\": ARMO {it['ARMO']}  player.additem "
              f"xx{int(it['ARMO'], 16) & 0xFFFFFF:06X} 1" if it["ARMO"] else f"{it['edid']}: {it.get('note')}")
        for p in it["parts"]:
            print(f"  {p['key']}: slots {p['slots']}, male {(p['male'] or {}).get('model', '-')}, "
                  f"female {(p['female'] or {}).get('model', '-')}" + (f"  ({p['one_sex']} only)" if p["one_sex"]
                                                                        else ""))
    for e, r in rep["items"].items():
        for sex, f in r["fits"].items():
            if f.get("error"):
                print(f"  {e} ({sex}) not fitted: {f['error']}")
    for o in prep["outfits"]:
        print(f"outfit {o['edid']}: OTFT {o['OTFT']}, {len(o['items'])} items"
              + (f", missing {', '.join(o['missing'])}" if o["missing"] else ""))
    for t in tests:
        if t.get("NPC"):
            print(f"test NPC ({t['sex']}): player.placeatme xx{int(t['NPC'], 16) & 0xFFFFFF:06X}")
        else:
            print(f"test NPC ({t['sex']}): {t['note']}")
    print("textures:", packed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
