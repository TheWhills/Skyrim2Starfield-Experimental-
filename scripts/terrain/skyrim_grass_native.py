"""Test of Skyrim's grass grown by Starfield's own grass system instead of baked patches (docs/terrain/skyrim-objects.md
"Native grass"). Builds an MO2 mod with S2SGrass.esm:
  * one Starfield Grass (GRAS) per Skyrim grass used on the converted ground: a vanilla GRAS copied, its model the
    converted Skyrim grass model (single instance, as Skyrim's), Skyrim's density / slopes / height and colour range /
    flags written in (fo4sf.sfgrass);
  * one Ground Cover (GCVR) per spare Starfield LTEX the Skyrim terrain overrides (SKYG_..., overlays_params.json
    "ltex_overrides"), listing the grasses of the Skyrim textures painted with it (ltex_mapping.json) and that LTEX;
    textures that fell back to a vanilla Starfield LTEX get no cover (it would grow on vanilla planets);
  * an override of the Skyrim world's biome (--biome, default: the one the terrain build gave the world) adding a
    {mask, LTEX, GCVR} terrain entry per spare LTEX and terrain mask (--biome-masks). The grass survey (2026-10-28)
    found every vanilla ground cover reached through biomes, none through its own texture list, and the planet-trait
    overlay BTDs (overlaytrait*) painting exactly textures their biomes pair with ground cover: the supported route
    for an overlay. Side effect, test only: the planet generator may also paint those Skyrim textures on planets of
    that biome.
Use it with a terrain build staged with --no-grass (make_skyrim_objects.py stage), so only the engine's grass shows.

2026-11-22 (owner: grass as a Starfield grass type, with its fading): the October test added the cover to the
world's land biome (ForestDeciduousLifeJemison) and grew nothing. But Nirn's biome map is ocean everywhere (make_planet
--land-px 0), so the biome under Riverwood is Nirn's ocean biome (NirnOceanNoCoating, our copy of OceanLife04 in the
planet plugin): its slime coat once covered every Riverwood object, i.e. the engine applies the planet's biome at the
spot to the overlay. Supported hypothesis: ground cover comes from that biome too. --biome planet (now the default)
adds the {mask, LTEX, GCVR} entries to that biome (our own record: no vanilla planet changes); the plugin then has the
terrain and planet plugins as masters and must load after them. --control grows one vanilla Jemison ground cover on
every converted Skyrim texture instead (no Skyrim models): grass there and none with Skyrim's points at our models,
none either way at the route. Without ltex_mapping.json (the October staging kept none) the Skyrim -> Starfield
texture mapping is read off the installed terrain (refresh_btd.infer_mapping).

    python -I scripts\\terrain\\skyrim_grass_native.py --skyrim "<Skyrim SE>\\Data\\Skyrim.esm"
        --skyrim-data "<Skyrim SE>\\Data" --starfield "<Starfield>" --terrain <overlay build folder>
        --texconv <texconv.exe> --out "<MO2 mods>\\S2S Grass Native" [--tints <work>\\grass\\grass.json] [--biome <EDID>]
"""
import argparse
import json
import os
import re
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "scripts"))
sys.path.insert(0, os.path.join(REPO, "scripts", "armor"))
sys.path.insert(0, HERE)

from fo4sf import bsa, sfgrass, sfplugin, skyrimconvert, skyrimgrass, skyrimnif  # noqa: E402
from fo4sf import nif as nifmod  # noqa: E402

PLUGIN = "S2SGrass.esm"
PREFIX = "s2s"
VANILLA_OCEAN = 0x07F88A      # OceanLife04: the biome under the overlay when make_planet kept its coating
VANILLA_LAND = 0x1CBD6A       # ForestDeciduousLifeJemison: where --control takes its vanilla ground cover from


def mapping_from_fids(fids, sky_edid, overrides):
    """ltex_mapping.json's "skyrim" form from {Skyrim LTEX: Starfield LTEX} (refresh_btd.infer_mapping): a converted
    slot is named SKYG_<Skyrim EditorID> as the overrides list it, any other (vanilla) LTEX by its hex FormID."""
    slot = {int(o["form_id"]): "SKYG_" + o["skyrim"] for o in overrides}
    return {str(f): {"edid": sky_edid.get(f, f"{f:08X}"), "starfield": slot.get(int(sf), f"{int(sf):08X}")}
            for f, sf in fids.items()}


def location_biome(planet_recs, n_masters=2):
    """The planet plugin's own biome that lies under the overlay: make_planet's <Name>OceanNoCoating (the biome map is
    ocean everywhere), else its only own biome, else None (the vanilla ocean then)."""
    own = [r for r in planet_recs if r[0] == b"BIOM" and r[3] >> 24 == n_masters]
    for r in own:
        if sfplugin.edid(r[2]).lower().endswith("oceannocoating"):
            return r
    return own[0] if len(own) == 1 else None


