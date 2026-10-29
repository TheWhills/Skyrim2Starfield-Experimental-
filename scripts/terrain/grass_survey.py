"""How Starfield grows its own grass (read-only): Grass (GRAS), Ground Cover (GCVR) and the biomes' terrain entries in
Starfield.esm, which landscape textures carry ground cover, whether hand-made worlds' BTDs paint any of them, and what
a vanilla grass model looks like. Decides whether Skyrim's grass can be grown by the engine on the Skyrim overlay
(docs/terrain/skyrim-objects.md "Native grass").

    python -I scripts\\terrain\\grass_survey.py --starfield "<Starfield>" --out C:\\Modding\\work\\grass_survey.json

Prints a summary; the JSON has every record. Paste the summary back.
"""
import argparse
import json
import os
import struct
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import ba2 as ba2mod  # noqa: E402
from fo4sf import landtex, sfgrass, sfplugin  # noqa: E402
from fo4sf import nif as nifmod  # noqa: E402


def zs(d):
    return bytes(d).split(b"\0")[0].decode("latin-1", "replace")


def btd_tables(sf_data: str):
    """{BTD name: [LTEX FormIDs]} of every vanilla BTD (headers only: they are stored uncompressed)."""
    out = {}
    for name in landtex.TERRAIN_ARCHIVES:
        path = os.path.join(sf_data, name)
        if not os.path.exists(path):
            continue
        arc = ba2mod.Ba2(path)
        with open(path, "rb") as f:
            for e in arc.entries:
                if not e.name.lower().endswith(".btd") or e.kind != "GNRL" or e.packed:
                    continue
                f.seek(e.offset)
                head = f.read(landtex.BTD_LTEX_TABLE + 4)
                if len(head) < landtex.BTD_LTEX_TABLE + 4:
                    continue
                k = struct.unpack_from("<I", head, landtex.BTD_LTEX_TABLE)[0]
                if k > 4096:
                    continue
                out[e.name] = list(struct.unpack(f"<{k}I", f.read(4 * k)))
    return out


def model_summary(raw: bytes) -> dict:
    n = nifmod.parse(raw)
    types = Counter(n.type_of(i) for i in range(len(n.blocks)))
    strings = [s.decode("latin-1", "replace") for s in n.strings]
    return {"bs_version": n.bs_version, "blocks": dict(types), "strings": strings[:20],
            "materials": [s for s in strings if s.lower().endswith(".mat")]}


def find_models(sf_data: str, models, limit: int):
    want = {("meshes/" + m.replace("\\", "/").lower().lstrip("/")): m for m in models}
    found = {}
    for f in sorted(os.listdir(sf_data)):
        if not (f.lower().startswith("starfield - meshes") and f.lower().endswith(".ba2")):
            continue
        try:
            a = ba2mod.Ba2(os.path.join(sf_data, f))
        except ba2mod.Ba2Error:
            continue
        for i, name in enumerate(a.names):
            key = name.replace("\\", "/").lower()
            if key in want and want[key] not in found:
                try:
                    found[want[key]] = dict(model_summary(a.read(i)), archive=f)
                except Exception as e:                       # noqa: BLE001 (reported)
                    found[want[key]] = {"error": f"{type(e).__name__}: {e}"}
                if len(found) >= limit:
                    return found
    return found


NO_GRASS, ALLOW_PROCGEN = 0x80, 0x08          # WRLD DATA bit 7, FNAM bit 3 (xEdit wbDefinitionsSF1)


