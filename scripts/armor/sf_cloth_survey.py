"""Survey Starfield Havok cloth (read-only): every NIF with BSClothExtraData (loose or inside .ba2 archives) and every
loose cloth .hkx, summarised with fo4sf.sfcloth: bone-driving vs mesh cloth, particles / pinned, constraint-set and
collider classes, the bones the cloth drives and the bone they hang from. Finds vanilla cloth to learn from and to
use as a writer template (docs/armor/animation-port.md "Starfield cloth").

    python -I scripts\\armor\\sf_cloth_survey.py --root "%SF%\\Data" --out C:\\Modding\\work\\sfcloth
    python -I scripts\\armor\\sf_cloth_survey.py --root <mod folder> --root <other mod> --out ...
    (--filter hair,clothes,outfit limits archive entries by path words; default: every .nif)
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import ba2 as ba2mod  # noqa: E402
from fo4sf import hktagfile  # noqa: E402
from fo4sf import nif as nifmod  # noqa: E402
from fo4sf import sfcloth as C  # noqa: E402

MARK = b"BSClothExtraData"


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


def from_nif(data: bytes):
    if MARK not in data:
        return []
    n = nifmod.parse(data)
    return [C.payload(b) for i, b in enumerate(n.blocks) if n.type_of(i) == "BSClothExtraData"]


def sources(roots, words):
    """(label, bytes loader, kind) for every loose .nif / .hkx and every archived .nif."""
    for root in roots:
        for d, _ds, fs in os.walk(root):
            for f in sorted(fs):
                p, low = os.path.join(d, f), f.lower()
                rel = os.path.relpath(p, root)
                if low.endswith((".nif", ".hkx")):
                    yield rel, (lambda p=p: _read(p)), low[-3:]
                elif low.endswith(".ba2"):
                    try:
                        a = ba2mod.Ba2(p)
                    except ba2mod.Ba2Error:
                        continue
                    if a.kind != "GNRL":
                        continue
                    for i, name in enumerate(a.names):
                        nl = name.lower()
                        if nl.endswith(".nif") and (not words or any(w in nl for w in words)):
                            yield f"{f}:{name}", (lambda a=a, i=i: a.read(i)), "nif"


def survey(roots, words=()):
    out, errors = [], []
    for label, load, kind in sources(roots, words):
        try:
            data = load()
            blobs = from_nif(data) if kind == "nif" else ([data] if data[4:8] == b"TAG0" else [])
            for blob in blobs:
                s = C.summary(blob)
                s["file"] = label
                s["chains"] = C.chains(s)
                out.append(s)
        except (C.ClothError, hktagfile.TagfileError, nifmod.NifError, ValueError, KeyError, IndexError) as e:
            errors.append(f"{label}: {type(e).__name__}: {e}")
    return {"roots": list(roots), "cloth": len(out), "stats": C.stats(out), "errors": errors, "files": out}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", action="append", required=True)
    ap.add_argument("--filter", default="", help="comma-separated words an archived path must contain")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    words = [w.strip().lower() for w in a.filter.split(",") if w.strip()]
    r = survey(a.root, words)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "sf_cloth_survey.json"), "w", encoding="utf-8") as fh:
        json.dump(r, fh, indent=1)
    print(f"{r['cloth']} cloth setups; errors: {len(r['errors'])}")
    for k, v in r["stats"].items():
        print(f"  {k}: {v}")
    for s in r["files"][:40]:
        sim = s["sims"][0] if s["sims"] else {}
        print(f"{s['file']}: {s['mode']}, {len(s['driven_bones'])} bones driven "
              f"{[(c['host'], c['bones'], c['depth']) for c in s['chains']]}, "
              f"{sim.get('particles')} particles / {sim.get('fixed')} pinned")
    if len(r["files"]) > 40:
        print(f"... {len(r['files']) - 40} more in the report")
    for e in r["errors"][:20]:
        print("error:", e)
    print(f"report: {os.path.join(a.out, 'sf_cloth_survey.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
