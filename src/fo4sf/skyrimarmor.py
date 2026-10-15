"""Skyrim armor and clothing records (ARMO / ARMA) as an inventory for the armor conversion. Read-only.

Layouts follow xEdit's wbDefinitionsTES5.pas (dev-4.1.6, read 2026-10-15):
* ARMO: EDID, MOD2 / MOD4 (male / female WORLD model), BODT or BOD2 (biped flags u32, [BODT only: general flags u8 +
  3 unused], armor type u32: 0 light, 1 heavy, 2 clothing), RNAM race, MODL x n (the ARMA list), DATA (value i32,
  weight f32), DNAM armor rating i32 / 100, TNAM template armor (enchanted / variant copies point at their base).
* ARMA: EDID, BODT / BOD2, RNAM race, DNAM (male priority u8, female priority u8, weight slider male u8, female u8,
  2 unknown, detection sound u8, 1 unknown, weapon adjust f32; weight slider flag 0x02 = "Enabled": the engine then
  loads <model>_0.nif and _1.nif), MOD2 / MOD3 male / female third person, MOD4 / MOD5 male / female first person,
  MODL x n additional races.
* Biped flag bit i = slot 30 + i (30 Head, 31 Hair, 32 Body, 33 Hands, 34 Forearms, ... 61 FX01).
"""
import collections
import struct

from fo4sf import fo4land

SLOT_NAMES = {30: "Head", 31: "Hair", 32: "Body", 33: "Hands", 34: "Forearms", 35: "Amulet", 36: "Ring", 37: "Feet",
              38: "Calves", 39: "Shield", 40: "Tail", 41: "LongHair", 42: "Circlet", 43: "Ears",
              50: "DecapitateHead", 51: "Decapitate", 61: "FX01"}
ARMOR_TYPES = {0: "light", 1: "heavy", 2: "clothing"}
WEIGHT_SLIDER_ENABLED = 0x02
NON_PLAYABLE_RECORD = 0x4          # ARMO record header flag bit 2
DELETED = 0x20


def slots(flags: int) -> list:
    return [30 + i for i in range(32) if flags >> i & 1]


def slot_label(s: int) -> str:
    return f"{s} {SLOT_NAMES.get(s, 'Unnamed')}"


def _body_template(sig, d):
    """(biped flags, armor type or None, general flags) from BODT or BOD2."""
    flags, = struct.unpack_from("<I", d, 0)
    if sig == b"BOD2":
        return flags, (struct.unpack_from("<I", d, 4)[0] if len(d) >= 8 else None), 0
    general = d[4] if len(d) > 4 else 0
    return flags, (struct.unpack_from("<I", d, 8)[0] if len(d) >= 12 else None), general


def _records(p, sig):
    for item in fo4land.iter_items(p.buf, p.body, len(p.buf)):
        if item[0] == "GRUP" and item[3] == sig:
            for typ, off, flags, fid in fo4land.iter_items(p.buf, item[1] + 24, item[2]):
                if typ != "GRUP" and not flags & DELETED:
                    yield fid, flags, list(fo4land.iter_subrecords(fo4land.record_data(p.buf, off)))


def _edids(p, sig):
    out = {}
    for fid, _f, fields in _records(p, sig):
        for s, d in fields:
            if s == b"EDID":
                out[fid] = fo4land.zstring(d)
    return out


