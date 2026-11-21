"""Lighting audit (read-only, 2026-11-21; owner: "its inconsistently lit ... the inn is super dark but faendals room
looks less dark"): per interior cell of the batch, how Skyrim lights it and what our build places, so the converter can
be made to light any room the way Skyrim does (docs/interior/lighting-model.md).

    python -I scripts/interior/light_audit.py --skyrim "$sky\\Skyrim.esm" --work C:\\Modding\\work\\s2s\\riverwood_doors

Per cell:
  * Skyrim: its lights (in use / initially disabled / off by default), radius and brightness (colour x fade), the cell's
    ambient, six directional ambient colours and directional light (where from: the cell or its lighting template).
  * Ours: the lights the plugin places (PluginSpike's merge within LIGHT_MERGE_M, its lumen rule, settings from
    <work>\\convert\\lighting.json), and which Skyrim lights the merge dropped.
  * Light on the top of every placed object (normal up) by fo4sf.lightmodel: Skyrim's ambient / directional / point
    light shares, and the ratio ours / Skyrim's (Starfield under the falloff hypothesis lightmodel.STARFIELD_FALLOFF,
    point lights only). Room-to-room: each cell's median ratio against the batch's, in stops; within a room: p90 / p10.
Writes <work>\\light_audit.json; prints the summary."""
import argparse
import json
import math
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import fo4land, lightmodel, skyriminterior  # noqa: E402

# PluginSpike's own defaults and make_skyrim_interior.INTERIOR_LIGHTING (the build's); lighting.json wins when present
DEFAULTS = {"LIGHT_MERGE_M": "1", "LIGHT_POWER": "2", "LIGHT_RADIUS_SCALE": "1", "SKYRIM_LIGHTS": "1",
            "LIGHT_MAX_SCALE": "256", "LIGHT_ADAPT": "1"}
# the rule before 2026-11-21's eye adaptation bake: cap 16, no per-room scale (the "before" columns)
BEFORE = {"LIGHT_MAX_SCALE": "16", "LIGHT_ADAPT": "0"}
# the base the build copies (OMNI_LIGHT 3197A6 LGT_Fire_Cauldron): verified values, the owner's SfInspect 2026-11-16
TEMPLATE_LM, TEMPLATE_RADIUS_M = 4000.0, 8.0
SKIP_BASES = {"COCMarkerHeading"}


def settings(work, cell):
    out = dict(DEFAULTS)
    path = os.path.join(work, "convert", "lighting.json") if work else ""
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            lj = json.load(fh)
        for k in ("*", cell):
            out.update({kk: str(v) for kk, v in (lj.get(k) or {}).items()})
    return out


def placed_lights(refs, s, room_scale=1.0):
    """PluginSpike's rule (Program.cs, the cell loop + SkyrimLight): lights in export order, one dropped when a placed
    one is within LIGHT_MERGE_M on every axis; radius max(units / 70, 1) x LIGHT_RADIUS_SCALE m; lumens = template x
    clamp(power x max(fade, 1) x max(1, (radius / template radius)^2), 1, LIGHT_MAX_SCALE) x the room's light_scale
    (when LIGHT_ADAPT is not 0). Returns (placed, merged): placed =
    [(ref, radius m, lumens)], merged = [(ref, the ref it merged into)]."""
    merge = float(s["LIGHT_MERGE_M"])
    power, rscale = float(s["LIGHT_POWER"]), float(s["LIGHT_RADIUS_SCALE"])
    cap = float(s.get("LIGHT_MAX_SCALE", "256"))
    scale = room_scale if s.get("LIGHT_ADAPT", "1") != "0" else 1.0
    placed, merged = [], []
    for r in refs:
        if r.get("type") != "Light":
            continue
        pm = [v / lightmodel.UNITS_PER_M for v in r["pos"]]
        hit = next((q for q in placed if all(abs(a / lightmodel.UNITS_PER_M - b) < merge
                                             for a, b in zip(q[0]["pos"], pm))), None)
        if hit:
            merged.append((r, hit[0]))
            continue
        L = r.get("light") or {}
        radius = max(float(L.get("radius", 300.0)) / lightmodel.UNITS_PER_M, 1.0) * rscale
        fade = max(float(L.get("fade", 1.0)), 0.05)
        area = max(1.0, (radius / TEMPLATE_RADIUS_M) ** 2)
        lm = TEMPLATE_LM * min(cap, max(1.0, power * max(fade, 1.0) * area)) * scale
        placed.append((r, radius, lm))
    return placed, merged


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return 0.0
    i = (len(xs) - 1) * q
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return xs[lo] + (xs[hi] - xs[lo]) * (i - lo)


