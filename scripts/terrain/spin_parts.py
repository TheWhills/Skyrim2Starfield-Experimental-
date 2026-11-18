"""Turning parts (the mill water wheel) for an already installed exterior, without restaging it: lists every reference
of a model with a turning part (manifest item "spin", skyrimconvert._spin_model) in the staged exterior's objects.json,
works out where the part's own reference goes (exterior.spin_pose: at the axle, the part's frame composed with the
reference's rotation), and copies the parts' models (with their geometry / material / texture files) into a staging
folder. dotnet/PluginSpike (SPIN_PARTS=<out>/spin_parts.json, tools/owner/riverwood_doors.ps1) then adds a copy of the
vanilla turning static per part and the references to FO4Port.esm, persistent in the world's persistent cell as the
outdoor furniture. docs/terrain/skyrim-objects.md "Animated objects".

    python -I scripts\\terrain\\spin_parts.py --exterior C:\\Modding\\staging\\skyrim_all --work C:\\Modding\\work\\sky_all --out <FO4Port staging>

Needs the exterior's models converted with turning parts (make_skyrim_objects.py convert after 2026-11-18, e.g.
tools\\owner\\exterior_collision.ps1); the static part of each model is the exterior's own, refreshed by that run.
An exterior staged with them already (make_skyrim_objects.py stage, bases with "anim_template") gets nothing here.
--around X Y R (metres, the exterior's frame) keeps only the parts within R of a point.
"""
import argparse
import json
import math
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import checkpoints, exterior  # noqa: E402

TEMPLATE = exterior.SPIN_TEMPLATE          # ACTI _AnimGraph_Standard_Idle_Loop_RotateY, slowed (exterior.spin_speed)
EDID_PREFIX = "S2SSpin_"


def plan(objects: dict, manifest: dict, around=None) -> dict:
    """spin_parts.json: {"template", "bases": [{"edid", "model", "bounds", "source", "template", "speed",
    "speed_from"}], "refs": [{"src", "of", "base",
    "pos", "rot", "scale", "disabled"}], "already_staged": n}. around = (x, y, r) metres or None."""
    items = {i["source"].replace("/", "\\").lower(): i for i in manifest["items"] if i.get("spin")}
    staged = sum(1 for b in objects["bases"] if b.get("anim_template"))
    out = {"template": TEMPLATE, "bases": [], "refs": [], "already_staged": staged}
    if staged:
        return out
    base_of = {}
    for r in objects["refs"]:
        b = objects["bases"][r["base"]]
        item = items.get((b.get("source") or "").replace("/", "\\").lower())
        if item is None:
            continue
        if around and math.hypot(r["pos"][0] - around[0], r["pos"][1] - around[1]) > around[2]:
            continue
        key = item["source"].lower()
        if key not in base_of:
            stem = b["edid"][len(objects.get("edid_prefix", "")):] if b["edid"].startswith(objects.get("edid_prefix", "")) \
                else b["edid"]
            base_of[key] = len(out["bases"])
            out["bases"].append({"edid": EDID_PREFIX + stem, "model": item["spin"]["model"],
                                 "bounds": item["spin"]["bounds"], "source": item["source"],
                                 "template": TEMPLATE, "speed_from": exterior.SPIN_SPEED_FROM,
                                 "speed": exterior.spin_speed(item["spin"]["period_s"])})
        pos, rot, scale = exterior.spin_pose(r["pos"], r["rot"], float(r.get("scale") or 1.0), item["spin"])
        out["refs"].append({"src": r["src"] + exterior.SPIN_SRC_SUFFIX, "of": r["src"], "base": base_of[key],
                            "pos": pos, "rot": rot, "scale": round(scale, 6), "disabled": bool(r.get("disabled"))})
    return out


def model_files(convert_dir: str, model: str, prefix: str = "skyrim"):
    """Relative paths (forward slashes) of a converted model and everything it names (checkpoints.output_inventory)."""
    out_name = "/".join(model.replace("\\", "/").split("/"))[:-len(".nif")]
    return sorted(checkpoints.output_inventory(convert_dir, {"out_name": out_name}, prefix))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exterior", required=True, help="the staged exterior (objects.json)")
    ap.add_argument("--work", required=True, help="its make_skyrim_objects.py work folder (convert\\manifest.json)")
    ap.add_argument("--out", required=True, help="FO4Port.esm's staging folder: spin_parts.json and the models")
    ap.add_argument("--around", nargs=3, type=float, metavar=("X", "Y", "R"))
    a = ap.parse_args(argv)
    with open(os.path.join(a.exterior, "objects.json"), encoding="utf-8") as f:
        objects = json.load(f)
    convert = os.path.join(a.work, "convert")
    with open(os.path.join(convert, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    p = plan(objects, manifest, a.around)
    copied = 0
    for b in p["bases"]:
        for rel in model_files(convert, b["model"]):
            d = os.path.join(a.out, *rel.split("/"))
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(os.path.join(convert, *rel.split("/")), d)
            copied += 1
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "spin_parts.json"), "w", encoding="utf-8") as f:
        json.dump(p, f, indent=1)
    if p["already_staged"]:
        print(f"the exterior already has its turning parts ({p['already_staged']} bases): none added")
    else:
        print(f"turning parts: {len(p['refs'])} references of {len(p['bases'])} models "
              f"({', '.join(b['source'] for b in p['bases']) or 'none: reconvert the exterior first?'}); "
              f"{copied} files into {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
