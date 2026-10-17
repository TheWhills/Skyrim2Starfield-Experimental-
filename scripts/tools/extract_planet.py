"""Copy one planet's surface data out of Starfield's archives (read-only), to find where on the planet to put an overlay:
its biome map (planetdata\\biomemaps\\<planet>.biom) and any other archived file naming the planet, plus every BIOM
record's FormID and EditorID from Starfield.esm (to name the biomes in the map). Writes a zip OUTSIDE the repository.

    python -I scripts\\tools\\extract_planet.py --sf-data "<Starfield>\\Data" --planet jemison --zip C:\\Modding\\work\\jemison.zip
"""
import argparse
import glob
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import ba2, fo4land  # noqa: E402


def biomes(esm):
    out = {}
    with fo4land.Plugin(esm) as p:
        rng = p.top_group(b"BIOM")
        if rng is None:
            return out
        for typ, off, _fl, fid in fo4land.iter_items(p.buf, *rng):
            if typ == "GRUP":
                continue
            edid = ""
            for sig, d in fo4land.iter_subrecords(fo4land.record_data(p.buf, off)):
                if sig == b"EDID":
                    edid = fo4land.zstring(d)
                    break
            out[f"{fid:08X}"] = edid
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sf-data", required=True)
    ap.add_argument("--planet", default="jemison")
    ap.add_argument("--zip", required=True)
    ap.add_argument("--max-bytes", type=int, default=64 * 2 ** 20, help="skip single files bigger than this")
    a = ap.parse_args(argv)
    if os.path.abspath(a.zip).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--zip must be outside the repository")
    planet = a.planet.lower()
    hits = []
    for p in sorted(glob.glob(os.path.join(a.sf_data, "*.ba2"))):
        try:
            arc = ba2.Ba2(p)
        except Exception:                                # noqa: BLE001 (texture archives etc.)
            continue
        for i, name in enumerate(arc.names):
            k = name.replace("\\", "/").lower()
            if planet in k.rsplit("/", 1)[-1] and (k.startswith("planetdata/") or k.endswith(".biom")):
                hits.append((p, i, name))
    print(f"{len(hits)} files naming {a.planet} under planetdata\\:")
    os.makedirs(os.path.dirname(os.path.abspath(a.zip)) or ".", exist_ok=True)
    with zipfile.ZipFile(a.zip, "w", zipfile.ZIP_DEFLATED) as z:
        for p, i, name in hits:
            arc = ba2.Ba2(p)
            e = arc.entries[i]
            size = e.unpacked or e.packed
            print(f"  {size:12,}  {name}  [{os.path.basename(p)}]")
            if size > a.max_bytes:
                continue
            z.writestr("files/" + name.replace("\\", "/"), arc.read(i))
        bm = biomes(os.path.join(a.sf_data, "Starfield.esm"))
        z.writestr("biomes.json", json.dumps(bm, indent=0))
        print(f"{len(bm)} BIOM records")
    print(f"-> {a.zip}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