def audit_cell(export, s, image_spaces=None):
    refs = [r for r in export["refs"]]
    lighting = export.get("lighting") or {}
    lights = [r for r in refs if r.get("type") == "Light" and r.get("light")]
    sky_lights = [(r["light"], r["pos"]) for r in lights if not r.get("disabled")]
    mean = lightmodel.room_mean_linear(lighting, refs)
    room_scale = lightmodel.adaptation_scale(mean)
    placed, merged = placed_lights(refs, s, room_scale)
    before, _m = placed_lights(refs, dict(s, **BEFORE))
    rows = []
    for p in lightmodel.sample_points(refs):
        sky = lightmodel.skyrim_light_at(lighting, sky_lights, p)
        sf = sum(lightmodel.starfield_point(lm, rad, q["pos"], p) for q, rad, lm in placed if not q.get("disabled"))
        sf0 = sum(lightmodel.starfield_point(lm, rad, q["pos"], p) for q, rad, lm in before if not q.get("disabled"))
        # what Skyrim shows: its light x its eye adaptation (the room's scale), linearised
        rows.append({"sky": lightmodel.luma(sky["total"]), "amb": lightmodel.luma(sky["ambient"]),
                     "dir": lightmodel.luma(sky["directional"]), "pts": lightmodel.luma(sky["points"]),
                     "sky_pts_linear": lightmodel.srgb_to_linear(lightmodel.luma(sky["points"])), "sf": sf, "sf0": sf0})
    lit = [x for x in rows if x["sky_pts_linear"] > 1e-4]
    # ours against what Skyrim's screen shows (its light x the adaptation, the same for every point of the room)
    ratios = [x["sf"] / (x["sky_pts_linear"] * room_scale) for x in lit if x["sf"] > 0]
    ratios0 = [x["sf0"] / (x["sky_pts_linear"] * room_scale) for x in lit if x["sf0"] > 0]
    dark = sum(1 for x in lit if x["sf"] <= 0)
    sky_tot = [x["sky"] for x in rows]
    sky_lin = [lightmodel.srgb_to_linear(min(1.0, v)) for v in sky_tot]
    ims = None
    if lighting.get("image_space") and image_spaces is not None:
        ims = image_spaces.get(int(lighting["image_space"].split(":")[0], 16))
    radii = [r["light"]["radius"] / lightmodel.UNITS_PER_M for r in lights]
    bright = [max(r["light"]["color"]) / 255.0 * (r["light"].get("fade", 1.0) + r["light"].get("ref_fade_delta", 0.0))
              for r in lights]
    return {
        "cell": export["cell"],
        "skyrim": {"lights": len(lights), "disabled": sum(1 for r in lights if r.get("disabled")),
                   "off_by_default": sum(1 for r in lights if r["light"].get("off_by_default")),
                   "radius_m": [round(min(radii), 1), round(statistics.median(radii), 1), round(max(radii), 1)]
                   if radii else [],
                   "brightness": [round(min(bright), 2), round(statistics.median(bright), 2), round(max(bright), 2)]
                   if bright else [],
                   "ambient": lighting.get("ambient"), "directional_ambient": lighting.get("directional_ambient"),
                   "directional": lighting.get("directional"), "directional_fade": lighting.get("directional_fade"),
                   "directional_rotation": lighting.get("directional_rotation"),
                   "from_template": lighting.get("from_template", []), "template": lighting.get("template"),
                   "image_space": lighting.get("image_space"), "image_space_data": ims},
        "per_light": [{"light": r["base_editor_id"], "formkey": r["formkey"],
                       "radius_m": round(r["light"]["radius"] / lightmodel.UNITS_PER_M, 2),
                       "skyrim_brightness": round(lightmodel.luma([v / 255.0 for v in r["light"]["color"]])
                                                  * (r["light"].get("fade", 1.0) + r["light"].get("ref_fade_delta", 0.0)), 3),
                       "ours_lm": next((round(lm) for q, _rad, lm in placed if q is r), None)} for r in lights],
        "ours": {"placed": len(placed), "merged": [{"light": m["base_editor_id"], "into": into["base_editor_id"],
                                                     "formkey": m["formkey"]} for m, into in merged],
                 "lumens": [round(min(lm for _q, _r, lm in placed)), round(statistics.median([lm for *_x, lm in placed])),
                            round(max(lm for _q, _r, lm in placed))] if placed else [],
                 "radius_m": [round(min(r for _q, r, _l in placed), 1), round(max(r for _q, r, _l in placed), 1)]
                 if placed else []},
        "points": len(rows),
        "adaptation": {"room_mean_linear": round(mean, 4) if mean else None, "light_scale": round(room_scale, 3)},
        "skyrim_light": {"median": round(statistics.median(sky_tot), 3) if sky_tot else 0,
                         "p10": round(pct(sky_tot, 0.1), 3), "p90": round(pct(sky_tot, 0.9), 3),
                         "mean_linear": round(statistics.fmean(sky_lin), 4) if sky_lin else 0,
                         "share_ambient": round(sum(x["amb"] for x in rows) / max(1e-9, sum(sky_tot)), 2),
                         "share_directional": round(sum(x["dir"] for x in rows) / max(1e-9, sum(sky_tot)), 2),
                         "share_points": round(sum(x["pts"] for x in rows) / max(1e-9, sum(sky_tot)), 2)},
        "ours_vs_skyrim": {"median": round(statistics.median(ratios), 2) if ratios else None,
                           "median_before": round(statistics.median(ratios0), 2) if ratios0 else None,
                           "spread_stops": round(math.log2(pct(ratios, 0.9) / pct(ratios, 0.1)), 2)
                           if len(ratios) > 1 and pct(ratios, 0.1) > 0 else None,
                           "lit_in_skyrim_dark_here": dark},
    }


