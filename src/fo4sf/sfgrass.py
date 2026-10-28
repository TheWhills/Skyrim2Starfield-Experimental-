"""Starfield's run-time grass records, for growing Skyrim's grass the way the engine grows its own (instead of the baked
patch statics of skyrimgrass.py). Record layouts from xEdit's wbDefinitionsSF1 (read for the format only; offsets of
GRAS DNAM worked out from its field list, to be confirmed by scripts/terrain/grass_survey.py on Starfield.esm):

* GRAS (Grass): EDID, OBND, ODTY, OPDS, XALG, components, MODL (+ model fields), DNAM (38 bytes): contrast f32,
  cluster scale f32, height range f32, colour range f32, wind frequency f32, above-water clamp f32, below-water clamp
  f32, max density u8 (28), min slope u8, max slope u8, flags u8 (1 vertex lighting, 2 uniform scaling, 4 fits slope,
  8 apply between), coverage f32 (32), dirtiness min u8, dirtiness max u8.
* GCVR (Ground Cover): EDID, (GNAM grass FormID, DNAM s16 override density, -1 = the grass's own) repeated, LNAM
  landscape textures it grows on (repeated), YNAM painted-material threshold f32 (default 28).
* BIOM (Biome) terrain data: LNAM / ANAM {mask u32, LTEX, GCVR}: a planet biome's ground textures and their cover.

Skyrim's GRAS (skyrimgrass.parse_gras_data) has the same core fields: density (percent), slopes, height range, colour
range, flags with the same bit meanings (1 vertex lighting, 2 uniform scaling, 4 fit to slope).
"""
import struct
from typing import Dict, Iterable, List, Optional, Tuple

DNAM_SIZE = 38
FLAG_BITS = 0x7                       # vertex lighting, uniform scaling, fits slope: same bits in both games


def parse_gras_dnam(d: bytes) -> Dict:
    if len(d) < DNAM_SIZE:
        raise ValueError(f"GRAS DNAM is {len(d)} bytes, expected {DNAM_SIZE}")
    f = struct.unpack_from("<7f", d, 0)
    dens, lo, hi, flags = struct.unpack_from("<4B", d, 28)
    cov, = struct.unpack_from("<f", d, 32)
    dmin, dmax = struct.unpack_from("<2B", d, 36)
    return {"contrast": f[0], "cluster_scale": f[1], "height_range": f[2], "colour_range": f[3],
            "wind_frequency": f[4], "above_water_clamp": f[5], "below_water_clamp": f[6], "max_density": dens,
            "min_slope": lo, "max_slope": hi, "flags": flags, "coverage": cov, "dirtiness_min": dmin,
            "dirtiness_max": dmax}


def gras_dnam_from_skyrim(template_dnam: bytes, sky: Dict, density_scale: float = 1.0) -> bytes:
    """The template GRAS's DNAM with Skyrim's density, slopes, height / colour range and flags written in; the
    Starfield-only fields (contrast, cluster scale, wind, water clamps, coverage, dirtiness) stay the template's."""
    b = bytearray(template_dnam)
    if len(b) < DNAM_SIZE:
        raise ValueError(f"template GRAS DNAM is {len(b)} bytes, expected {DNAM_SIZE}")
    struct.pack_into("<2f", b, 8, float(sky["height_range"]), float(sky["colour_range"]))
    dens = max(0, min(255, int(round(sky["density"] * density_scale))))
    flags = (b[31] & ~FLAG_BITS) | (sky["flags"] & FLAG_BITS)
    struct.pack_into("<4B", b, 28, dens, int(sky["min_slope"]), int(sky["max_slope"]), flags)
    return bytes(b)


def parse_gcvr(subs) -> Dict:
    grasses, ltex, thr = [], [], None
    for s, d in subs:
        d = bytes(d)
        if s == b"GNAM" and len(d) >= 4:
            grasses.append([struct.unpack_from("<I", d)[0], -1])
        elif s == b"DNAM" and len(d) >= 2 and grasses:
            grasses[-1][1] = struct.unpack_from("<h", d)[0]
        elif s == b"LNAM" and len(d) >= 4:
            ltex.append(struct.unpack_from("<I", d)[0])
        elif s == b"YNAM" and len(d) >= 4:
            thr = struct.unpack_from("<f", d)[0]
    return {"grasses": [tuple(g) for g in grasses], "ltex": ltex, "threshold": thr}


