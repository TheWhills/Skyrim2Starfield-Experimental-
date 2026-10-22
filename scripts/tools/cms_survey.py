"""Check the compressed-mesh format reading behind native Skyrim collision (src/fo4sf/cmsencode.py) on vanilla
Starfield collision: every hknpCompressedMeshShape in the first --max NIFs of Starfield - Meshes*.ba2 is walked with the
encoder's own tree reader (meshcollision.survey_sf_meshes). Read-only; writes a JSON summary.

    python -I scripts\\tools\\cms_survey.py --starfield-data "<Starfield>\\Data" --out <dir> [--max 400]

Zero problems = Starfield's trees use the codec the encoder writes (verified so far on 34 FO4 meshes only)."""
import argparse
import json
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))
from fo4sf import ba2, meshcollision, nif as nifmod  # noqa: E402


def blobs(nif_bytes):
    n = nifmod.parse(nif_bytes)
    for i in range(len(n.blocks)):
        if n.type_of(i) == "bhkPhysicsSystem":
            ln, = struct.unpack_from("<I", n.blocks[i], 0)
            yield n.blocks[i][4:4 + ln]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield-data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max", type=int, default=400, help="NIFs with a compressed mesh to survey")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    rep = {"nifs": 0, "meshes": 0, "sections": 0, "triangles": 0, "max_prims": 0, "with_problems": [], "errors": {}}
    for fn in sorted(os.listdir(a.starfield_data)):
        if not (fn.lower().startswith("starfield - meshes") and fn.lower().endswith(".ba2")):
            continue
        arc = ba2.Ba2(os.path.join(a.starfield_data, fn))
        for k, name in enumerate(arc.names):
            if rep["nifs"] >= a.max:
                break
            if not name.lower().endswith(".nif"):
                continue
            try:
                data = arc.read(k)
                if b"hknpCompressedMeshShape" not in data:
                    continue
                found = False
                for blob in blobs(data):
                    for m in meshcollision.survey_sf_meshes(blob):
                        found = True
                        rep["meshes"] += 1
                        rep["sections"] += m["sections"]
                        rep["triangles"] += m["triangles"]
                        rep["max_prims"] = max(rep["max_prims"], m["max_prims"])
                        if m["problems"]:
                            rep["with_problems"].append({"nif": name, "problems": m["problems"][:5]})
                rep["nifs"] += found
            except Exception as e:                       # noqa: BLE001  (survey: count and continue)
                key = f"{type(e).__name__}: {e}"[:100]
                rep["errors"][key] = rep["errors"].get(key, 0) + 1
    with open(os.path.join(a.out, "cms_survey.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=1)
    print(f"{rep['nifs']} NIFs, {rep['meshes']} compressed meshes, {rep['sections']} sections, {rep['triangles']} "
          f"triangles; {len(rep['with_problems'])} with problems; {sum(rep['errors'].values())} unreadable")
    return 0 if not rep["with_problems"] else 1


if __name__ == "__main__":
    sys.exit(main())
