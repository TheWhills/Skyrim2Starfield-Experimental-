"""Skyrim's own ground textures on Starfield terrain (make_skyrim_overlay.py build --skyrim-ground).

The BTD's LTEX table holds raw FormIDs. A new LTEX in a mod plugin has no fixed FormID at run time (its load-order
index varies), so instead the terrain plugin OVERRIDES spare Starfield.esm LTEX records: ones no vanilla BTD lists and
no biome / ground cover / planet / surface block record names. Each override keeps the vanilla record (material type,
friction) and points BNAM at a material made from a Skyrim landscape texture set (TXST TX00 diffuse, TX01 normal),
cloned from the plain ground's own vanilla material so the terrain shader sees what it expects. Vanilla planets do not
use those records, so they look the same.

Skyrim textures beyond the number of free records fall back to the converted texture of the same category with the
most coverage (else the category's Starfield pick). Supported hypothesis, not yet tested in game: that a terrain LTEX
override with a cloned single-layer material renders.
"""
import os
import struct
import zipfile
from typing import Dict, Iterable, List, Optional

from fo4sf import fo4land, landtex

REFERENCING = (b"BIOM", b"GCVR", b"PNDT", b"SFBK")      # records whose data may name an LTEX


def ltex_fields(sf_esm: str) -> Dict[int, dict]:
    """{LTEX form id: {"edid", "bnam"}} of every Starfield.esm LTEX."""
    out = {}
    with fo4land.Plugin(sf_esm) as p:
        rng = p.top_group(b"LTEX")
        if rng is None:
            return out
        for typ, off, _fl, fid in fo4land.iter_items(p.buf, *rng):
            if typ == "GRUP":
                continue
            rec = {"edid": "", "bnam": ""}
            for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
                if sig == b"EDID":
                    rec["edid"] = fo4land.zstring(d)
                elif sig == b"BNAM":
                    rec["bnam"] = fo4land.zstring(d)
            out[fid] = rec
    return out


def referenced(sf_esm: str, fids: Iterable[int], sigs=REFERENCING) -> set:
    """The fids that appear as a 4-byte value anywhere in the data of the given record types (top groups)."""
    want = {struct.pack("<I", f): f for f in fids}
    hit = set()
    with fo4land.Plugin(sf_esm) as p:
        for sig in sigs:
            rng = p.top_group(sig)
            if rng is None:
                continue
            for typ, off, _fl, _fid in fo4land.iter_items(p.buf, *rng):
                if typ == "GRUP":
                    continue
                data = fo4land.record_data(p.buf, off)
                for k, f in want.items():
                    if f not in hit and k in data:
                        hit.add(f)
    return hit


def free_slots(sf_esm: str, usage: Dict[int, int], fields: Optional[Dict[int, dict]] = None) -> List[int]:
    """Starfield.esm LTEX records safe to override: listed by no vanilla BTD, named by no REFERENCING record, not the
    plain ground. Sorted by FormID (stable between builds)."""
    fields = fields if fields is not None else ltex_fields(sf_esm)
    cand = [f for f in sorted(fields) if usage.get(f, 0) == 0 and f != landtex.PLAIN_GROUND]
    used = referenced(sf_esm, cand)
    return [f for f in cand if f not in used]


def coverage(cells) -> Dict[int, float]:
    """{Skyrim LTEX: summed weight over the map} from landtex.read_world_textures cells."""
    tot: Dict[int, float] = {}
    for ws in cells.values():
        for fid, w in ws.items():
            tot[fid] = tot.get(fid, 0.0) + float(w.sum())
    return tot


def plan(ltex: Dict[int, dict], cov: Dict[int, float], slots: List[int]):
    """(chosen [(skyrim fid, slot fid)], fallback {skyrim fid: chosen skyrim fid}): the most-covering Skyrim textures
    with a diffuse get the free slots in order; every other covered Skyrim texture borrows the chosen one of its
    category with the most coverage (absent: no entry, the category's Starfield pick applies)."""
    ranked = [f for f in sorted(cov, key=lambda f: -cov[f]) if f in ltex and ltex[f].get("diffuse") and cov[f] > 0]
    chosen = list(zip(ranked, slots))
    picked = {f for f, _s in chosen}
    best = {}
    for f, _s in chosen:
        c = landtex.category(ltex[f]["edid"], ltex[f]["diffuse"])
        best.setdefault(c, f)                       # ranked order: first is the most covering
    fallback = {}
    for f in ranked:
        if f not in picked:
            c = landtex.category(ltex[f]["edid"], ltex[f]["diffuse"])
            if c in best:
                fallback[f] = best[c]
    return chosen, fallback


def template_material(content_resources: str, bnam: str) -> dict:
    """The vanilla material a Starfield LTEX names (BNAM), read from the Creation Kit's ContentResources.zip."""
    import json
    want = bnam.replace("\\", "/").lower().lstrip("/")
    base = want.rsplit("/", 1)[-1]
    with zipfile.ZipFile(content_resources) as z:
        names = z.namelist()
        hit = next((n for n in names if n.lower().endswith(want)), None) or \
            next((n for n in names if n.lower().rsplit("/", 1)[-1] == base), None)
        if hit is None:
            raise FileNotFoundError(f"ground material {bnam!r} not in {os.path.basename(content_resources)}")
        mat = json.loads(z.read(hit).decode("utf-8-sig"))
    if "Layer1" not in mat.get("Summary", {}):
        raise ValueError(f"ground material {hit} is not a single-layer material (Summary: {list(mat.get('Summary', {}))})")
    return mat


def texture_path(p: str) -> str:
    """A Skyrim TXST path as the archives store it: TXST values omit the leading 'textures\\' folder."""
    p = (p or "").replace("/", "\\").lstrip("\\")
    return p if not p or p.lower().startswith("textures\\") else "textures\\" + p


def bnam_for(material_rel: str, vanilla_bnam: str) -> str:
    """Our staged material path ('materials\\skyrim\\ground\\x.mat') written the way vanilla BNAM values are."""
    rel = material_rel.replace("/", "\\")
    if not vanilla_bnam.lower().replace("/", "\\").startswith("materials\\") and rel.lower().startswith("materials\\"):
        rel = rel[len("materials\\"):]
    return rel
