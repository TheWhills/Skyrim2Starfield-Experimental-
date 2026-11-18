"""A converted creature as a race of its own (docs/npc/creatures.md, "own race"): S2SCreatures.esm with copies of a
vanilla creature's RACE, skin (ARMO), skin addon (ARMA) and NPC, every file path the copies name moved from the
vanilla creature's folder to ours (same relative path), so the converted skeleton, rig, clips and body sit beside the
vanilla ones instead of replacing them.

What is redirected (verified on CritterRace 000176B6 in the owner's probe, 2026-11-17): the race's ANAM skeleton,
NAM5 rig, DNAM default animation folder and its subgraph entries' SAPT folders; the addon's model paths (MOD2-MOD5).
Graph paths (NAM6, SGNM) stay the vanilla creature's: the same behaviour drives our clips. The race keeps its own
subgraph entries and no SRAC (subgraph template race), so the game needs this race's own animation data: the Creation
Kit's GenerateAnimInfo run over S2SCreatures.esm (docs/OWNER-SETUP.md). A copied race without that data stood in the
reference pose (race_heads, 2026-11-09).
Records reference each other through 4-byte fields (RACE RNAM armor race and WNAM skin, ARMO RNAM and its addon,
ARMA RNAM, NPC RNAM / WNAM): every 4-byte field holding one of the vanilla FormIDs is pointed at our copy.
Starfield.esm is localized and this plugin is not: FULL becomes text, DESC is dropped (sfplugin).
"""
import struct
from typing import Dict, List, Tuple

from . import sfplugin

RACE_PATHS = (b"ANAM", b"NAM5", b"DNAM", b"SAPT")
MODEL_PATHS = (b"MOD2", b"MOD3", b"MOD4", b"MOD5")


def redirect(path: str, old_prefix: str, new_prefix: str) -> str:
    """path with old_prefix (case-insensitive, either slash) replaced by new_prefix; unchanged when it does not start
    with it. The rest keeps its own case."""
    p = path.replace("/", "\\")
    old = old_prefix.replace("/", "\\").rstrip("\\") + "\\"
    if not p.lower().startswith(old.lower()):
        return path
    return new_prefix.replace("/", "\\").rstrip("\\") + "\\" + p[len(old):]


def _text(d: bytes) -> str:
    return d.split(b"\0", 1)[0].decode("utf-8", "replace")


def retarget_record(subs, fid_map: Dict[int, int], path_sigs, old_prefix: str, new_prefix: str, edid: str,
                    name=None, drop=(b"DESC", b"SRAC")) -> Tuple[List[Tuple[bytes, bytes]], List[str]]:
    """(subrecords, changes) of a copied record: EDID set, FULL set to `name` (text) when given, `drop` removed, the
    path fields `path_sigs` redirected, and every 4-byte field naming a FormID of fid_map pointed at its copy."""
    out, changes = [], []
    for s, d in subs:
        if s in drop:
            changes.append(f"{s.decode()} dropped")
            continue
        if s == b"EDID":
            out.append((s, sfplugin.zs(edid)))
            continue
        if s == b"FULL" and name is not None:
            out.append((s, sfplugin.zs(name)))
            continue
        if s in path_sigs:
            old = _text(d)
            new = redirect(old, old_prefix, new_prefix)
            if new != old:
                changes.append(f"{s.decode()} {old} -> {new}")
                d = sfplugin.zs(new)
        elif len(d) == 4:
            v, = struct.unpack("<I", d)
            if v in fid_map:
                changes.append(f"{s.decode()} {v:08X} -> {fid_map[v]:08X}")
                d = struct.pack("<I", fid_map[v])
        out.append((s, d))
    if name is not None and not any(s == b"FULL" for s, _d in out):
        out.insert(1, (b"FULL", sfplugin.zs(name)))
    return out, changes


def build_plugin(race, skin, addon, npc, info: Dict, old_prefix: str, new_prefix: str, name: str,
                 prefix: str = "S2S_Chicken") -> Tuple[bytes, Dict]:
    """S2SCreatures.esm bytes and a report. race / skin / addon / npc: the vanilla records as sfplugin.records gives
    them, (type, header, subs, FormID). New FormIDs: race, skin, addon, NPC = this plugin's objects 0-3."""
    olds = [race[3], skin[3], addon[3], npc[3]]
    news = [sfplugin.new_form_id(i) for i in range(4)]
    fid_map = dict(zip(olds, news))
    rep = {"form_ids": {}, "changes": {}}
    recs = []
    for (typ, header, subs, _fid), new, edid, nm, paths in (
            (race, news[0], f"{prefix}Race", name, RACE_PATHS),
            (skin, news[1], f"{prefix}_Skin", None, ()),
            (addon, news[2], f"{prefix}_SkinAA", None, MODEL_PATHS),
            (npc, news[3], prefix, name, ())):
        s2, ch = retarget_record(subs, fid_map, paths, old_prefix, new_prefix, edid, nm)
        recs.append((typ, header, s2, new))
        rep["form_ids"][edid] = f"{new:08X}"
        rep["changes"][edid] = ch
    return sfplugin.build(recs, info), rep


def find_chain(recs_by_type: Dict[bytes, list], race_edid: str, npc_fid: int):
    """(race, skin, addon, npc) records: the race by EditorID, its skin by WNAM, the skin's first addon (the first
    4-byte field naming an ARMA), the NPC by FormID. Raises KeyError naming what is missing."""
    race = next((r for r in recs_by_type.get(b"RACE", []) if sfplugin.edid(r[2]) == race_edid), None)
    if race is None:
        raise KeyError(f"RACE {race_edid}")
    wnam = next((struct.unpack("<I", d)[0] for s, d in race[2] if s == b"WNAM" and len(d) == 4), None)
    skin = next((r for r in recs_by_type.get(b"ARMO", []) if r[3] == wnam), None)
    if skin is None:
        raise KeyError(f"ARMO {wnam!r} (the race's skin)")
    arma = {r[3]: r for r in recs_by_type.get(b"ARMA", [])}
    addon = next((arma[v] for s, d in skin[2] if len(d) == 4 for v in struct.unpack("<I", d) if v in arma), None)
    if addon is None:
        raise KeyError("ARMA (the skin's addon)")
    npc = next((r for r in recs_by_type.get(b"NPC_", []) if r[3] == npc_fid), None)
    if npc is None:
        raise KeyError(f"NPC_ {npc_fid:08X}")
    return race, skin, addon, npc
