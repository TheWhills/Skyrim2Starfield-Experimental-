"""Skyrim's magic against Starfield's powers, record by record (read-only; owner 2026-11-09: "magic and casting").

    python -I scripts\\magic\\magic_survey.py --skyrim "$sky\\Skyrim.esm" --starfield "$sf\\Data\\Starfield.esm" ^
        --out C:\\Modding\\work\\magic

Layouts (xEdit wbDefinitionsTES5 / wbDefinitionsSF1, read 2026-11-09; supported, the survey's range checks test them
on the real files):
  Skyrim SPEL SPIT: u32 cost, u32 flags, u32 type (0 spell, 1 disease, 2 power, 3 lesser power, 4 ability, 5 poison,
    10 addiction, 11 voice), f32 charge time, u32 cast type (0 constant, 1 fire and forget, 2 concentration), u32
    delivery (0 self, 1 touch, 2 aimed, 3 target actor, 4 target location), f32 cast duration, f32 range, perk.
  Skyrim MGEF DATA: archetype u32 at 64, projectile at 72, casting type u32 at 80, delivery u32 at 84, magic skill
    (actor value index) s32 at 12.
  Starfield SPEL SPIT: u32 cost, u32 flags, u8 type at 8, f32 charge time, u8 cast type at 13, u8 target at 14.
  Starfield MGEF DATA: 18 form / actor-value fields (4 bytes each), script AI (8), archetype u32 at 80, spellmaking
    (8), base cost at 92, sound level, cast type u8 at 100, delivery u8 at 101.
  Skyrim PROJ DATA: u16 flags, u16 type (bits: 1 missile, 2 lobber, 4 beam, 8 flame, 0x10 cone, 0x20 barrier, 0x40
    arrow). Starfield PROJ PROD: ... a length-prefixed string at 81, f32, u32, then u8 type (0 missile, 1 lobber, 2
    beam, 3 flame, 4 cone, 5 barrier, 6 arrow, 7 plasma, 8 emitter).
Reports: Skyrim's spells by school, cast type, delivery, archetype and projectile type; Starfield's powers / spells
the same way; per Skyrim archetype whether Starfield has it (same enum entry) and uses it; per (cast type, delivery,
projectile type) whether any Starfield spell or effect works that way: what can be carried over as data, and what
needs new behaviour (casting animations: the melee graph's CastSelf / CastTarget slots, docs/armor/animation-port.md).
Writes magic_survey.json and magic_survey.md.
"""
import argparse
import json
import os
import struct
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import sfplugin  # noqa: E402

SPELL_TYPES = {0: "Spell", 1: "Disease", 2: "Power", 3: "Lesser Power", 4: "Ability", 5: "Poison", 6: "Enchantment",
               7: "Potion", 8: "Wort Craft", 9: "Leveled Spell", 10: "Addiction", 11: "Voice"}
CAST = {0: "Constant Effect", 1: "Fire and Forget", 2: "Concentration"}
DELIVERY = {0: "Self", 1: "Touch", 2: "Aimed", 3: "Target Actor", 4: "Target Location"}
SKY_ARCH = ["Value Modifier", "Script", "Dispel", "Cure Disease", "Absorb", "Dual Value Modifier", "Calm", "Demoralize",
            "Frenzy", "Disarm", "Command Summoned", "Invisibility", "Light", "Unknown 13", "Unknown 14", "Lock", "Open",
            "Bound Weapon", "Summon Creature", "Detect Life", "Telekinesis", "Paralysis", "Reanimate", "Soul Trap",
            "Turn Undead", "Guide", "Werewolf Feed", "Cure Paralysis", "Cure Addiction", "Cure Poison", "Concussion",
            "Value and Parts", "Accumulate Magnitude", "Stagger", "Peak Value Modifier", "Cloak", "Werewolf",
            "Slow Time", "Rally", "Enhance Weapon", "Spawn Hazard", "Etherealize", "Banish", "Spawn Scripted Ref",
            "Disguise", "Grab Actor", "Vampire Lord"]
