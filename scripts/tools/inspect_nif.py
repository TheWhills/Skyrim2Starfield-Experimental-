"""What is inside a few Skyrim models, shape by shape (read-only): geometry block, vertex / triangle counts, shader block,
Skyrim shader type, shader flags, emissive, textures, alpha, double-sided, and what the converter does with the shape.
For "why does this look wrong in game": pick the models by name, or by a regex over the models of an interior export.

    python -I scripts\\tools\\inspect_nif.py --skyrim-data "<Skyrim SE>\\Data" --work C:\\Modding\\work\\int_inn ^
        --find "fire|ember|flame|pit|candle|torch|lantern" --zip C:\\Modding\\work\\int_inn\\inspect.zip
    python -I scripts\\tools\\inspect_nif.py --skyrim-data ... --name meshes\\effects\\fxfirewithembers01.nif

Prints a table and writes <zip>.json next to the zip (the table as data) plus the source NIFs in the zip, so both can
be uploaded. Nothing is written into the game folders or this repository.
"""
import argparse
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import bsa, exterior, nif as nifmod, skyrimnif  # noqa: E402


def converter_decision(info, alpha, has_normal):
    """Mirror of SkyrimConverter._shape_material (no textures converted here)."""
    test, blend, _ = alpha
    if info["type"] is None:
        return "neutral material (no shader)"
    if info["type"] == "BSEffectShaderProperty":
        return "SKIPPED (effect shader)"
    if not info.get("textures"):
        return "neutral material (no textures)"
    kind = "decal" if blend and not test else "cutout" if test else "opaque"
    if not has_normal and kind != "decal":
        return "neutral material (no normal map)"
    return f"{kind} material from the diffuse"


def inspect(src, name):
    raw = src.mesh(name)
    if raw is None:
        return {"nif": name, "error": "not in the archives"}
    try:
        n = nifmod.parse(raw)
        shapes = skyrimnif.trishapes(n)
    except Exception as e:                       # noqa: BLE001  (reported per model)
        return {"nif": name, "error": f"{type(e).__name__}: {e}"}
    out = []
    for s in shapes:
        info = skyrimnif.shader_info(n, s.shader_ref)
        alpha = skyrimnif.alpha_test(n, s.alpha_ref)
        paths = skyrimnif.texture_set(n, s.shader_ref) or []
        lo = [min(p[a] for p in s.positions) for a in range(3)]
        hi = [max(p[a] for p in s.positions) for a in range(3)]
        out.append({"name": s.name.decode("latin-1", "replace") if isinstance(s.name, bytes) else s.name,
                    "block": n.type_of(s.block), "verts": len(s.positions), "tris": len(s.triangles),
                    "size_units": [round(h - l, 1) for l, h in zip(lo, hi)], "skinned": bool(s.skinned),
                    "shader": info, "alpha": {"test": alpha[0], "blend": alpha[1], "ref": alpha[2]},
                    "double_sided": skyrimnif.double_sided(n, s.shader_ref),
                    "converter": converter_decision(info, alpha, len(paths) > 1 and bool(paths[1]))})
    others = sorted({n.type_of(i) for i in range(len(n.blocks))} - {"NiNode", "BSFadeNode"})
    return {"nif": name, "shapes": out, "block_types": others}


def models_from_work(work, rx):
    with open(os.path.join(work, "convert_input.json"), encoding="utf-8") as f:
        refs = json.load(f)["refs"]
    return [exterior.source_key(r["model"]) for r in refs if rx.search(r["model"])]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 allow_abbrev=False)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--name", action="append", default=[], help="a mesh path (repeatable)")
    ap.add_argument("--work", help="an interior / objects work folder (its convert_input.json)")
    ap.add_argument("--find", default="", help="with --work: regex over model paths")
    ap.add_argument("--zip", help="also zip the source NIFs here (OUTSIDE the repository) and write <zip>.json")
    a = ap.parse_args(argv)
    names = list(a.name)
    if a.work:
        names += models_from_work(a.work, re.compile(a.find or ".", re.I))
    if not names:
        sys.exit("nothing to inspect: pass --name, or --work with --find")
    if a.zip and os.path.abspath(a.zip).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--zip must be outside the repository")
    src = bsa.SkyrimArchives(a.skyrim_data)
    results = [inspect(src, nm) for nm in dict.fromkeys(names)]
    for r in results:
        print(f"\n{r['nif']}")
        if "error" in r:
            print(f"  ERROR {r['error']}")
            continue
        print(f"  other blocks: {', '.join(r['block_types'])}")
        for s in r["shapes"]:
            sh, al = s["shader"], s["alpha"]
            print(f"  [{s['block']}] {s['name']!r} {s['verts']}v {s['tris']}t size {s['size_units']}"
                  f"{' SKINNED' if s['skinned'] else ''}")
            print(f"     {sh['type']} {sh.get('shader_type', '')} f1={sh.get('flags1')} f2={sh.get('flags2')}"
                  f" emit={sh.get('emissive')}x{sh.get('emissive_multiple')} alpha test={al['test']} blend={al['blend']}"
                  f" ref={al['ref']} double={s['double_sided']}")
            for t in sh.get("textures", []):
                print(f"     tex {t}")
            print(f"     -> {s['converter']}")
    if a.zip:
        os.makedirs(os.path.dirname(os.path.abspath(a.zip)) or ".", exist_ok=True)
        with zipfile.ZipFile(a.zip, "w", zipfile.ZIP_DEFLATED) as z:
            for r in results:
                data = src.mesh(r["nif"])
                if data is not None:
                    z.writestr(bsa.norm(r["nif"]).replace("\\", "/"), data)
            z.writestr("inspect.json", json.dumps(results, indent=1))
        with open(a.zip + ".json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=1)
        print(f"\n{len(results)} models -> {a.zip} (+ {a.zip}.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