def build_gcvr(template_subs, edid: bytes, grasses: Iterable[Tuple[int, int]], ltex: Iterable[int],
               threshold: Optional[float] = None) -> List[Tuple[bytes, bytes]]:
    """A GCVR from a template: its other fields kept, the grass list, texture list (and threshold) replaced."""
    head, tail, placed = [], [], False
    for s, d in template_subs:
        if s in (b"GNAM", b"DNAM", b"LNAM"):
            placed = True
            continue
        if s == b"EDID":
            head.append((s, edid))
        elif s == b"YNAM":
            tail.append((s, struct.pack("<f", threshold) if threshold is not None else bytes(d)))
        elif placed:
            tail.append((s, bytes(d)))
        else:
            head.append((s, bytes(d)))
    body = []
    for g, dens in grasses:
        body += [(b"GNAM", struct.pack("<I", g)), (b"DNAM", struct.pack("<h", int(dens)))]
    body += [(b"LNAM", struct.pack("<I", f)) for f in ltex]
    if threshold is not None and not any(s == b"YNAM" for s, _d in tail):
        tail.append((b"YNAM", struct.pack("<f", threshold)))
    return head + body + tail


def biome_terrain(subs) -> List[Dict]:
    """The LNAM / ANAM entries of a BIOM: [{"kind", "mask", "ltex", "gcvr"}]."""
    out = []
    for s, d in subs:
        d = bytes(d)
        if s in (b"LNAM", b"ANAM") and len(d) >= 12:
            m, lt, gc = struct.unpack_from("<3I", d)
            out.append({"kind": s.decode(), "mask": m, "ltex": lt, "gcvr": gc})
    return out


def biome_with_cover(subs, entries: Iterable[Tuple[int, int]], mask: Optional[int] = None,
                     masks: Optional[Iterable[int]] = None):
    """A BIOM's subrecords with LNAM {mask, LTEX, GCVR} entries added after its last LNAM: one per LTEX with `mask`
    (default: the first existing entry's), or one per LTEX and mask in `masks`. Entries for an LTEX the biome already
    lists replace that entry's ground cover."""
    subs = [(s, bytes(d)) for s, d in subs]
    have = biome_terrain(subs)
    if mask is None:
        mask = next((e["mask"] for e in have if e["kind"] == "LNAM"), 0)
    want = dict(entries)
    out, last = [], None
    for s, d in subs:
        if s == b"LNAM" and len(d) >= 12:
            m, lt, gc = struct.unpack_from("<3I", d)
            if lt in want:
                d = struct.pack("<3I", m, lt, want.pop(lt)) + d[12:]
            out.append((s, d))
            last = len(out)
            continue
        out.append((s, d))
    use = list(masks) if masks is not None else [mask]
    add = [(b"LNAM", struct.pack("<3I", m, lt, gc)) for lt, gc in want.items() for m in use]
    at = last if last is not None else next((i + 1 for i, (s, _d) in enumerate(out) if s == b"TNAM"), len(out))
    out[at:at] = add
    return out


def cover_plan(mapping_skyrim: Dict, overrides: List[Dict], ltex_grass: Dict[int, List[int]],
               sky_ltex_edid: Dict[int, str], coverage: Optional[Dict[str, float]] = None) -> Dict:
    """Which Starfield LTEX gets which Skyrim grasses: {"slots": {sf LTEX fid: [Skyrim GRAS fids]}, "skipped": [...]}.

    mapping_skyrim: ltex_mapping.json "skyrim" ({key: {"edid", "starfield"}}); overrides: overlays_params.json
    "ltex_overrides" ([{"form_id", "skyrim"}]: the spare Starfield.esm LTEX records the terrain overrides with Skyrim
    textures, named SKYG_<Skyrim EditorID>). Only those spare records get ground cover: a vanilla LTEX that a Skyrim
    texture borrowed is painted on vanilla planets too, so cover there would grow Skyrim grass across the game."""
    slot_of = {"SKYG_" + o["skyrim"]: int(o["form_id"]) for o in overrides}
    by_edid = {e: fid for fid, e in sky_ltex_edid.items()}
    slots: Dict[int, List[int]] = {}
    skipped = []
    for v in mapping_skyrim.values():
        sky_fid = by_edid.get(v.get("edid"))
        grass = ltex_grass.get(sky_fid, []) if sky_fid is not None else []
        if not grass:
            continue
        slot = slot_of.get(v.get("starfield"))
        if slot is None:
            skipped.append({"skyrim": v.get("edid"), "starfield": v.get("starfield"),
                            "why": "painted with a vanilla Starfield texture (would grow on vanilla planets)"})
            continue
        lst = slots.setdefault(slot, [])
        lst += [g for g in grass if g not in lst]
    return {"slots": slots, "skipped": skipped}
