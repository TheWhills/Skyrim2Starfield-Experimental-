r"""Skyrim's snow on the tops of rocks as Starfield's global snow layer, per exterior cell (2026-11-25; docs/terrain/
skyrim-objects.md "Snow on rocks").

Skyrim puts snow on upward-facing surfaces with a directional material (STAT DNAM -> MATO SnowMaterialObject1P,
SnowMaterialMountain1P ...; skyrimrefs.directional_materials): 22,348 of our placed objects have one. Starfield draws
the same kind of world-space, top-down layer with its global layer system (Materials/GlobalLayerSystem/GL_Snow_*.mat:
SourceDirection, directionality, noise), chosen per biome (BIOM EFSD) or per cell (CELL XCGD). A biome covers the
whole overlay, so this writes XCGD on the exterior cells where Skyrim's objects carry snow: a cell gets a layer when at
least --min-share of its placed Skyrim objects have a snow directional material; GL_Snow_Light_01 where most of those
are Skyrim's *Light* snow materials, GL_Snow_Medium_01 otherwise. Then the WRLD cell index is written again.
Unverified: vanilla uses XCGD only on interior cells; whether the engine honours it outdoors is the first in-game test.

    python -I scripts\terrain\snow_layer.py --work C:\Modding\work\sky_all --staging C:\Modding\staging\skyrim_all ^
        --skyrim-data <Skyrim Data> --sf-esm <Starfield>\Data\Starfield.esm
--dry-run prints the plan; --off removes every XCGD again. The staged plugin is backed up once (.before_snow_layer);
reinstall the exterior afterwards (tools/owner/snow_layer.ps1 does it all). A restage (TerrainOverlays) drops it: rerun.
"""
import argparse
import json
import os
import shutil
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "scripts", "tools"))

from fo4sf import esm_patch, fo4land, skyrimrefs  # noqa: E402

LAYERS = {"light": "materials/globallayersystem/gl_snow_light_01.mat",
          "medium": "materials/globallayersystem/gl_snow_medium_01.mat"}
BACKUP = ".before_snow_layer"


def snow_class(mato_edid: str):
    """'light' / 'medium' for a Skyrim snow directional material, None for others (ash, moss, sulfur, ice, LOD)."""
    e = (mato_edid or "").lower()
    if "snow" not in e or "lod" in e:
        return None
    return "light" if "light" in e else "medium"


def plan_cells(objects: dict, base_of: dict, dmat: dict, min_share: float = 0.25) -> tuple:
    """({(x, y): 'light' / 'medium'}, {(x, y): Counter}) from objects.json's placed references (src = Skyrim FormKey),
    base_of {src: Skyrim base formkey}, dmat (skyrimrefs.directional_materials)."""
    per = {}
    for r in objects["refs"]:
        base = base_of.get(r["src"])
        if base is None:                      # grass patches, turning parts, generated water: not Skyrim references
            continue
        c = per.setdefault(tuple(r["cell"]), Counter())
        c["all"] += 1
        k = snow_class((dmat.get(base) or {}).get("edid", ""))
        if k:
            c["snow"] += 1
            c[k] += 1
    out = {xy: ("light" if c["light"] > c["medium"] else "medium")
           for xy, c in per.items() if c["snow"] and c["snow"] >= min_share * c["all"]}
    return out, per


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True, help="the exterior's make_skyrim_objects.py work folder (export.json)")
    ap.add_argument("--staging", required=True)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--sf-esm", required=True, help="Starfield.esm (the cell index layout is verified on LC030World)")
    ap.add_argument("--min-share", type=float, default=0.25)
    ap.add_argument("--off", action="store_true", help="remove every cell's global layer")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    import world_offsets
    with open(os.path.join(a.staging, "objects.json"), encoding="utf-8") as f:
        objects = json.load(f)
    with open(os.path.join(a.staging, "overlays_params.json"), encoding="utf-8") as f:
        prm = json.load(f)
    world = prm["overlays"][0]["world"]
    plugin_path = os.path.join(a.staging, prm["plugin"])
    if a.off:
        cells, per = {}, {}
    else:
        with open(os.path.join(a.work, "export.json"), encoding="utf-8") as f:
            base_of = {r["formkey"]: r.get("base_formkey") for r in json.load(f)["refs"]}
        cells, per = plan_cells(objects, base_of, skyrimrefs.directional_materials(a.skyrim_data), a.min_share)
    n = Counter(cells.values())
    print(f"{len(per):,} cells with Skyrim objects; snow layer on {len(cells):,} (light {n['light']:,}, medium "
          f"{n['medium']:,}; share of snow objects >= {a.min_share:g})")
    if a.dry_run:
        return 0
    with fo4land.Plugin(a.sf_esm) as sf:
        reading = world_offsets.verify(sf.buf, sf.body, "LC030World", log=lambda *x: None)
    if not reading:
        sys.exit("no reading of LC030World's cell index: cannot rewrite ours; plugin left as it was")
    with fo4land.Plugin(plugin_path) as p:
        wfid = p.find_world(world)[0]
        data = bytes(p.buf)
    new, changed, missing = esm_patch.set_cell_fields(
        data, wfid, {xy: {b"XCGD": esm_patch.zstring(LAYERS[k])} for xy, k in cells.items()}, remove=(b"XCGD",))
    if missing:
        print(f"  {len(missing)} planned cells have no CELL record (left out), e.g. {missing[:3]}")
    if not os.path.exists(plugin_path + BACKUP):
        shutil.copy2(plugin_path, plugin_path + BACKUP)
    tmp = plugin_path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(new)
    world_offsets.write(tmp, world, reading, log=print)
    os.replace(tmp, plugin_path)
    with open(os.path.join(a.staging, "snow_cells.json"), "w", encoding="utf-8") as f:
        json.dump({"min_share": a.min_share, "layers": LAYERS,
                   "cells": {f"{x},{y}": k for (x, y), k in sorted(cells.items())}}, f, indent=0)
    print(f"{changed:,} cell records changed in {plugin_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
