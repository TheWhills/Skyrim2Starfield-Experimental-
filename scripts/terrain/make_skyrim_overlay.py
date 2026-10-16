"""Skyrim's Tamriel as ONE native Starfield terrain overlay on Mars: the core64 recipe (docs/terrain/core64c.md,
docs/terrain/commonwealth-scale.md section 6a) with Skyrim.esm as the height source. Walkable terrain only: no
objects, water, textures beyond one plain ground texture, LOD objects, NPCs. See docs/terrain/skyrim-tamriel.md.

    python scripts/terrain/make_skyrim_overlay.py info  --skyrim <Skyrim.esm> [--find Riverwood]
    python scripts/terrain/make_skyrim_overlay.py build --skyrim <Skyrim.esm> --sf-data <Starfield Data> --out <dir>
        [--cells X0 X1 Y0 Y1] [--arrival Riverwood | --arrival 5,-12] [--landmark <cell EditorID or X,Y> ...]
        [any make_cw_overlays.py build option, e.g. --mask-writer builtin, --no-mars, --rays ..., --ray-distances ...]
    dotnet run --project dotnet/TerrainOverlays -c Release -- <Starfield.esm> <dir>        (reads overlays_params.json)
    python scripts/terrain/make_skyrim_overlay.py check --sf-data <Starfield Data> --out <dir> [--no-plugins]

info reads only Skyrim.esm (no Starfield files needed): LAND extent, holes, height range, WRLD defaults, cell-border
seams, the overlay size the build would choose and the cell EditorIDs matching --find (landmark names).

build writes, all OUTSIDE the repo (derived game data), exactly what make_cw_overlays.py writes for core64, plus
skyrim_source.json (the info above and how every landmark resolved):
  Data/Terrain/<WORLD>.btd (+ Data/meshes/terrain copy), overlay mask, overlays_params.json, plan.json,
  expected.json, README.txt, preview.png
Frame: Skyrim position / 70 = local metres (the CW frame of the FO4 builder with Skyrim's origin), heights / 70.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))
sys.path.insert(0, HERE)
from fo4sf import overlay_grid as og  # noqa: E402
from fo4sf import skyrimland  # noqa: E402
from fo4sf import terrain_grid as tg  # noqa: E402
import make_cw_overlays as cw  # noqa: E402

MAX_N = tg.MAX_CELLS            # largest vanilla BTD: 100 x 100 cells (docs/terrain/architecture.md 1.4)
BTD_BYTES_PER_CELL = 33_000     # experiment 2: 27.6 MB for 841 cells of real FO4 terrain (planning estimate only)

# core64's recipe (commonwealth-scale.md 6a) with Skyrim names. The Mars registration is experiment 2b's, the one
# verified in game; never install two terrain experiments at once (every Mars plugin overrides MarsPlanetData).
DEFAULTS = {
    "prefix": "SKY", "world": "SKY_Tamriel", "plugin": "SkyrimTerrainTamriel.esm",
    "mars_plugin": "SkyrimTerrainTamriel_Mars.esm", "experiment": "skyrim_tamriel", "display_name": "Skyrim",
    "ref_lat": 0.3, "ref_lon": -1.2, "ref_offset": (-12, -27), "centre_cell": (-12, -27),
}
LOCAL_MIN_N = 5                 # --frame local: at least 5 x 5 cells (the outer ring blends into Mars)
LOCAL_EDGE_KEEP = 50.0          # and probes up to 50 m from its edge, at city distances
LOCAL_RAY_DISTANCES = (0.0, 25.0, 50.0, 100.0, 200.0)
DEFAULT_ARRIVAL = "Riverwood"   # exterior cell EditorID; falls back to the overlay centre if the plugin has no such cell


def single_tile_n(cells, max_n=MAX_N, pad="origin"):
    """Smallest n whose one n x n overlay covers the source cells. pad 'origin': local frame = source frame / 70 (the
    overlay is centred on Skyrim's origin); 'centre': the overlay is centred on the cells (a city far from the origin
    stays small; its local frame is shifted by the tile's origin)."""
    rect = og.sf_cells_of_fo4_rect(*cells)
    for n in range(3, max_n + 1):
        if len(og.split(*rect, n, pad)) == 1:
            return n
    return None


def names_for(world_edid: str) -> dict:
    """Plugin / worldspace names for a source worldspace: Tamriel keeps its names; others (cities) get their own, so a
    city build never shares a plugin, worldspace or archive name with the Tamriel build."""
    if world_edid.lower() == "tamriel":
        return dict(DEFAULTS)
    stem = re.sub(r"[^A-Za-z0-9]", "", world_edid)
    return dict(DEFAULTS, world=f"SKY_{stem}", plugin=f"SkyrimTerrain{stem}.esm",
                mars_plugin=f"SkyrimTerrain{stem}_Mars.esm", experiment=f"skyrim_{stem.lower()}",
                display_name=re.sub(r"World$", "", stem) or stem)


def resolve(land, specs, what):
    out, report = [], []
    for s in specs:
        lm = land.landmark(s)
        report.append({"spec": s, "role": what, "found": lm is not None,
                       **({"name": lm[0], "source_units": [lm[2], lm[3]],
                           "local_m": [round(lm[2] / 70.0, 3), round(lm[3] / 70.0, 3)]} if lm else {})})
        if lm:
            out.append(lm)
        else:
            near = [e for e, _ in land.find_cells(re.escape(s[:6]))][:8] if not re.match(r"\s*-?\d", s) else []
            print(f"WARNING: {what} {s!r}: no such exterior cell in {land.world}" +
                  (f" (similar: {', '.join(near)})" if near else "") + "; skipped")
    return out, report


def plan_numbers(land, cells, n):
    rect = og.sf_cells_of_fo4_rect(*cells)
    return {"source_cells": {"x": [cells[0], cells[1]], "y": [cells[2], cells[3]]},
            "sf_cells": {"x": [rect[0], rect[1]], "y": [rect[2], rect[3]]},
            "overlay_n": n, "overlay_km": None if n is None else n / 10.0,
            "btd_estimate_mb": None if n is None else round(n * n * BTD_BYTES_PER_CELL / 1e6, 1)}


# ---------------------------------------------------------------------------------------------------------- textures
def skyrim_ground(a, ltex, cells, usage, out):
    """--skyrim-ground: convert the most-covering Skyrim landscape texture sets into Starfield materials (staged under
    <out>/Data) and assign each one a spare Starfield.esm LTEX to override (src/fo4sf/skyrimground.py)."""
    from fo4sf import bsa, landtex, skyrimconvert, skyrimground
    sf_esm = os.path.join(a.sf_data, "Starfield.esm")
    if not (a.content_resources and a.texconv):
        sys.exit("--skyrim-ground needs --content-resources (Starfield Tools\\ContentResources.zip) and --texconv")
    fields = skyrimground.ltex_fields(sf_esm)
    plain = fields.get(landtex.PLAIN_GROUND)
    if not plain or not plain["bnam"]:
        sys.exit("Starfield.esm has no plain ground LTEX (LDirtFootprints01) with a material to clone")
    template = skyrimground.template_material(a.content_resources, plain["bnam"])
    print(f"skyrim ground: material template {plain['bnam']} (from {plain['edid']}); finding spare LTEX records...")
    tslots = template["Summary"]["Layer1"].get("Textures", {})
    print("  template texture slots: " + ", ".join(f"{k}={(v or {}).get('File') or (v or {}).get('Replacement') or '-'}"
                                                 for k, v in tslots.items()))
    uv = [c.get("Data") for o in template.get("Objects", []) for c in o.get("Components", [])
          if "UVStream" in c.get("Type", "") or "Scale" in json.dumps(c.get("Data", {}))[:200]]
    if uv:
        print(f"  template UV / scale components: {json.dumps(uv)[:600]}")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "ground_template.mat.json"), "w", encoding="utf-8") as f:
        json.dump(template, f, indent=1)
    slots = skyrimground.free_slots(sf_esm, usage, fields)
    cov = skyrimground.coverage(cells)
    chosen, fallback = skyrimground.plan(ltex, cov, slots[:a.skyrim_ground_max])
    print(f"skyrim ground: {len(slots)} spare Starfield LTEX records; converting {len(chosen)} of "
          f"{sum(1 for f in cov if cov[f] > 0)} Skyrim ground textures in use")
    conv = skyrimconvert.SkyrimConverter(bsa.SkyrimArchives(os.path.dirname(os.path.abspath(a.skyrim))),
                                         os.path.join(out, "Data"), a.texconv, a.content_resources)
    if a.skyrim_ground_test:                          # every converted ground diffuse becomes a checkerboard
        checker, real = skyrimground.checker_dds(), conv.src.texture
        diffuses = {skyrimground.texture_path(ltex[f]["diffuse"]).lower() for f, _s in chosen}
        conv.src.texture = lambda name: checker if name.replace("/", "\\").lower() in diffuses else real(name)
        print("skyrim ground: TEST MODE, ground diffuse textures replaced by a magenta / green checkerboard")
    flat = skyrimground.flat_textures(os.path.join(out, "Data"), a.texconv)
    tiling = a.skyrim_ground_tiling
    print(f"skyrim ground: flat AO / height maps, tiling {tiling:g} m per repeat (vanilla dirt 3.2 m), no displacement")
    names, sky, overrides, failed, done = {}, {}, [], {}, {}
    for fid, slot in chosen:
        v = ltex[fid]
        stem = "ground/" + re.sub(r"[^a-z0-9]+", "_", v["edid"].lower()).strip("_")
        try:
            mat = conv._convert_texture_set(stem, skyrimground.texture_path(v["diffuse"]),
                                            skyrimground.texture_path(v.get("normal")), "", template=template,
                                            extra_files=flat)
            mp = os.path.join(out, "Data", *mat.replace("\\", "/").split("/"))
            with open(mp, encoding="utf-8") as f:
                md = json.load(f)
            skyrimground.terrain_settings(md, tiling)
            from fo4sf import convert_material as cm
            with open(mp, "w", encoding="utf-8", newline="\n") as f:
                f.write(cm.dump_mat(md))
        except Exception as e:                       # noqa: BLE001  (reported; that texture uses the category pick)
            failed[v["edid"]] = f"{type(e).__name__}: {e}"
            continue
        name = "SKYG_" + v["edid"]
        names[name], sky[v["edid"]], done[fid] = slot, name, name
        overrides.append({"form_id": slot, "vanilla_edid": fields[slot]["edid"], "skyrim": v["edid"],
                          "material": skyrimground.bnam_for(mat, plain["bnam"])})
    borrowed = 0
    for fid, src in fallback.items():
        if src in done and ltex[fid]["edid"] not in sky:
            sky[ltex[fid]["edid"]] = done[src]
            borrowed += 1
    for e, why in list(failed.items())[:5]:
        print(f"  ground texture {e} not converted: {why}")
    print(f"skyrim ground: {len(overrides)} converted, {len(failed)} failed, {borrowed} more Skyrim textures borrow a "
          f"converted one of their category")
    return {"names": names, "skyrim": sky, "overrides": overrides, "converted": len(overrides), "failed": failed,
            "free_slots": len(slots), "borrowed": borrowed}


