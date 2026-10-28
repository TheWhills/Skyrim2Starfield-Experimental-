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

from fo4sf import bsa, sfgrass, sfplugin, skyrimconvert, skyrimgrass, skyrimnif  # noqa: E402
from fo4sf import nif as nifmod  # noqa: E402

PLUGIN = "S2SGrass.esm"
PREFIX = "s2s"


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
    ap.add_argument("--biome", default="world",
                    help="EditorID or hex FormID of the biome to list the covers in; 'world' (default) = the terrain "
                         "build's world biome (overlays_params.json world_overrides), 'none' = ground cover records "
                         "only")
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
                    (os.path.join(a.terrain, "overlays_params.json"), "overlays_params.json"),
                    (os.path.join(a.terrain, "ltex_mapping.json"), "ltex_mapping.json")):
        if not os.path.isfile(p):
            sys.exit(f"{what} not found: {p}")
    with open(os.path.join(a.terrain, "overlays_params.json"), encoding="utf-8") as fh:
        prm = json.load(fh)
    with open(os.path.join(a.terrain, "ltex_mapping.json"), encoding="utf-8") as fh:
        mapping = json.load(fh)
    overrides = prm.get("ltex_overrides") or []
    if not overrides:
        sys.exit("the terrain build overrides no LTEX (build it with --skyrim-ground): nothing safe to grow grass on")
    tints = {}
    if a.tints:
        with open(a.tints, encoding="utf-8") as fh:
            tints = {k: tuple(v) for k, v in json.load(fh).get("tints", {}).items()}

    ltex_grass, gras_sky = skyrimgrass.read_grass(a.skyrim)
    sky_ltex = {fid: sfplugin.edid(s) for _t, _h, s, fid in sfplugin.records(a.skyrim, [b"LTEX"])}
    plan = sfgrass.cover_plan(mapping.get("skyrim", {}), overrides, ltex_grass, sky_ltex)
    report = {"slots": {f"{k:08X}": [gras_sky[g]["edid"] for g in v if g in gras_sky] for k, v in plan["slots"].items()},
              "skipped_textures": plan["skipped"], "grasses": {}, "failed": {}}
    if not plan["slots"]:
        sys.exit("no converted ground texture has Skyrim grass: " + json.dumps(plan["skipped"][:10], indent=1))

    sf = sfplugin.records(sf_esm, [b"GRAS", b"GCVR", b"BIOM"])
    gt = pick(sf, b"GRAS", a.gras_template, gras_ok)
    ct = pick(sf, b"GCVR", a.gcvr_template, lambda s: any(x == b"LNAM" for x, _d in s))
    if gt is None or ct is None:
        sys.exit("no vanilla GRAS / GCVR template found")
    report["templates"] = {"gras": sfplugin.edid(gt[2]), "gcvr": sfplugin.edid(ct[2]),
                           "gras_dnam": sfgrass.parse_gras_dnam(dict((s, bytes(d)) for s, d in gt[2])[b"DNAM"])}

    os.makedirs(out, exist_ok=True)
    staging = os.path.join(out, "_staging")
    shutil.rmtree(staging, ignore_errors=True)
    conv = skyrimconvert.SkyrimConverter(bsa.SkyrimArchives(a.skyrim_data), staging, a.texconv, cr, None,
                                         prefix=PREFIX)
    recs, gras_fid = [], {}
    tdnam = dict((s, bytes(d)) for s, d in gt[2])[b"DNAM"]
    for g in sorted({g for v in plan["slots"].values() for g in v}, key=lambda g: gras_sky.get(g, {}).get("edid", "")):
        r = gras_sky.get(g)
        if r is None:
            continue
        name = "meshes\\" + r["model"].replace("/", "\\").lstrip("\\")
        try:
            model = convert_model(conv, name, tints.get(r["model"]), staging)
        except Exception as e:                                   # noqa: BLE001 (reported; that grass is left out)
            report["failed"][r["edid"]] = f"{type(e).__name__}: {e}"
            continue
        fid = sfplugin.new_form_id(len(recs))
        subs = sfplugin.edit(gt[2], {b"EDID": sfplugin.zs("S2S_" + r["edid"]), b"MODL": sfplugin.zs(model),
                                     b"DNAM": sfgrass.gras_dnam_from_skyrim(tdnam, r, a.density_scale)})
        recs.append((b"GRAS", gt[1], subs, fid))
        gras_fid[g] = fid
        report["grasses"][r["edid"]] = {"form_id": f"{fid:08X}", "model": model,
                                        "skyrim": {k: r[k] for k in ("density", "min_slope", "max_slope",
                                                                     "height_range", "colour_range", "flags")}}
    covers = []
    for slot, gs in sorted(plan["slots"].items()):
        lst = [(gras_fid[g], -1) for g in gs if g in gras_fid]
        if not lst:
            continue
        fid = sfplugin.new_form_id(len(recs))
        subs = sfgrass.build_gcvr(ct[2], sfplugin.zs(f"S2S_Cover_{slot:08X}"), lst, [slot], a.threshold)
        recs.append((b"GCVR", ct[1], subs, fid))
        covers.append((slot, fid))
    report["covers"] = [{"ltex": f"{s:08X}", "gcvr": f"{c:08X}"} for s, c in covers]
    biome = a.biome
    if biome.lower() == "world":
        biome = (prm.get("world_overrides") or {}).get("biome")
        if not biome:
            sys.exit("the terrain build sets no world biome (overlays_params.json world_overrides): pass --biome "
                     "<EditorID or hex FormID> (Jemison / New Atlantis: 1CBD6A) or --biome none")
    if biome.lower() == "none":
        biome = None
    masks = list(range(7)) if a.biome_masks == "all" else [int(x) for x in a.biome_masks.split(",") if x.strip()]
    if biome:
        want = biome.lower()
        b = next((r for r in sf if r[0] == b"BIOM" and (sfplugin.edid(r[2]).lower() == want
                                                        or f"{r[3]:08x}" == want.zfill(8))), None)
        if b is None:
            sys.exit(f"biome {biome} not in Starfield.esm")
        recs.append((b"BIOM", b[1], sfgrass.biome_with_cover(b[2], covers, masks=masks), b[3]))
        report["biome"] = {"edid": sfplugin.edid(b[2]), "form_id": f"{b[3]:08X}", "masks": masks,
                           "entries_added": len(covers) * len(masks)}
    with open(os.path.join(out, PLUGIN), "wb") as fh:
        fh.write(sfplugin.build(recs, sfplugin.header_info(sf_esm), author="Skyrim2Starfield grass"))
    import hair_pack
    base = os.path.splitext(PLUGIN)[0]
    report["packing"] = hair_pack.pack(staging, out, a.starfield, a.archive2, f"{base} - Main.ba2",
                                       f"{base} - Textures.ba2")
    report["converter"] = {"stats": conv.stats, "material_errors": conv.material_errors}
    shutil.rmtree(staging, ignore_errors=True)
    with open(os.path.join(out, "grass_native.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    print(f"{len(gras_fid)} grasses, {len(covers)} ground covers"
          + (f", biome {report['biome']['edid']} overridden ({report['biome']['entries_added']} entries)"
             if biome else ", no biome override")
          + f"; {len(plan['skipped'])} grassy Skyrim textures skipped (vanilla Starfield ground), "
            f"{len(report['failed'])} models failed")
    print(f"report: {os.path.join(out, 'grass_native.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
