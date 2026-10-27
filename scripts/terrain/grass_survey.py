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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--models", type=int, default=6, help="vanilla grass models to describe")
    a = ap.parse_args(argv)
    data = os.path.join(a.starfield, "Data")
    esm = os.path.join(data, "Starfield.esm")
    recs = sfplugin.records(esm, [b"GRAS", b"GCVR", b"BIOM", b"LTEX", b"WRLD"])
    edid = {fid: sfplugin.edid(s) for _t, _h, s, fid in recs}
    gras, gcvr, biom = {}, {}, {}
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
    cover_ltex = Counter(x for g in gcvr.values() for x in g["ltex_ids"])
    biome_cover = Counter(e["gcvr"] for b in biom.values() for e in b["terrain"] if e["gcvr"])
    btd = btd_tables(data)
    painted_with_cover = {}
    for name, table in btd.items():
        hit = [edid.get(x, f"{x:08X}") for x in table if x in cover_ltex]
        if hit:
            painted_with_cover[name] = hit
    worlds = Counter(n.replace("\\", "/").split("/")[1] if "/" in n.replace("\\", "/") else n
                     for n in painted_with_cover)
    dens = [g["dnam"]["max_density"] for g in gras.values() if "dnam" in g]
    sizes = Counter(g["dnam_size"] for g in gras.values())
    models = find_models(data, sorted({g["model"] for g in gras.values() if g["model"]}), a.models)
    summary = {
        "grass_records": len(gras), "dnam_sizes": dict(sizes),
        "max_density_range": [min(dens), max(dens)] if dens else None,
        "ground_cover_records": len(gcvr), "gcvr_with_ltex": sum(1 for g in gcvr.values() if g["ltex_ids"]),
        "ltex_with_cover": len(cover_ltex), "biome_entries_with_cover": sum(biome_cover.values()),
        "gcvr_used_by_biomes": len(biome_cover), "gcvr_not_in_any_biome": len(set(gcvr) - set(biome_cover)),
        "btds": len(btd), "btds_painting_a_cover_texture": len(painted_with_cover),
        "btd_folders_painting_cover": dict(worlds.most_common(15)),
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
                   "btd_painting_cover": painted_with_cover}, fh, indent=1)
    print(json.dumps(summary, indent=1))
    print(f"\nreport: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
