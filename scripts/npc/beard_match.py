"""Match each Skyrim beard to the closest-shaped vanilla Starfield beard, so converted NPCs wear Starfield's own
beards instead of converted Skyrim ones (2026-11-07, owner: "all the Skyrim beards match up to a Starfield one pretty
well; match them and just have them be Starfield's").

Reads Skyrim.esm's facial-hair head parts (HDPT type 4) and their meshes from the Skyrim archives, placed on
Starfield's head by the hair pipeline's head placement (skyrimhair.convert), and Starfield.esm's facial-hair head
parts and their meshes from the game archives. Shape distance: the symmetric mean closest-point distance between the
two point sets (both in Starfield skeleton space, metres). Writes beard_match.json:
  {"matches": {Skyrim EditorID: {"starfield": EditorID, "form_id": "XXXXXXXX", "distance_mm": d,
                                 "next": [[EditorID, d], ...]}}, "starfield_beards": [...], "skipped": [...]}
Edit "starfield" / "form_id" by hand to override a match; face_fit.py --beard-map uses it.

    python -I scripts\\npc\\beard_match.py --skyrim-data "<Skyrim>\\Data" --starfield "<Starfield>" --out <folder>
"""
import argparse
import json
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts", "armor"))

from fo4sf import bsa, sfplugin, skyrimhair  # noqa: E402

FACIAL_HAIR = 4
SAMPLE = 1500


def sample(points, n: int = SAMPLE, seed: int = 0) -> np.ndarray:
    p = np.asarray(points, float).reshape(-1, 3)
    if len(p) <= n:
        return p
    return p[np.random.default_rng(seed).choice(len(p), n, replace=False)]


def chamfer(a, b, chunk: int = 512) -> float:
    """Symmetric mean closest-point distance between two point sets."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if not len(a) or not len(b):
        return float("inf")

    def one(x, y):
        out = []
        yy = (y * y).sum(1)
        for c in range(0, len(x), chunk):
            q = x[c:c + chunk]
            d2 = (q * q).sum(1)[:, None] + yy[None, :] - 2 * q @ y.T
            out.append(np.sqrt(np.maximum(d2.min(1), 0)))
        return float(np.concatenate(out).mean())
    return (one(a, b) + one(b, a)) / 2


def rank(sky_pts, sf_sets: dict) -> list:
    """[(Starfield EditorID, distance m)] best first."""
    return sorted(((k, chamfer(sky_pts, v)) for k, v in sf_sets.items()), key=lambda kv: kv[1])


def skyrim_beards(esm: str) -> list:
    """[(EditorID, [model paths])] of Skyrim.esm's facial-hair head parts (with their extra parts' models)."""
    import npc_hair
    hdpt, _clfm = npc_hair.head_parts(esm)
    return [(p["edid"], npc_hair.part_models(fid, hdpt)) for fid, p in sorted(hdpt.items())
            if p.get("type") == FACIAL_HAIR and p.get("model")]


def starfield_beards(sf_esm: str) -> list:
    """[(EditorID, FormID, model)] of Starfield.esm's facial-hair head parts that have a model."""
    import npc_hair
    out = []
    for _t, _h, subs, fid in sfplugin.records(sf_esm, [b"HDPT"]):
        if npc_hair.part_type(subs) != FACIAL_HAIR:
            continue
        model = next((bytes(d).rstrip(b"\0").decode("latin-1") for s, d in subs if s == b"MODL"), "")
        if model:
            out.append((sfplugin.edid(subs), fid, model))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    import gear_fit
    import hkx_to_af
    import npc_hair
    sf_data = os.path.join(a.starfield, "Data")
    world = npc_hair.skeleton_world(hkx_to_af.vanilla_file(npc_hair.SF_SKELETON, sf_data)[0])
    sky = bsa.SkyrimArchives(a.skyrim_data)
    rep = {"matches": {}, "starfield_beards": [], "skipped": []}
    sf_sets, sf_ids = {}, {}
    for edid, fid, model in starfield_beards(os.path.join(sf_data, "Starfield.esm")):
        try:
            pts, _t, _w = gear_fit.starfield_part(sf_data, "meshes/" + model.replace("\\", "/"), world)
        except (SystemExit, Exception) as e:          # report, keep going
            rep["skipped"].append(f"Starfield {edid}: {e}")
            continue
        sf_sets[edid], sf_ids[edid] = sample(pts), fid
        rep["starfield_beards"].append(edid)
    print(f"Starfield beards: {len(sf_sets)}")
    for edid, models in skyrim_beards(os.path.join(a.skyrim_data, "Skyrim.esm")):
        pts = []
        for m in models:
            rel = "meshes\\" + re.sub(r"^meshes[\\/]", "", m.replace("/", "\\"), flags=re.I)
            raw = sky._read(bsa.norm(rel))
            if raw is None:
                continue
            try:
                h = skyrimhair.convert(raw, None, world)
            except Exception as e:                       # report, keep going
                rep["skipped"].append(f"Skyrim {edid} {m}: {e}")
                continue
            pts += [np.asarray(sh.positions, float) for sh in h.shapes]
        if not pts or not sf_sets:
            rep["skipped"].append(f"Skyrim {edid}: no mesh")
            continue
        r = rank(sample(np.concatenate(pts)), sf_sets)
        best, d = r[0]
        rep["matches"][edid] = {"starfield": best, "form_id": f"{sf_ids[best]:08X}", "distance_mm": round(d * 1000, 1),
                                "next": [[k, round(x * 1000, 1)] for k, x in r[1:4]]}
        print(f"  {edid} -> {best} ({d * 1000:.1f} mm; next {', '.join(k for k, _x in r[1:3])})")
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "beard_match.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    for s in rep["skipped"]:
        print("skipped:", s)
    print("written:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