def land_textures(a, land, out):
    """Skyrim's ground texture layers for the BTD (src/fo4sf/landtex.py): returns tile -> (LTEX table, sample weights,
    quad map) for make_cw_overlays.build, and writes <out>/ltex_mapping.json (editable; pass back with --ltex-mapping)."""
    import numpy as np
    from fo4sf import landtex
    sf_esm = os.path.join(a.sf_data, "Starfield.esm")
    sf = landtex.starfield_ltex(sf_esm)
    if not sf:
        sys.exit(f"no LTEX records read from {sf_esm}")
    cells, ltex = landtex.read_world_textures(a.skyrim, land.land_source)   # a city paints with its parent's land
    override = None
    if a.ltex_mapping:
        with open(a.ltex_mapping, encoding="utf-8") as f:
            override = json.load(f)
        override = {k: override.get(k) for k in ("categories", "skyrim", "default") if override.get(k)}
        if "categories" in override and isinstance(next(iter(override["categories"].values()), None), dict):
            override["categories"] = {k: v["edid"] for k, v in override["categories"].items()}
        if "skyrim" in override and isinstance(next(iter(override["skyrim"].values()), None), dict):
            override["skyrim"] = {v["edid"]: v["starfield"] for v in override["skyrim"].values()}
    usage, _first, nbtd, _skip = landtex.vanilla_usage(a.sf_data)
    print(f"ground textures: {nbtd} vanilla BTDs surveyed, {len(usage)} Starfield LTEX in use")
    ground = None
    if a.skyrim_ground:
        ground = skyrim_ground(a, ltex, cells, usage, out)
        sf = dict(sf, **ground["names"])                    # "SKYG_<Skyrim EditorID>" -> the overridden slot
        override = dict(override or {})
        override["skyrim"] = dict(ground["skyrim"], **(override.get("skyrim") or {}))
    mapping = landtex.build_mapping(ltex, sf, override, usage if nbtd else None)
    for cat, v in mapping["categories"].items():
        print(f"  {cat:7} -> {v['edid']}" + (f" (in {v['vanilla_btds']} vanilla BTDs)" if "vanilla_btds" in v else ""))
    cells_t, used = landtex.target_cells(cells, mapping, sf)
    default_sf = sf[mapping["skyrim"][landtex.DEFAULT_LTEX]["starfield"]]
    if default_sf not in used:
        used = sorted(set(used) | {default_sf})
    names = {v: k for k, v in sf.items()}
    os.makedirs(out, exist_ok=True)
    landtex.save_mapping(os.path.join(out, "ltex_mapping.json"), mapping, landtex.coverage(cells_t, used, names))
    x0, x1, y0, y1 = land.grid_bounds
    planes = {fid: np.rint(np.clip(landtex.merged_grid(cells_t, fid, x0, x1, y0, y1, 1.0 if fid == default_sf else 0.0),
                                   0, 1) * 255).astype(np.uint8) for fid in used}
    sp, ox, oy = tg.FO4_VERTEX_UNITS, x0 * tg.FO4_CELL_UNITS, y0 * tg.FO4_CELL_UNITS
    stats = {"starfield_ltex": [names[f] for f in used], "skyrim_ltex": len(ltex), "cells_with_layers": len(cells)}
    if ground:
        stats["skyrim_ground"] = {k: ground[k] for k in ("converted", "failed", "free_slots", "borrowed")}
        stats["ltex_overrides"] = ground["overrides"]

    def per_tile(t):
        xs, ys = t.sample_coords()
        xu, size = xs * tg.UNITS_PER_METRE, len(xs)
        qmap = np.zeros((2 * t.n, 2 * t.n, 8), np.uint8)
        words = np.zeros((size, size), np.uint16)
        beyond = []
        last = next(iter(planes.values())).shape[0] - 1
        for r0 in range(0, size, 64):
            yu = ys[r0:r0 + 64] * tg.UNITS_PER_METRE
            lo = int(min(max(np.floor((yu[0] - oy) / sp), 0), last))
            hi = int(min(max(np.floor((yu[-1] - oy) / sp) + 1, 0), last))
            if hi <= lo:
                lo, hi = max(min(lo, last - 1), 0), min(max(lo, 0) + 1, last)
            band = np.stack([tg.resample_bilinear(planes[f][lo:hi + 1].astype(np.float32) / 255.0, ox, oy + lo * sp, sp,
                                                  xu, yu) for f in used])
            q, w, st = landtex.encode_quadrants(band, used, used)
            qmap[r0 // 64] = q[0]
            words[r0:r0 + 64] = w
            beyond.append(st["weight_beyond_six_layers"])
        stats["weight_beyond_six_layers_max"] = round(max(beyond), 5) if beyond else 0.0
        return used, words, qmap

    return per_tile, stats


# ---------------------------------------------------------------------------------------------------------- commands
def cmd_info(a):
    land = skyrimland.SkyrimLand(a.skyrim, a.world_edid)
    cells = tuple(a.cells) if a.cells else land.extent
    pad = "centre" if a.frame == "local" else "origin"
    out = {"source": land.summary(), "seams": land.seams(),
           "plan": plan_numbers(land, cells, single_tile_n(cells, pad=pad))}
    if a.find:
        out["find"] = [{"edid": e, "cell": list(xy)} for e, xy in land.find_cells(a.find)[:200]]
    print(json.dumps(out, indent=1))
    if out["plan"]["overlay_n"] is None:
        print(f"NOTE: needs more than {MAX_N} x {MAX_N} cells as one overlay; pick a smaller --cells rectangle")
    return 0


def cmd_build(a, rest):
    land = skyrimland.SkyrimLand(a.skyrim, a.world_edid)
    s = land.summary()
    print(f"{land.world}: {s['cells_with_vhgt']} cells with VHGT, extent x {s['extent']['x']} y {s['extent']['y']}, "
          f"{s['holes']} holes, heights {s['heights_m'][0]:.1f}..{s['heights_m'][1]:.1f} m, "
          f"default land {land.default_land} units")
    cells = tuple(a.cells) if a.cells else land.extent
    pad = "centre" if a.frame == "local" else "origin"
    if a.arrival == DEFAULT_ARRIVAL and a.world_edid.lower() != "tamriel":
        a.arrival = ""                               # a city: arrive at its centre unless told otherwise
    n = a.tile or single_tile_n(cells, pad=pad)
    if n is not None and a.frame == "local" and not a.tile:
        n = max(n, LOCAL_MIN_N)                     # room inside the blend ring around a small city
    if n is None or n > MAX_N:
        sys.exit(f"source cells {cells} need more than {MAX_N} x {MAX_N} Starfield cells as one overlay; pass a "
                 f"smaller --cells rectangle (largest vanilla BTD is {MAX_N} x {MAX_N})")
    if len(og.split(*og.sf_cells_of_fo4_rect(*cells), n, pad)) != 1:
        sys.exit(f"--tile {n} does not cover {cells} as one overlay (omit --tile to choose the smallest that does)")

    arrival, arr_rep = resolve(land, [a.arrival] if a.arrival else [], "arrival")
    extra, extra_rep = resolve(land, a.landmark, "landmark")
    marks = tuple(arrival + extra)

    d = names_for(a.world_edid)
    argv = ["build", "--out", a.out, "--sf-data", a.sf_data, "--fo4", a.skyrim,
            "--fo4-cells", *map(str, cells), "--tile", str(n), "--pad", pad, "--plan", "rays",
            "--prefix", d["prefix"], "--world", d["world"], "--plugin", d["plugin"], "--mars-plugin", d["mars_plugin"],
            "--experiment", d["experiment"], "--btd-copy-meshes",
            "--ref-lat", str(d["ref_lat"]), "--ref-lon", str(d["ref_lon"]),
            "--ref-offset", *map(str, d["ref_offset"]), "--centre-cell", *map(str, d["centre_cell"])]
    if a.frame == "local":                           # a city-sized overlay: probes at city distances
        argv += ["--edge-keep", str(LOCAL_EDGE_KEEP), "--ray-distances", *map(str, LOCAL_RAY_DISTANCES)]
    ca = cw.parser().parse_args(argv + rest)           # later options win: anything in `rest` overrides the recipe
    if not ca.coc:
        ca.coc = f"{ca.world}{(arrival[0][0].title().replace('_', '') if arrival else '')}Spawn"
    for v in (ca.world, ca.coc):                       # make_cw_overlays.main's checks for single overlays
        if not re.fullmatch(r"[A-Za-z0-9_]+", v):
            sys.exit(f"bad EditorID {v!r}")
    if not ca.coc.endswith("Spawn"):
        sys.exit("--coc must end in Spawn (the runner's COC naming)")
    if not re.fullmatch(r"[0-9A-Fa-f]{2}", ca.load_byte):
        sys.exit("--load-byte must be two hex digits")
    ca.heights = skyrimland.SkyrimHeights(land, falloff_cells=a.edge_falloff_cells)
    ca.landmarks = marks
    ca.ray_landmarks = ()
    ca.arrival = arrival[0][0] if arrival else ""   # "" never matches a point label: the COC sits at the centre
    ca.display_name = a.display_name or d["display_name"]
    tex_stats = None
    a.texconv = ca.texconv or getattr(a, "texconv", "")   # --texconv belongs to make_cw_overlays' parser (passed in rest)
    if a.skyrim_ground_test:
        a.skyrim_ground = True
    if a.skyrim_ground:
        a.land_textures = True
    if a.land_textures:
        ca.land_textures, tex_stats = land_textures(a, land, a.out)

    os.makedirs(a.out, exist_ok=True)
    source = {"esm": os.path.basename(a.skyrim), "summary": s, "seams": land.seams(),
              "plan": plan_numbers(land, cells, n), "landmarks": arr_rep + extra_rep,
              "filled_cells_in_overlay": sum(1 for h in land.holes
                                             if cells[0] <= h[0] <= cells[1] and cells[2] <= h[1] <= cells[3]),
              "fill_height_units": ca.heights.fill,
              "outside_land": f"edge height eased to the fill height over {a.edge_falloff_cells:g} cells "
                              "(Skyrim has no ground past its LAND rectangle)",
              "frame": "local metres = Skyrim units / 70 from Skyrim's origin; height = Skyrim z / 70 (hypothesis H, "
                       "verified for FO4 in core64; same unit for Skyrim is a supported hypothesis)",
              "not_included": ["objects (STAT/TREE/...: make_skyrim_objects.py)", "water planes", "grass", "object LOD",
                               "navmesh", "actors"] + ([] if a.land_textures else
                                                        ["land textures (one plain ground LTEX; --land-textures)"])}
    def write_source():
        if tex_stats is not None:
            source["land_textures"] = tex_stats
        with open(os.path.join(a.out, "skyrim_source.json"), "w", encoding="utf-8") as f:
            json.dump(source, f, indent=1)
    write_source()
    print(f"overlay {ca.world}: {n} x {n} cells ({n / 10:g} km), source cells {cells}, arrival "
          f"{arrival[0][0] if arrival else 'overlay centre'}, {len(extra)} extra landmarks")
    res = cw.build(ca)
    write_source()                                   # with the texture stats the build filled in
    pp = os.path.join(a.out, "overlays_params.json")
    with open(pp, encoding="utf-8") as f:
        prm = json.load(f)
    if tex_stats and tex_stats.get("ltex_overrides"):  # for dotnet/TerrainOverlays: override these Starfield.esm LTEX
        prm["ltex_overrides"] = tex_stats["ltex_overrides"]
        print(f"overlays_params.json: {len(prm['ltex_overrides'])} Starfield LTEX overrides with Skyrim ground materials")
    if a.planet:
        apply_planet(prm, a)
    with open(pp, "w", encoding="utf-8") as f:
        json.dump(prm, f, indent=1)
    return res


def apply_planet(prm, a):
    """--planet: register the overlay on another planet's PNDT (default Mars, experiment 2b's verified registration) at
    --latlon, with that planet's overlay world / surface block / location as the record templates (--template-*). The
    plan's probe points stay in the overlay's own frame (local metres), which does not depend on the planet."""
    if not (a.latlon and a.template_world and a.template_block and a.template_location):
        sys.exit("--planet needs --latlon LAT LON (radians) and --template-world / --template-block / "
                 "--template-location (hex FormIDs of one of that planet's overlay worlds; SfInspect planetworlds / sfbk)")
    if not prm.get("mars"):
        sys.exit("--planet with --no-mars: nothing registers the overlay")
    prm["mars"]["planet"] = a.planet
    prm["mars"]["hypothesis"] = (f"registered on {a.planet} at lat {a.latlon[0]} lon {a.latlon[1]} rad (owner's choice, "
                                 "away from the planet's own locations); not verified in game")
    prm["mars"].pop("reference", None)
    prm["templates"] = {"world": a.template_world, "block": a.template_block, "location": a.template_location}
    for o in prm["overlays"]:
        o["latitude"], o["longitude"] = a.latlon
        o.pop("planet_target_cell", None)
    print(f"overlays_params.json: registered on {a.planet} at lat {a.latlon[0]:g} lon {a.latlon[1]:g}; templates "
          f"WRLD {a.template_world} SFBK {a.template_block} LCTN {a.template_location}")


def cmd_check(a, rest):
    ca = cw.parser().parse_args(["check", "--out", a.out, "--sf-data", a.sf_data] + rest)
    return cw.check(ca)


def join_coordinates(argv):
    """'--landmark -30,-20' -> '--landmark=-30,-20' (and --arrival): argparse would take '-30,-20' for an option, and
    most of Tamriel has a negative cell coordinate."""
    out, i = [], 0
    while i < len(argv):
        if argv[i] in ("--landmark", "--arrival") and i + 1 < len(argv) and re.fullmatch(r"-\d+\s*,\s*-?\d+", argv[i + 1]):
            out.append(f"{argv[i]}={argv[i + 1]}")
            i += 2
        else:
            out.append(argv[i])
            i += 1
    return out


def main(argv=None):
    # allow_abbrev=False: options this parser does not know (e.g. --world) must reach make_cw_overlays unchanged,
    # not be taken as an abbreviation of one of ours (--world-edid)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 allow_abbrev=False)
    ap.add_argument("cmd", choices=("info", "worlds", "build", "check"))
    ap.add_argument("--skyrim", help="Skyrim.esm (Special Edition; read-only)")
    ap.add_argument("--world-edid", default=skyrimland.WORLD, help="source worldspace EditorID (default Tamriel)")
    ap.add_argument("--sf-data", default="", help="Starfield Data folder (build: LTEX template BTD; check)")
    ap.add_argument("--out", help="staging folder outside the repo, e.g. C:\\Modding\\staging\\skyrim_tamriel")
    ap.add_argument("--cells", type=int, nargs=4, metavar=("X0", "X1", "Y0", "Y1"),
                    help="inclusive Skyrim cell rectangle (default: every cell with LAND)")
    ap.add_argument("--tile", type=int, default=0, help="overlay size in Starfield cells (default: smallest that fits)")
    ap.add_argument("--arrival", default=DEFAULT_ARRIVAL,
                    help="exterior cell EditorID or 'X,Y' Skyrim cell the COC marker goes next to ('' = overlay centre)")
    ap.add_argument("--landmark", action="append", default=[],
                    help="extra probe target (cell EditorID or 'X,Y'), added to the ray nearest its bearing; repeatable")
    ap.add_argument("--frame", choices=("skyrim", "local"), default="skyrim",
                    help="skyrim: overlay centred on Skyrim's origin (local = Skyrim position / 70; Tamriel); local: centred "
                         "on the cells (walled cities: a small overlay wherever the city is)")
    ap.add_argument("--edge-falloff-cells", type=float, default=skyrimland.FALLOFF_CELLS,
                    help="build: past Skyrim's LAND rectangle, ease the edge height down to the worldspace's default "
                         "land height over this many Skyrim cells (default 4 = 234 m; 0 = drop at the edge)")
    ap.add_argument("--display-name", default="", help="in-game WRLD/Location name (default 'Skyrim')")
    ap.add_argument("--find", default="", help="info: list exterior cell EditorIDs matching this regex")
    ap.add_argument("--land-textures", action="store_true",
                    help="build: Skyrim's ground texture layers mapped onto Starfield LTEX (reads Starfield.esm from "
                         "--sf-data; writes ltex_mapping.json); default: one plain ground texture")
    ap.add_argument("--planet", default="", help="build: register on this PNDT EditorID instead of MarsPlanetData")
    ap.add_argument("--latlon", type=float, nargs=2, metavar=("LAT", "LON"), help="build --planet: radians")
    ap.add_argument("--template-world", default="", help="build --planet: hex FormID of that planet's overlay WRLD")
    ap.add_argument("--template-block", default="", help="build --planet: hex FormID of that world's SFBK")
    ap.add_argument("--template-location", default="", help="build --planet: hex FormID of that world's LCTN")
    ap.add_argument("--skyrim-ground", action="store_true",
                    help="build: with --land-textures, Skyrim's OWN ground textures (converted, on spare Starfield LTEX "
                         "records the terrain plugin overrides); needs --content-resources and --texconv")
    ap.add_argument("--skyrim-ground-test", action="store_true",
                    help="build --skyrim-ground: paint a magenta / green checkerboard instead of Skyrim's colours, to "
                         "see in game whether the overridden ground textures are what the terrain draws")
    ap.add_argument("--skyrim-ground-tiling", type=float, default=round(4096.0 / 6.0 / 70.0, 2),
                    help="build --skyrim-ground: metres per ground texture repeat (default 9.75, Skyrim's ~6 per cell; "
                         "Starfield's dirt uses 3.2)")
    ap.add_argument("--skyrim-ground-max", type=int, default=200, help="build: at most this many converted ground textures")
    ap.add_argument("--content-resources", default="", help="build --skyrim-ground: Starfield Tools\\ContentResources.zip")
    ap.add_argument("--ltex-mapping", default="", help="build: an edited ltex_mapping.json to override the automatic picks")
    a, rest = ap.parse_known_args(join_coordinates(sys.argv[1:] if argv is None else argv))
    if a.cmd in ("info", "worlds", "build") and not a.skyrim:
        sys.exit("--skyrim <Skyrim.esm> is required")
    if a.cmd in ("build", "check") and not (a.out and a.sf_data):
        sys.exit("--out and --sf-data are required")
    if a.cmd == "worlds":
        print(json.dumps(skyrimland.list_worlds(a.skyrim), indent=1))
        return 0
    if a.cmd == "info":
        if rest:
            sys.exit(f"unknown options: {rest}")
        return cmd_info(a)
    if a.cmd == "build":
        return cmd_build(a, rest)
    return cmd_check(a, rest)


if __name__ == "__main__":
    sys.exit(main())