def world_flag_info(subs) -> dict:
    d = dict((s, bytes(v)) for s, v in subs)
    data, fnam = d.get(b"DATA", b"\0")[0], d.get(b"FNAM", b"\0")[0]
    bn = d.get(b"BNAM")
    return {"data_flags": data, "no_grass": bool(data & NO_GRASS), "fnam_flags": fnam,
            "allow_procgen": bool(fnam & ALLOW_PROCGEN), "biome": f"{struct.unpack_from('<I', bn)[0]:08X}" if bn else None}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--models", type=int, default=6, help="vanilla grass models to describe")
    ap.add_argument("--plugin", action="append", default=[],
                    help="another plugin whose worldspaces' grass / procgen flags to report (e.g. the Skyrim terrain "
                         "plugin in Starfield\\Data); repeatable")
    ap.add_argument("--world", action="append", default=["LC172World", "NewAtlantis", "CityNewAtlantisLodge"],
                    help="vanilla worldspace EditorIDs to show the flags of")
    a = ap.parse_args(argv)
    data = os.path.join(a.starfield, "Data")
    esm = os.path.join(data, "Starfield.esm")
    recs = sfplugin.records(esm, [b"GRAS", b"GCVR", b"BIOM", b"LTEX", b"WRLD"])
    edid = {fid: sfplugin.edid(s) for _t, _h, s, fid in recs}
    gras, gcvr, biom, world_biome, world_flags = {}, {}, {}, {}, {}
    for t, _h, subs, fid in recs:
        if t == b"GRAS":
            d = dict((s, bytes(v)) for s, v in subs)
            row = {"edid": edid[fid], "model": zs(d.get(b"MODL", b"")), "dnam_size": len(d.get(b"DNAM", b"")),
                   "subrecords": [s.decode("latin-1") for s, _v in subs]}
            try:
                row["dnam"] = sfgrass.parse_gras_dnam(d.get(b"DNAM", b""))
            except ValueError as e:
                row["dnam_error"] = str(e)
            gras[fid] = row
        elif t == b"GCVR":
            g = sfgrass.parse_gcvr(subs)
            gcvr[fid] = {"edid": edid[fid], "grasses": [(edid.get(x, f"{x:08X}"), dn) for x, dn in g["grasses"]],
                         "ltex": [edid.get(x, f"{x:08X}") for x in g["ltex"]], "ltex_ids": g["ltex"],
                         "threshold": g["threshold"], "subrecords": [s.decode("latin-1") for s, _v in subs]}
        elif t == b"BIOM":
            biom[fid] = {"edid": edid[fid], "terrain": sfgrass.biome_terrain(subs)}
        elif t == b"WRLD":
            bn = next((struct.unpack_from("<I", bytes(d))[0] for s, d in subs if s == b"BNAM" and len(d) >= 4), None)
            if bn is not None:
                world_biome[edid[fid].lower()] = bn
            world_flags[edid[fid]] = world_flag_info(subs)
    cover_ltex = Counter(x for g in gcvr.values() for x in g["ltex_ids"])
    biome_cover = Counter(e["gcvr"] for b in biom.values() for e in b["terrain"] if e["gcvr"])
    btd = btd_tables(data)
    painted_with_cover = {}
    for name, table in btd.items():
        hit = [edid.get(x, f"{x:08X}") for x in table if x in cover_ltex]
        if hit:
            painted_with_cover[name] = hit
    # the biomes' own pairs {mask, LTEX, GCVR}: does a hand-made world paint a texture its biome gives ground cover?
    masks = Counter(e["mask"] for b in biom.values() for e in b["terrain"])
    covered_by = {}                                             # biome -> {LTEX: GCVR}
    any_cover = {}
    for bf, b in biom.items():
        for e in b["terrain"]:
            if e["gcvr"]:
                covered_by.setdefault(bf, {})[e["ltex"]] = e["gcvr"]
                any_cover.setdefault(e["ltex"], set()).add(e["gcvr"])
    own_hits, any_hits, no_biome = {}, {}, 0
    for name, table in btd.items():
        stem = os.path.splitext(os.path.basename(name.replace("\\", "/")))[0].lower()
        b = world_biome.get(stem)
        if b is None:
            no_biome += 1
        hit = [edid.get(x, f"{x:08X}") for x in table if x in covered_by.get(b, {})]
        if hit:
            own_hits[name] = {"world_biome": edid.get(b, f"{b:08X}"), "ltex": hit}
        hit = [edid.get(x, f"{x:08X}") for x in table if x in any_cover]
        if hit:
            any_hits[name] = hit
    worlds = Counter(n.replace("\\", "/").split("/")[1] if "/" in n.replace("\\", "/") else n
                     for n in painted_with_cover)
    dens = [g["dnam"]["max_density"] for g in gras.values() if "dnam" in g]
    sizes = Counter(g["dnam_size"] for g in gras.values())
    models = find_models(data, sorted({g["model"] for g in gras.values() if g["model"]}), a.models)
    ours = {}
    for pl in a.plugin:
        for _t, _h, subs, _f in sfplugin.records(pl, [b"WRLD"]):
            ours[f"{os.path.basename(pl)}:{sfplugin.edid(subs)}"] = world_flag_info(subs)
    summary = {
        "worlds": len(world_flags), "worlds_no_grass": sum(1 for w in world_flags.values() if w["no_grass"]),
        "worlds_allow_procgen": sum(1 for w in world_flags.values() if w["allow_procgen"]),
        "named_worlds": {w: world_flags.get(w) for w in a.world},
        "our_worlds": ours,
        "grass_records": len(gras), "dnam_sizes": dict(sizes),
        "max_density_range": [min(dens), max(dens)] if dens else None,
        "ground_cover_records": len(gcvr), "gcvr_with_ltex": sum(1 for g in gcvr.values() if g["ltex_ids"]),
        "ltex_with_cover": len(cover_ltex), "biome_entries_with_cover": sum(biome_cover.values()),
        "gcvr_used_by_biomes": len(biome_cover), "gcvr_not_in_any_biome": len(set(gcvr) - set(biome_cover)),
        "btds": len(btd), "btds_painting_a_cover_texture": len(painted_with_cover),
        "btd_folders_painting_cover": dict(worlds.most_common(15)),
        "biome_masks": {str(k): v for k, v in sorted(masks.items())},
        "worlds_with_biome": len(world_biome), "btds_without_a_world_biome": no_biome,
        "btds_painting_a_texture_their_biome_covers": len(own_hits),
        "btds_painting_a_texture_any_biome_covers": len(any_hits),
        "examples_own_biome": dict(list(own_hits.items())[:8]),
        "examples_any_biome": {k: v[:5] for k, v in list(any_hits.items())[:8]},
        "biome_ltex_with_cover": len(any_cover),
        "example_gcvr": next(({"edid": g["edid"], "grasses": g["grasses"][:6], "ltex": g["ltex"][:6],
                                "threshold": g["threshold"]} for g in gcvr.values() if g["ltex_ids"]), None),
        "example_gras": next(({k: v for k, v in g.items() if k != "subrecords"} for g in gras.values()
                              if "dnam" in g), None),
        "gras_subrecords": next((g["subrecords"] for g in gras.values()), None),
        "models": models,
    }
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "gras": {f"{k:08X}": v for k, v in gras.items()},
                   "gcvr": {f"{k:08X}": v for k, v in gcvr.items()},
                   "biomes": {f"{k:08X}": v for k, v in biom.items()},
                   "btd_painting_cover": painted_with_cover, "btd_own_biome_cover": own_hits,
                   "btd_any_biome_cover": any_hits,
                   "world_biome": {k: f"{v:08X}" for k, v in world_biome.items()},
                   "world_flags": world_flags}, fh, indent=1)
    print(json.dumps(summary, indent=1))
    print(f"\nreport: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