SF_ARCH = ["Value Modifier", "Script", "Dispel", "Cure Disease", "Absorb", "Dual Value Modifier", "Calm", "Demoralize",
           "Frenzy", "Disarm", "Command Summoned", "Invisibility", "Light", "Darkness", "Nighteye", "Lock", "Open",
           "Bound Weapon", "Summon Creature", "Detect Life", "Telekinesis", "Paralysis", "Reanimate", "Soul Trap",
           "Turn Undead", "Guide", "Summon Duplicate", "Cure Paralysis", "Cure Addiction", "Cure Poison", "Concussion",
           "Stimpak", "Accumulate Magnitude", "Stagger", "Peak Value Modifier", "Cloak", "Command", "Slow Time", "Rally",
           "Enhance Weapon", "Spawn Hazard", "Etherealize", "Banish", "Spawn Scripted Ref", "Disguise", "Damage",
           "Immunity", "Permanent Reanimate", "Boostpack", "Chameleon", "Capacity Value Modifier", "Reset Flora",
           "Drop Resources", "Antigravity", "Track Damage", "Gravity Wielder"]
SKY_PROJ = {1: "Missile", 2: "Lobber", 4: "Beam", 8: "Flame", 0x10: "Cone", 0x20: "Barrier", 0x40: "Arrow"}
SF_PROJ = ["Missile", "Lobber", "Beam", "Flame", "Cone", "Barrier", "Arrow", "Plasma", "Emitter"]
# Skyrim actor value indices of the magic skills (UESP / xEdit ActorValueEnum)
SCHOOLS = {18: "Alteration", 19: "Conjuration", 20: "Destruction", 21: "Illusion", 22: "Restoration"}


def _u32(d, o):
    return struct.unpack_from("<I", d, o)[0] if len(d) >= o + 4 else None


def _s32(d, o):
    return struct.unpack_from("<i", d, o)[0] if len(d) >= o + 4 else None


def sky_effect(subs):
    d = dict(subs).get(b"DATA", b"")
    return {"edid": sfplugin.edid(subs), "archetype": _u32(d, 64), "projectile": _u32(d, 72),
            "cast": _u32(d, 80), "delivery": _u32(d, 84), "school": _s32(d, 12), "size": len(d)}


def sf_effect(subs):
    d = dict(subs).get(b"DATA", b"")
    return {"edid": sfplugin.edid(subs), "archetype": _u32(d, 80), "projectile": _u32(d, 60),
            "cast": d[100] if len(d) > 100 else None, "delivery": d[101] if len(d) > 101 else None, "size": len(d)}


def sky_spell(subs):
    d = dict(subs).get(b"SPIT", b"")
    return {"edid": sfplugin.edid(subs), "type": _u32(d, 8), "cast": _u32(d, 16), "delivery": _u32(d, 20),
            "effects": [_u32(dd, 0) for s, dd in subs if s == b"EFID"], "etyp": _u32(dict(subs).get(b"ETYP", b""), 0)}


def sf_spell(subs):
    d = dict(subs).get(b"SPIT", b"")
    return {"edid": sfplugin.edid(subs), "type": d[8] if len(d) > 8 else None, "cast": d[13] if len(d) > 13 else None,
            "delivery": d[14] if len(d) > 14 else None,
            "effects": [_u32(dd, 0) for s, dd in subs if s == b"EFID"], "etyp": _u32(dict(subs).get(b"ETYP", b""), 0)}


def sky_proj_type(subs):
    d = dict(subs).get(b"DATA", b"")
    t = struct.unpack_from("<H", d, 2)[0] if len(d) >= 4 else None
    return SKY_PROJ.get(t, f"0x{t:x}" if t is not None else None)


def _prod_at(d, size):
    """(type byte or None, string non-empty) reading the PROD string at 81 with a `size`-byte length prefix; None when
    the string is not a printable, zero-terminated one or the type is out of range."""
    if len(d) < 81 + size:
        return None, False
    n = struct.unpack_from("<H" if size == 2 else "<I", d, 81)[0]
    s = d[81 + size:81 + size + n]
    if n > 512 or len(s) != n or (n and (s[-1] != 0 or any(c < 32 or c > 126 for c in s[:-1]))):
        return None, False
    at = 81 + size + n + 8
    return (d[at] if at < len(d) and d[at] < len(SF_PROJ) else None), n > 1


def prod_prefix(all_subs):
    """The PROD string prefix size (2 or 4) that reads the most records with a non-empty string as valid."""
    votes = Counter()
    for subs in all_subs:
        d = dict(subs).get(b"PROD", b"")
        for size in (2, 4):
            t, nonempty = _prod_at(d, size)
            if t is not None and nonempty:
                votes[size] += 1
    return votes.most_common(1)[0][0] if votes else 2