def read_armor(esm: str) -> dict:
    """{"armo": {fid: {...}}, "arma": {fid: {...}}} for every ARMO and ARMA in the plugin."""
    with fo4land.Plugin(esm) as p:
        races = _edids(p, b"RACE")
        armo, arma = {}, {}
        for fid, rflags, fields in _records(p, b"ARMO"):
            a = {"edid": "", "slots": [], "armor_type": None, "world_model": "", "world_model_female": "",
                 "race": None, "addons": [], "value": None, "weight": None, "rating": None, "template": None,
                 "non_playable": bool(rflags & NON_PLAYABLE_RECORD)}
            for s, d in fields:
                if s == b"EDID":
                    a["edid"] = fo4land.zstring(d)
                elif s in (b"BODT", b"BOD2"):
                    flags, kind, general = _body_template(s, d)
                    a["slots"], a["armor_type"] = slots(flags), ARMOR_TYPES.get(kind, kind)
                    a["non_playable"] |= bool(general & 0x10)
                elif s == b"MOD2":
                    a["world_model"] = fo4land.zstring(d)
                elif s == b"MOD4":
                    a["world_model_female"] = fo4land.zstring(d)
                elif s == b"RNAM":
                    a["race"] = races.get(struct.unpack_from("<I", d)[0], "%08X" % struct.unpack_from("<I", d)[0])
                elif s == b"MODL" and len(d) == 4:
                    a["addons"].append(struct.unpack_from("<I", d)[0])
                elif s == b"DATA" and len(d) >= 8:
                    a["value"], a["weight"] = struct.unpack_from("<if", d)
                elif s == b"DNAM" and len(d) >= 4:
                    a["rating"] = struct.unpack_from("<i", d)[0] / 100.0
                elif s == b"TNAM":
                    a["template"] = struct.unpack_from("<I", d)[0]
            armo[fid] = a
        for fid, _rflags, fields in _records(p, b"ARMA"):
            m = {"edid": "", "slots": [], "race": None, "extra_races": [], "male": "", "female": "",
                 "male_1st": "", "female_1st": "", "priority": (0, 0), "weight_slider": (False, False),
                 "dnam_raw": ""}
            for s, d in fields:
                if s == b"EDID":
                    m["edid"] = fo4land.zstring(d)
                elif s in (b"BODT", b"BOD2"):
                    m["slots"] = slots(_body_template(s, d)[0])
                elif s == b"RNAM":
                    rid = struct.unpack_from("<I", d)[0]
                    m["race"] = races.get(rid, "%08X" % rid)
                elif s == b"MODL" and len(d) == 4:
                    rid = struct.unpack_from("<I", d)[0]
                    m["extra_races"].append(races.get(rid, "%08X" % rid))
                elif s == b"DNAM" and len(d) >= 4:
                    m["priority"] = (d[0], d[1])
                    m["weight_slider"] = (bool(d[2] & WEIGHT_SLIDER_ENABLED), bool(d[3] & WEIGHT_SLIDER_ENABLED))
                    m["dnam_raw"] = bytes(d).hex()
                else:
                    key = {b"MOD2": "male", b"MOD3": "female", b"MOD4": "male_1st", b"MOD5": "female_1st"}.get(s)
                    if key:
                        m[key] = fo4land.zstring(d)
            arma[fid] = m
    return {"armo": armo, "arma": arma}


def worn_models(arma: dict) -> list:
    """The worn mesh files the engine loads for one ARMA: with the weight slider enabled, <model>_0.nif and
    <model>_1.nif (the record names either one; vanilla usually names _1), else the model itself."""
    out = []
    for key, slider in (("male", arma["weight_slider"][0]), ("female", arma["weight_slider"][1])):
        path = arma[key]
        if not path:
            continue
        low = path.lower()
        if slider and (low.endswith("_0.nif") or low.endswith("_1.nif")):
            stem = path[:-6]
            out += [stem + "_0.nif", stem + "_1.nif"]
        else:
            out.append(path)
    return list(dict.fromkeys(out))


def summary(inv: dict) -> dict:
    """Counts the armor conversion is sized by: records per armor type, slot usage, addon structure, races, distinct
    worn meshes (with weight variants), ARMO variants that only re-use a template's addons."""
    armo, arma = inv["armo"], inv["arma"]
    playable = [a for a in armo.values() if not a["non_playable"]]
    types = collections.Counter(a["armor_type"] for a in playable)
    slot_use = collections.Counter(slot_label(s) for a in playable for s in a["slots"])
    races = collections.Counter(m["race"] for m in arma.values())
    meshes = sorted({w for m in arma.values() for w in worn_models(m)})
    first = {m[k] for m in arma.values() for k in ("male_1st", "female_1st") if m[k]}
    missing_addons = sum(1 for a in armo.values() for f in a["addons"] if f not in arma)
    return {"armo": len(armo), "armo_playable": len(playable), "arma": len(arma),
            "armor_types": dict(types), "slots": dict(slot_use.most_common()),
            "multi_slot_armo": sum(1 for a in playable if len(a["slots"]) > 1),
            "armo_with_template": sum(1 for a in armo.values() if a["template"]),
            "addons_per_armo": dict(collections.Counter(len(a["addons"]) for a in armo.values())),
            "addons_not_in_plugin": missing_addons,
            "arma_races": dict(races.most_common(12)),
            "arma_weight_slider": sum(1 for m in arma.values() if any(m["weight_slider"])),
            "worn_meshes": len(meshes), "first_person_meshes": len(first),
            "female_specific_arma": sum(1 for m in arma.values() if m["female"] and m["female"] != m["male"])}