def control_cover(biome_subs):
    """The ground cover a vanilla biome pairs with its textures most often (FormID, 0 if none)."""
    from collections import Counter
    c = Counter(e["gcvr"] for e in sfgrass.biome_terrain(biome_subs) if e["gcvr"])
    return c.most_common(1)[0][0] if c else 0


def pick(recs, sig, rx=None, need=None):
    for t, h, subs, fid in sorted(recs, key=lambda r: sfplugin.edid(r[2])):
        if t != sig:
            continue
        if rx and not re.search(rx, sfplugin.edid(subs), re.I):
            continue
        if need is None or need(subs):
            return (t, h, subs, fid)
    return None


def gras_ok(subs):
    d = dict((s, bytes(v)) for s, v in subs)
    return b"MODL" in d and len(d.get(b"DNAM", b"")) >= sfgrass.DNAM_SIZE


def convert_model(conv, name: str, tint, staging: str) -> str:
    """The Skyrim grass model as one Starfield static model (materials with Skyrim's tint, back faces when double
    sided); returns its path under meshes\\."""
    raw = conv.src.mesh(name)
    if raw is None:
        raise FileNotFoundError("not in the Skyrim archives")
    src = nifmod.parse(raw)
    shapes, mats = [], []
    for sh in skyrimnif.trishapes(src):
        m = conv._shape_material(src, sh, flat_normal_ok=True, albedo_tint=tint)
        if m is None:
            continue
        if skyrimnif.double_sided(src, sh.shader_ref):
            sh = skyrimconvert.with_back_faces(sh) or sh
        shapes.append(sh)
        mats.append(m)
    if not shapes:
        raise ValueError("no drawable shape")
    stem = re.sub(r"[^a-z0-9_]+", "_", os.path.splitext(name.lower().replace("\\", "/").split("meshes/", 1)[-1])[0])
    out_name = f"{PREFIX}/grassnative/{stem}"
    files = skyrimconvert.convert_static_sse(src, shapes, out_name, mats, None, {})
    for rel, data in files.items():
        p = os.path.join(staging, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(data)
    return out_name.replace("/", "\\") + ".nif"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True, help="Skyrim.esm")
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--terrain", required=True, help="the overlay build folder (overlays_params.json, ltex_mapping.json)")
    ap.add_argument("--texconv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--content-resources")
    ap.add_argument("--archive2")
    ap.add_argument("--tints", help="grass.json of a make_skyrim_objects.py grass run: its per-model vertex-colour tints")
    ap.add_argument("--density-scale", type=float, default=1.0, help="Skyrim density (percent) x this = Max Density")
    ap.add_argument("--threshold", type=float, help="GCVR painted-material threshold (default: the template's)")
    ap.add_argument("--biome", default="planet",
                    help="where the covers are listed: 'planet' (default) = the planet plugin's own biome under the "
                         "overlay (Nirn's ocean copy); 'world' = the terrain build's world biome (overlays_params.json "
                         "world_overrides; October's test); an EditorID or hex FormID of a Starfield.esm biome; "
                         "'none' = ground cover records only")
    ap.add_argument("--control", action="store_true",
                    help="control test: every converted Skyrim texture gets the vanilla ground cover the world's land "
                         "biome (Jemison's forest) uses most (vanilla grass models), no Skyrim grass converted")
    ap.add_argument("--biome-masks", default="all",
                    help="terrain masks of the added biome entries: 'all' (0-6: Base, Solid, FlatOuter, FlatInner, "
                         "Talus, Flow, Path) or a comma list, e.g. 0")
    ap.add_argument("--gras-template", help="EditorID regex of the vanilla GRAS to copy (default: the first usable)")
    ap.add_argument("--gcvr-template", help="EditorID regex of the vanilla GCVR to copy (default: the first with LTEX)")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    sf_esm = os.path.join(a.starfield, "Data", "Starfield.esm")
    cr = a.content_resources or os.path.join(a.starfield, "Tools", "ContentResources.zip")
    for p, what in ((sf_esm, "Starfield.esm"), (cr, "ContentResources.zip"), (a.skyrim, "Skyrim.esm"),
                    (os.path.join(a.terrain, "overlays_params.json"), "overlays_params.json")):
        if not os.path.isfile(p):
            sys.exit(f"{what} not found: {p}")
    with open(os.path.join(a.terrain, "overlays_params.json"), encoding="utf-8") as fh:
        prm = json.load(fh)
    overrides = prm.get("ltex_overrides") or []
    if not overrides:
        sys.exit("the terrain build overrides no LTEX (build it with --skyrim-ground): nothing safe to grow grass on")
    mapping_path = os.path.join(a.terrain, "ltex_mapping.json")
    if os.path.isfile(mapping_path):
        with open(mapping_path, encoding="utf-8") as fh:
            mapping = json.load(fh)
    else:
        import refresh_btd
        from fo4sf import landtex, skyrimland
        print("no ltex_mapping.json in the staging: reading which texture the installed terrain draws for each "
              "Skyrim texture ...")
        land = skyrimland.SkyrimLand(a.skyrim, "Tamriel")
        cells, sky_tex = landtex.read_world_textures(a.skyrim, land.land_source, {})
        fids, _support, _outside = refresh_btd.infer_mapping(cells, prm["overlays"], a.terrain)
        mapping = {"skyrim": mapping_from_fids(fids, {f: v.get("edid", "") for f, v in sky_tex.items()}, overrides)}
        print(f"  {len(fids)} Skyrim textures mapped")
    tints = {}
    if a.tints:
        with open(a.tints, encoding="utf-8") as fh:
            tints = {k: tuple(v) for k, v in json.load(fh).get("tints", {}).items()}

    ltex_grass, gras_sky = skyrimgrass.read_grass(a.skyrim)
    sky_ltex = {fid: sfplugin.edid(s) for _t, _h, s, fid in sfplugin.records(a.skyrim, [b"LTEX"])}
    plan = sfgrass.cover_plan(mapping.get("skyrim", {}), overrides, ltex_grass, sky_ltex)
    report = {"slots": {f"{k:08X}": [gras_sky[g]["edid"] for g in v if g in gras_sky] for k, v in plan["slots"].items()},
              "skipped_textures": plan["skipped"], "grasses": {}, "failed": {}}
    if not plan["slots"] and not a.control:
        sys.exit("no converted ground texture has Skyrim grass: " + json.dumps(plan["skipped"][:10], indent=1))

    sf = sfplugin.records(sf_esm, [b"GRAS", b"GCVR", b"BIOM"])
    masters = ["Starfield.esm"]
    biome = a.biome
    target = None                                     # (type, header, subs, FormID) of the biome to override
    if biome.lower() == "planet":
        mars = (prm.get("mars") or {}).get("plugin")
        planet = os.path.join(a.terrain, mars) if mars else ""
        if not planet or not os.path.isfile(planet):
            sys.exit("the terrain build has no planet plugin (overlays_params.json 'mars'): pass --biome world or a "
                     "biome EditorID")
        masters = ["Starfield.esm", prm["plugin"], mars]
        target = location_biome(sfplugin.records(planet, [b"BIOM"]))
        if target is None:
            target = next((r for r in sf if r[0] == b"BIOM" and r[3] == VANILLA_OCEAN), None)
        if target is None:
            sys.exit(f"no biome under the overlay found in {mars} or Starfield.esm")
    elif biome.lower() == "world":
        biome = (prm.get("world_overrides") or {}).get("biome")
        if not biome:
            sys.exit("the terrain build sets no world biome (overlays_params.json world_overrides): pass --biome "
                     "<EditorID or hex FormID> (Jemison / New Atlantis: 1CBD6A) or --biome none")
    if target is None and biome.lower() != "none":
        want = biome.lower()
        target = next((r for r in sf if r[0] == b"BIOM" and (sfplugin.edid(r[2]).lower() == want
                                                             or f"{r[3]:08x}" == want.zfill(8))), None)
        if target is None:
            sys.exit(f"biome {biome} not in Starfield.esm")
    nm = len(masters)

    os.makedirs(out, exist_ok=True)
    recs, covers, gras_fid = [], [], {}
    staging = os.path.join(out, "_staging")
    conv = None
    if a.control:
        wb = (prm.get("world_overrides") or {}).get("biome") or f"{VANILLA_LAND:08X}"
        src = next((r for r in sf if r[0] == b"BIOM" and (f"{r[3]:08x}" == wb.lower().zfill(8)
                                                          or sfplugin.edid(r[2]).lower() == wb.lower())), None)
        gc = control_cover(src[2]) if src else 0
        if not gc:
            sys.exit(f"control: the world's land biome ({wb}) lists no ground cover")
        covers = [(int(o["form_id"]), gc) for o in overrides]
        names = {r[3]: sfplugin.edid(r[2]) for r in sf if r[0] == b"GCVR"}
        report["control"] = {"gcvr": f"{gc:08X}", "edid": names.get(gc, "?"), "textures": len(covers)}
    else:
        gt = pick(sf, b"GRAS", a.gras_template, gras_ok)
        ct = pick(sf, b"GCVR", a.gcvr_template, lambda s: any(x == b"LNAM" for x, _d in s))
        if gt is None or ct is None:
            sys.exit("no vanilla GRAS / GCVR template found")
        report["templates"] = {"gras": sfplugin.edid(gt[2]), "gcvr": sfplugin.edid(ct[2]),
                               "gras_dnam": sfgrass.parse_gras_dnam(dict((s, bytes(d)) for s, d in gt[2])[b"DNAM"])}
        shutil.rmtree(staging, ignore_errors=True)
        conv = skyrimconvert.SkyrimConverter(bsa.SkyrimArchives(a.skyrim_data), staging, a.texconv, cr, None,
                                             prefix=PREFIX)
        tdnam = dict((s, bytes(d)) for s, d in gt[2])[b"DNAM"]
        for g in sorted({g for v in plan["slots"].values() for g in v},
                        key=lambda g: gras_sky.get(g, {}).get("edid", "")):
            r = gras_sky.get(g)
            if r is None:
                continue
            name = "meshes\\" + r["model"].replace("/", "\\").lstrip("\\")
            try:
                model = convert_model(conv, name, tints.get(r["model"]), staging)
            except Exception as e:                                   # noqa: BLE001 (reported; that grass is left out)
                report["failed"][r["edid"]] = f"{type(e).__name__}: {e}"
                continue
            fid = sfplugin.new_form_id(len(recs), nm)
            subs = sfplugin.edit(gt[2], {b"EDID": sfplugin.zs("S2S_" + r["edid"]), b"MODL": sfplugin.zs(model),
                                         b"DNAM": sfgrass.gras_dnam_from_skyrim(tdnam, r, a.density_scale)})
            recs.append((b"GRAS", gt[1], subs, fid))
            gras_fid[g] = fid
            report["grasses"][r["edid"]] = {"form_id": f"{fid:08X}", "model": model,
                                            "skyrim": {k: r[k] for k in ("density", "min_slope", "max_slope",
                                                                         "height_range", "colour_range", "flags")}}
        for slot, gs in sorted(plan["slots"].items()):
            lst = [(gras_fid[g], -1) for g in gs if g in gras_fid]
            if not lst:
                continue
            fid = sfplugin.new_form_id(len(recs), nm)
            subs = sfgrass.build_gcvr(ct[2], sfplugin.zs(f"S2S_Cover_{slot:08X}"), lst, [slot], a.threshold)
            recs.append((b"GCVR", ct[1], subs, fid))
            covers.append((slot, fid))
    report["covers"] = [{"ltex": f"{s:08X}", "gcvr": f"{c:08X}"} for s, c in covers]
    masks = list(range(7)) if a.biome_masks == "all" else [int(x) for x in a.biome_masks.split(",") if x.strip()]
    if target is not None:
        recs.append((b"BIOM", target[1], sfgrass.biome_with_cover(target[2], covers, masks=masks), target[3]))
        report["biome"] = {"edid": sfplugin.edid(target[2]), "form_id": f"{target[3]:08X}", "masks": masks,
                           "entries_added": len(covers) * len(masks)}
    report["masters"] = masters
    with open(os.path.join(out, PLUGIN), "wb") as fh:
        fh.write(sfplugin.build(recs, sfplugin.header_info(sf_esm), author="Skyrim2Starfield grass", masters=masters))
    if conv is not None:
        import hair_pack
        base = os.path.splitext(PLUGIN)[0]
        report["packing"] = hair_pack.pack(staging, out, a.starfield, a.archive2, f"{base} - Main.ba2",
                                           f"{base} - Textures.ba2")
        report["converter"] = {"stats": conv.stats, "material_errors": conv.material_errors}
        shutil.rmtree(staging, ignore_errors=True)
    if not os.path.isfile(mapping_path):
        with open(os.path.join(out, "ltex_mapping_inferred.json"), "w", encoding="utf-8") as fh:
            json.dump(mapping, fh, indent=1)
    with open(os.path.join(out, "grass_native.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    print((f"control: vanilla ground cover {report['control']['edid']} on {len(covers)} converted textures"
           if a.control else f"{len(gras_fid)} grasses, {len(covers)} ground covers")
          + (f", biome {report['biome']['edid']} ({report['biome']['form_id']}) overridden "
             f"({report['biome']['entries_added']} entries)" if target is not None else ", no biome override")
          + f"; {len(plan['skipped'])} grassy Skyrim textures skipped (vanilla Starfield ground), "
            f"{len(report['failed'])} models failed")
    if nm > 1:
        print(f"masters: {', '.join(masters)}: load {PLUGIN} after them")
    print(f"report: {os.path.join(out, 'grass_native.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
