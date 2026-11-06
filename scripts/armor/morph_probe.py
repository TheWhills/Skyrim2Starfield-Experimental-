"""Where Starfield keeps the body-slider morphs (morph.dat) of worn clothing and the naked body, and whether our reader
(fo4sf.sfmorph) reads them right (2026-11-06: converted gear does not follow the player's body sliders; vanilla worn
meshes carry a morph.dat).

Lists every archive entry with 'morph' in its path (count per folder, examples), picks the ones for the vanilla
nightwear (the template our armor copies), the naked bodies and the miner utility suit, reads them, and checks the
vertex count against the meshes their NIFs name. Writes morph_probe.json into --out.

    python -I scripts\\armor\\morph_probe.py --starfield "D:\\...\\Starfield" --out "C:\\Modding\\work\\morph_probe"
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import ba2, sfmorph, sfnif  # noqa: E402
from fo4sf import nif as nifmod  # noqa: E402

WANT = ("nightwear", "naked", "miner_utilitysuit")
NIFS = ("meshes/clothes/outfit_nightwear_01/outfit_nightwear_lowerbody_01_m.nif",
        "meshes/actors/human/mesh/naked_body/naked_m.nif")


def archives(sf_data: str):
    for fn in sorted(os.listdir(sf_data)):
        if fn.lower().startswith("starfield - ") and fn.lower().endswith(".ba2"):
            yield fn, ba2.Ba2(os.path.join(sf_data, fn))


def mesh_vertices(nif_bytes: bytes):
    """[(shape name, vertex count of LOD0)] of a NIF."""
    n = nifmod.parse(nif_bytes)
    out = []
    for i, b in enumerate(n.blocks):
        if n.type_of(i) == "BSGeometry":
            g = sfnif.parse_bsgeometry(b)
            m = next((x for x in g.meshes if x is not None), None)
            name = n.strings[g.name_idx].decode("latin-1") if 0 <= g.name_idx < len(n.strings) else ""
            out.append((name, m.num_verts if m else None))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    sf_data = os.path.join(a.starfield, "Data")
    found, nifs, folders = {}, {}, Counter()
    for fn, arc in archives(sf_data):
        for i, name in enumerate(arc.names):
            p = name.replace("\\", "/").lower()
            if "morph" in p:
                folders["/".join(p.split("/")[:4])] += 1
                if any(w in p for w in WANT) and len(found) < 40:
                    found[p] = (fn, i)
            if p in NIFS:
                nifs[p] = arc.read(i)
    rep = {"morph_folders": folders.most_common(40), "matches": {}, "nifs": {}}
    for p, data in nifs.items():
        rep["nifs"][p] = mesh_vertices(data)
    by_arc = {}
    for p, (fn, i) in found.items():
        by_arc.setdefault(fn, []).append((p, i))
    for fn, items in by_arc.items():
        arc = ba2.Ba2(os.path.join(sf_data, fn))
        for p, i in items:
            data = arc.read(i)
            entry = {"archive": fn, "bytes": len(data)}
            if p.endswith(".dat"):
                try:
                    entry.update(sfmorph.summary(sfmorph.parse(data)))
                except Exception as e:                            # report, keep going
                    entry["error"] = str(e)
                    entry["head_hex"] = data[:96].hex()
            rep["matches"][p] = entry
    os.makedirs(a.out, exist_ok=True)
    dst = os.path.join(a.out, "morph_probe.json")
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    print("morph folders:", *[f"{f} ({n})" for f, n in rep["morph_folders"][:12]], sep="\n  ")
    for p, v in rep["nifs"].items():
        print(f"{p}: shapes {v}")
    for p, e in rep["matches"].items():
        if "error" in e:
            print(f"{p}: READ ERROR {e['error']}")
        elif "keys" in e:
            ks = ", ".join(f"{k} {e['per_key'][k]['vertices']}v max {e['per_key'][k]['max_m'] * 1000:.0f}mm"
                           for k in e["keys"][:6])
            print(f"{p}: {e['vertices']} vertices, {len(e['keys'])} keys ({ks}), in order "
                  f"{e['layout']['records_in_vertex_order']}")
        else:
            print(f"{p}: {e['bytes']} bytes")
    print("wrote", dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