def summarise(cells):
    """Each cell's median ours / Skyrim's screen against the batch's, in stops, for the current rule and the one before
    (the same reference: the before rule's batch median, so the columns compare)."""
    meds0 = [c["ours_vs_skyrim"]["median_before"] for c in cells if c["ours_vs_skyrim"]["median_before"]]
    ref = statistics.median(meds0) if meds0 else None
    for c in cells:
        o = c["ours_vs_skyrim"]
        for k, out in (("median", "vs_batch_stops"), ("median_before", "vs_batch_stops_before")):
            o[out] = round(math.log2(o[k] / ref), 2) if o[k] and ref else None
    return ref


def batch_cells(work, extra):
    names = list(extra or [])
    path = os.path.join(work, "cells.txt") if work else ""
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    with open(line, encoding="utf-8") as c:
                        names.append(json.load(c)["cell"])
    return names


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim", required=True, help="Skyrim.esm")
    ap.add_argument("--work", default="", help="interior batch work folder (cells.txt, convert\\lighting.json)")
    ap.add_argument("--cell", action="append", default=[], help="Skyrim cell EditorID (repeatable)")
    ap.add_argument("--out", default="", help="JSON out (default <work>\\light_audit.json)")
    a = ap.parse_args(argv)
    names = batch_cells(a.work, a.cell)
    if not names:
        ap.error("no cells: give --work with cells.txt or --cell")
    cells = []
    with fo4land.Plugin(a.skyrim) as p:
        src = skyriminterior.Source(p, "Skyrim.esm")
        for n in names:
            exp = src.export(n)
            cells.append(audit_cell(exp, settings(a.work, exp["cell"]), src.image_spaces()))
    ref = summarise(cells)
    print(f"falloff model for ours: {lightmodel.STARFIELD_FALLOFF}; Skyrim's screen = its light x its eye adaptation "
          f"(ADAPT_REF {lightmodel.ADAPT_REF}, strength {lightmodel.ADAPT_STRENGTH}); before = cap 16, no adaptation; "
          f"now = the build's rule. Stops against the before rule's batch median ({ref})")
    print(f"{'cell':34} {'sky lights':>10} {'placed':>6} {'merged':>6} {'Skyrim light p10/med/p90':>25} "
          f"{'amb/dir/pts':>14} {'adapt x':>8} {'before':>9} {'now':>9} {'spread':>7} {'dark':>5}")
    for c in cells:
        sk, sl, ov = c["skyrim"], c["skyrim_light"], c["ours_vs_skyrim"]
        vs = "" if ov["vs_batch_stops"] is None else f"{ov['vs_batch_stops']:+.2f} st"
        vs0 = "" if ov["vs_batch_stops_before"] is None else f"{ov['vs_batch_stops_before']:+.2f} st"
        spread = "" if ov["spread_stops"] is None else f"{ov['spread_stops']:.1f}"
        print(f"{c['cell'][:34]:34} {sk['lights']:>10} {c['ours']['placed']:>6} {len(c['ours']['merged']):>6} "
              f"{sl['p10']:>8.2f}/{sl['median']:.2f}/{sl['p90']:.2f}      "
              f"{sl['share_ambient']:.2f}/{sl['share_directional']:.2f}/{sl['share_points']:.2f} "
              f"{c['adaptation']['light_scale']:>8.2f} {vs0:>9} {vs:>9} {spread:>7} {ov['lit_in_skyrim_dark_here']:>5}")
        print(f"    ambient {sk['ambient']}  directional {sk['directional']} x{sk['directional_fade']} "
              f"rot {sk['directional_rotation']}  from template {sk['from_template'] or '-'}")
        ims = sk["image_space_data"]
        print(f"    image space {sk['image_space'] or 'none (game default)'}"
              + (f" {ims.get('editor_id')} hdr {ims.get('hdr')} cinematic {ims.get('cinematic')} tint {ims.get('tint')}"
                 if ims else "") + f"; mean Skyrim light (linear) {sl['mean_linear']}")
        if sk["directional_ambient"]:
            print("    directional ambient " + " ".join(f"{k}{v}" for k, v in sk["directional_ambient"].items()))
        print(f"    Skyrim radius m min/med/max {sk['radius_m']}  colour x fade {sk['brightness']}  "
              f"disabled {sk['disabled']} off {sk['off_by_default']}; ours lumens {c['ours']['lumens']}")
        if c["ours"]["merged"]:
            print("    merged away: " + ", ".join(f"{m['light']} -> {m['into']}" for m in c["ours"]["merged"][:8]))
    out = a.out or (os.path.join(a.work, "light_audit.json") if a.work else "light_audit.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"falloff_model": lightmodel.STARFIELD_FALLOFF, "batch_median": ref, "cells": cells}, fh, indent=1)
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