def sf_proj_type(subs, size=None):
    """(type name, prefix size) of a Starfield PROD: the type byte follows a length-prefixed string at 81, a float and a
    u32. size: the file's prefix size (prod_prefix); without it, the first size that reads a valid string."""
    d = dict(subs).get(b"PROD", b"")
    for sz in ((size,) if size else (2, 4)):
        t, _ne = _prod_at(d, sz)
        if t is not None:
            return SF_PROJ[t], sz
    return None, None


def name(table, v):
    if v is None:
        return None
    if isinstance(table, dict):
        return table.get(v, str(v))
    return table[v] if 0 <= v < len(table) else str(v)


def in_range(values, top):
    vals = [v for v in values if v is not None]
    return round(sum(0 <= v < top for v in vals) / len(vals), 3) if vals else None


def survey(sky_esm, sf_esm):
    out = {}
    # ---- Skyrim
    recs = sfplugin.records(sky_esm, [b"SPEL", b"MGEF", b"PROJ", b"EQUP"])
    eff = {fid: sky_effect(s) for t, _h, s, fid in recs if t == b"MGEF"}
    proj = {fid: sky_proj_type(s) for t, _h, s, fid in recs if t == b"PROJ"}
    equip = {fid: sfplugin.edid(s) for t, _h, s, fid in recs if t == b"EQUP"}
    spells = [sky_spell(s) for t, _h, s, _f in recs if t == b"SPEL"]
    out["skyrim"] = summarise(spells, eff, proj, equip, SKY_ARCH, school=True)
    out["skyrim"]["layout_check"] = {
        "effect_DATA_sizes": dict(Counter(e["size"] for e in eff.values()).most_common(4)),
        "archetype_in_range": in_range([e["archetype"] for e in eff.values()], len(SKY_ARCH)),
        "cast_in_range": in_range([e["cast"] for e in eff.values()], 3),
        "delivery_in_range": in_range([e["delivery"] for e in eff.values()], 5),
        "spell_cast_in_range": in_range([s["cast"] for s in spells], 3)}
    # ---- Starfield
    recs = sfplugin.records(sf_esm, [b"SPEL", b"MGEF", b"PROJ", b"EQUP"])
    eff2 = {fid: sf_effect(s) for t, _h, s, fid in recs if t == b"MGEF"}
    proj2, sizes = {}, Counter()
    prefix = prod_prefix([s for t, _h, s, _f in recs if t == b"PROJ"])
    for t, _h, s, fid in recs:
        if t == b"PROJ":
            proj2[fid], size = sf_proj_type(s, prefix)
            sizes[size] += 1
    equip2 = {fid: sfplugin.edid(s) for t, _h, s, fid in recs if t == b"EQUP"}
    spells2 = [sf_spell(s) for t, _h, s, _f in recs if t == b"SPEL"]
    out["starfield"] = summarise(spells2, eff2, proj2, equip2, SF_ARCH, school=False)
    out["starfield"]["layout_check"] = {
        "effect_DATA_sizes": dict(Counter(e["size"] for e in eff2.values()).most_common(4)),
        "archetype_in_range": in_range([e["archetype"] for e in eff2.values()], len(SF_ARCH)),
        "cast_in_range": in_range([e["cast"] for e in eff2.values()], 3),
        "delivery_in_range": in_range([e["delivery"] for e in eff2.values()], 5),
        "projectile_string_prefix": {str(k): v for k, v in sizes.items()}}
    out["carry_over"] = compare(out["skyrim"], out["starfield"])
    return out


