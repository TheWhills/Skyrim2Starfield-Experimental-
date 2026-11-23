"""Which grass Skyrim grows around one spot, and what our native-grass build grows there instead (read-only).

2026-11-23, after the first family-material build: the Riverwood forest floor grew no grass and the clumps elsewhere
were all pale straw, so it was unclear which Skyrim grass families those places belong to. Prints, per Skyrim ground
texture within --radius of the spot (largest share first):

  * its share of the area and the Skyrim grasses it grows (Skyrim density %, slope range);
  * the Starfield texture slot our terrain draws it with and every grass that slot's ground cover grows (several
    Skyrim textures can share one slot, and then all their grasses grow on all of them);
  * per grass, from grass_native.json: our model path (own vanilla path or shared) and its game material.

Positions as for ground_at.py / ground_tone.py.

    python -I scripts\\terrain\\grass_at.py --skyrim "<Skyrim SE>\\Data\\Skyrim.esm" ^
        --terrain C:\\Modding\\staging\\skyrim_all --grass "<MO2 mods>\\S2S Grass Native" --pos -1848.57 913.23
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)


def grass_line(edid, gras, report):
    """One grass: Skyrim density / slopes, our model (own path or shared) and material."""
    g = gras or {}
    rep = report or {}
    own = (rep.get("vanilla_paths") or {}).get(edid)
    shared = (rep.get("shared_models") or {}).get(edid)
    mat = (rep.get("materials") or {}).get(edid, "")
    if not mat and shared:              # a shared model wears the material of the grass that owns that path
        for e, p in (rep.get("vanilla_paths") or {}).items():
            if p.split("\\", 1)[-1].lower() == shared.lower():
                mat = (rep.get("materials") or {}).get(e, "")
                break
    if edid in (rep.get("failed") or {}):
        model = "FAILED"
    elif own:
        model = own.rsplit("\\", 1)[-1]
    elif shared:
        model = "shares " + shared.rsplit("\\", 1)[-1]
    elif edid in (rep.get("grasses") or {}):
        model = rep["grasses"][edid].get("model", "?").rsplit("\\", 1)[-1]
    else:
        model = "not in build"
    dens = g.get("density")
    return (f"{edid:<20} density {dens if dens is not None else '?':>3}  slope "
            f"{g.get('min_slope', '?')}-{g.get('max_slope', '?')}  {model}"
            + (f"  [{mat.rsplit(chr(92), 1)[-1]}]" if mat else ""))


def describe(near, ltex_info, ltex_grass, gras_sky, mapping, overrides, report):
    """Lines for the area: near {Skyrim LTEX fid: (weight, ...)}, ltex_info {fid: {"edid"}}, ltex_grass {fid: [GRAS]},
    gras_sky {GRAS fid: {"edid", "density", ...}}, mapping ltex_mapping "skyrim" dict, overrides overlays_params
    "ltex_overrides", report grass_native.json."""
    by_edid = {v.get("edid"): v.get("starfield") for v in (mapping or {}).values()}
    slot_of = {"SKYG_" + o["skyrim"]: int(o["form_id"]) for o in overrides or ()}
    slots = (report or {}).get("slots") or {}
    gras_by_edid = {v["edid"]: v for v in gras_sky.values()}
    total = sum(v[0] for v in near.values()) or 1.0
    out = []
    for fid, val in sorted(near.items(), key=lambda kv: -kv[1][0]):
        edid = ltex_info.get(fid, {}).get("edid", "(engine default)" if fid == 0 else f"{fid:08X}")
        own = [gras_sky[g]["edid"] for g in ltex_grass.get(fid, []) if g in gras_sky]
        out.append(f"{edid}  {100 * val[0] / total:.0f} %  Skyrim grows: {', '.join(own) or 'no grass'}")
        sf = by_edid.get(edid)
        slot = slot_of.get(sf) if sf else None
        if sf is None:
            out.append("    our terrain: not mapped (no grass)")
        elif slot is None:
            out.append(f"    our terrain: {sf} (a vanilla Starfield texture: no grass, by design)")
        else:
            grown = slots.get(f"{slot:08X}")
            if grown is None:
                out.append(f"    our terrain: {sf} ({slot:08X}): no ground cover in this build")
            else:
                out.append(f"    our terrain: {sf} ({slot:08X}), its ground cover grows {len(grown)}:")
                for e in grown:
                    out.append("      " + ("* " if e in own else "  ") + grass_line(e, gras_by_edid.get(e), report))
    out.append("(* = a grass Skyrim grows on that texture; the others come from textures sharing the slot)")
    return out


def skyrim_units(ov, pos=None, spawn_at=None, skyrim_pos=None):
    """The spot in Skyrim units: --skyrim-pos as given, else the Starfield position shifted into the overlay frame
    (through the coc marker when spawn_at is given) and scaled by 70 units per metre."""
    if skyrim_pos:
        return float(skyrim_pos[0]), float(skyrim_pos[1])
    x, y = pos
    if spawn_at:
        sx, sy = ov["spawn"][:2]
        x, y = x - spawn_at[0] + sx, y - spawn_at[1] + sy
    ox, oy = (float(v) for v in ov.get("origin_cw_m", [0, 0]))
    return (x + ox) * 70.0, (y + oy) * 70.0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True, help="Skyrim.esm")
    ap.add_argument("--terrain", required=True, help="the staged exterior (e.g. C:\\Modding\\staging\\skyrim_all)")
    ap.add_argument("--grass", required=True, help="the native-grass mod folder (grass_native.json, and "
                                                   "ltex_mapping_inferred.json when the staging has no mapping)")
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--pos", type=float, nargs=2, metavar=("X", "Y"), help="Starfield player.getpos x / y (m)")
    where.add_argument("--skyrim-pos", type=float, nargs=2, metavar=("X", "Y"),
                       help="Skyrim's player.getpos x / y (game units) at the same spot: no frame shift to get wrong "
                            "(2026-11-23: a Starfield position read after walking away from the coc spot, given as "
                            "--spawn-at too, pointed at the spawn instead)")
    ap.add_argument("--spawn-at", type=float, nargs=2, metavar=("X", "Y"), help="as ground_at.py")
    ap.add_argument("--radius", type=float, default=10.0, help="metres around the spot (default 10)")
    a = ap.parse_args(argv)
    from fo4sf import landtex, skyrimgrass
    import ground_tone
    with open(os.path.join(a.terrain, "overlays_params.json"), encoding="utf-8") as f:
        prm = json.load(f)
    ov = prm["overlays"][0]
    xu, yu = skyrim_units(ov, a.pos, a.spawn_at, a.skyrim_pos)
    mapping = None
    for p in (os.path.join(a.terrain, "ltex_mapping.json"), os.path.join(a.grass, "ltex_mapping_inferred.json")):
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                mapping = json.load(f).get("skyrim", {})
            break
    if mapping is None:
        sys.exit("no ltex_mapping.json in the staging and no ltex_mapping_inferred.json in --grass: run the grass "
                 "build first")
    rp = os.path.join(a.grass, "grass_native.json")
    if not os.path.isfile(rp):
        sys.exit(f"{rp} not found: run skyrim_grass_native.py first")
    with open(rp, encoding="utf-8") as f:
        report = json.load(f)
    cells, ltex = landtex.read_world_textures(a.skyrim)
    near = ground_tone.area_textures(cells, {}, xu, yu, a.radius * 70.0)
    if not near:
        sys.exit(f"no Skyrim LAND textures within {a.radius:g} m of ({a.pos[0]:g}, {a.pos[1]:g})")
    ltex_grass, gras_sky = skyrimgrass.read_grass(a.skyrim)
    print(f"within {a.radius:g} m of Skyrim ({xu:.0f}, {yu:.0f}) units, cell ({int(xu // 4096)}, {int(yu // 4096)}):")
    for line in describe(near, ltex, ltex_grass, gras_sky, mapping, prm.get("ltex_overrides") or [], report):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