def summarise(spells, eff, proj, equip, arch_names, school):
    """Counts over the spells (type, cast, delivery, hand) and, for player-castable spells (type Spell), their effects'
    archetypes / schools / projectile types, plus every effect's archetype."""
    s = {"spells": len(spells), "effects": len(eff), "projectiles": len(proj),
         "spell_types": dict(Counter(name(SPELL_TYPES, x["type"]) for x in spells)),
         "projectile_types": dict(Counter(v for v in proj.values() if v))}
    castable = [x for x in spells if x["type"] in (0, 2, 3, 11)]
    s["castable"] = {"count": len(castable),
                     "by_cast_delivery": dict(Counter(f"{name(CAST, x['cast'])} / {name(DELIVERY, x['delivery'])}"
                                                       for x in castable).most_common()),
                     "by_hand": dict(Counter(equip.get(x["etyp"], "none") for x in castable).most_common())}
    arch, sch, ptypes, ways = Counter(), Counter(), Counter(), defaultdict(set)
    for x in castable:
        e = eff.get(x["effects"][0]) if x["effects"] else None
        if e is None:
            continue
        a = name(arch_names, e["archetype"])
        arch[a] += 1
        if school:
            sch[SCHOOLS.get(e.get("school"), "other")] += 1
        pt = proj.get(e["projectile"]) if e["projectile"] else None
        if pt:
            ptypes[pt] += 1
        ways[f"{name(CAST, x['cast'])} / {name(DELIVERY, x['delivery'])} / {pt or 'no projectile'}"].add(x["edid"])
    s["castable"]["by_archetype"] = dict(arch.most_common())
    if school:
        s["castable"]["by_school"] = dict(sch.most_common())
    s["castable"]["by_projectile_type"] = dict(ptypes.most_common())
    s["castable"]["ways"] = {k: {"count": len(v), "examples": sorted(v)[:6]} for k, v in
                             sorted(ways.items(), key=lambda kv: -len(kv[1]))}
    s["effect_archetypes"] = dict(Counter(name(arch_names, e["archetype"]) for e in eff.values()).most_common())
    return s


def compare(sky, sf):
    """Per Skyrim archetype used by castable spells: in Starfield's enum (same name) and how many Starfield effects
    use it; per Skyrim way of casting (cast / delivery / projectile type): Starfield spells cast that way."""
    have = sf["effect_archetypes"]
    arch = {a: {"skyrim_spells": n, "in_starfield_enum": a in SF_ARCH, "starfield_effects": have.get(a, 0)}
            for a, n in sky["castable"]["by_archetype"].items()}
    ways = {}
    for w, v in sky["castable"]["ways"].items():
        ways[w] = {"skyrim_spells": v["count"], "examples": v["examples"],
                   "starfield_spells": sf["castable"]["ways"].get(w, {}).get("count", 0)}
    return {"archetypes": arch, "ways": ways}


def report_md(r):
    sk, sf, co = r["skyrim"], r["starfield"], r["carry_over"]
    L = ["# Magic survey", "", f"Skyrim: {sk['spells']} spells, {sk['effects']} effects; castable "
         f"{sk['castable']['count']}. Starfield: {sf['spells']} spells, {sf['effects']} effects; castable "
         f"{sf['castable']['count']}.", "", "## Skyrim archetypes in castable spells", "",
         "| archetype | Skyrim spells | in Starfield's list | Starfield effects using it |", "|---|---|---|---|"]
    for a, x in co["archetypes"].items():
        L.append(f"| {a} | {x['skyrim_spells']} | {'yes' if x['in_starfield_enum'] else 'no'} | "
                 f"{x['starfield_effects']} |")
    L += ["", "## Ways of casting (cast type / delivery / projectile type)", "",
          "| way | Skyrim spells | Starfield spells | Skyrim examples |", "|---|---|---|---|"]
    for w, x in co["ways"].items():
        L.append(f"| {w} | {x['skyrim_spells']} | {x['starfield_spells']} | {', '.join(x['examples'])} |")
    L += ["", f"Skyrim schools: {sk['castable'].get('by_school')}", f"Skyrim hands: {sk['castable']['by_hand']}",
          f"Starfield hands: {sf['castable']['by_hand']}", f"Starfield projectile types: {sf['projectile_types']}",
          f"Layout checks: Skyrim {sk['layout_check']}; Starfield {sf['layout_check']}"]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True, help="Skyrim.esm")
    ap.add_argument("--starfield", required=True, help="Starfield.esm")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    r = survey(a.skyrim, a.starfield)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "magic_survey.json"), "w", encoding="utf-8") as fh:
        json.dump(r, fh, indent=1)
    with open(os.path.join(a.out, "magic_survey.md"), "w", encoding="utf-8") as fh:
        fh.write(report_md(r))
    sk, sf = r["skyrim"], r["starfield"]
    print(f"Skyrim: {sk['castable']['count']} castable spells; by school {sk['castable'].get('by_school')}")
    print(f"  by archetype {sk['castable']['by_archetype']}")
    print(f"Starfield: {sf['castable']['count']} castable; by archetype {sf['castable']['by_archetype']}")
    print(f"layout checks: Skyrim {sk['layout_check']}; Starfield {sf['layout_check']}")
    print(f"-> {os.path.join(a.out, 'magic_survey.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
