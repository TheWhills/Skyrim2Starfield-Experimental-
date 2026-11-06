"""Dump the blocks of skinned NIFs side by side, to compare a converted armor with a vanilla one (2026-11-06: a rigid
bar swinging from the first shape's first bone in game; our blocks follow a one-shape community outfit, so the
vanilla multi-shape layout is the reference).

Per NIF: header (versions), every block's type and size, and in full: NiNode (children, extras), BSGeometry (flags
after the name / refs / mesh slots), SkinAttach (bone names), BSSkin::Instance (root, data, bone refs, the bytes after
them), BSSkin::BoneData (count, bytes per bone, first bone). Writes nif_dump.json and prints a summary.

    python -I scripts\\armor\\nif_dump.py --starfield "D:\\...\\Starfield" --vanilla-armor Clothes_Nightwear_01 ^
        --file "<mod>\\meshes\\S2S\\Ralof_outfit.nif" --out "<folder>"
"""
import argparse
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import nif as nifmod  # noqa: E402
from fo4sf import sfplugin  # noqa: E402
import hkx_to_af  # noqa: E402


def _name(n, i):
    return n.strings[i].decode("latin-1", "replace") if 0 <= i < len(n.strings) else None


def describe(nif_bytes: bytes) -> dict:
    n = nifmod.parse(nif_bytes)
    out = {"bs_version": getattr(n, "bs_version", None), "user_version": getattr(n, "user_version", None),
           "blocks": []}
    for i, b in enumerate(n.blocks):
        t = n.type_of(i)
        d = {"i": i, "type": t, "size": len(b)}
        try:
            if t == "SkinAttach":
                name, cnt = struct.unpack_from("<iI", b, 0)
                p, names = 8, []
                for _ in range(cnt):
                    ln, = struct.unpack_from("<I", b, p)
                    names.append(b[p + 4:p + 4 + ln].decode("latin-1", "replace"))
                    p += 4 + ln
                d.update(name=_name(n, name), bones=names, tail=b[p:].hex())
            elif t == "BSSkin::Instance":
                root, data, cnt = struct.unpack_from("<iiI", b, 0)
                refs = list(struct.unpack_from(f"<{cnt}i", b, 12))
                d.update(root=root, data=data, bone_refs=refs, tail=b[12 + 4 * cnt:].hex())
            elif t == "BSSkin::BoneData":
                cnt, = struct.unpack_from("<I", b, 0)
                per = (len(b) - 4) / cnt if cnt else 0
                d.update(count=cnt, bytes_per_bone=per,
                         first=[round(x, 5) for x in struct.unpack_from("<17f", b, 4)] if cnt else [])
            elif t in ("NiNode", "BSFadeNode", "BSLeafAnimNode"):
                d.update(name=_name(n, struct.unpack_from("<i", b, 0)[0]), hex=b[:160].hex())
            elif t == "BSGeometry":
                d.update(name=_name(n, struct.unpack_from("<i", b, 0)[0]), hex=b.hex() if len(b) <= 400 else
                         b[:400].hex())
            else:
                d["hex"] = b[:96].hex()
        except struct.error as e:
            d["error"] = str(e)
        out["blocks"].append(d)
    return out


def vanilla_armor_nif(sf_data: str, editor_id: str) -> tuple:
    """(bytes, path) of the worn male model of a vanilla ARMO's first ARMA."""
    esm = os.path.join(sf_data, "Starfield.esm")
    recs = {fid: (t, subs) for t, _h, subs, fid in sfplugin.records(esm, [b"ARMO", b"ARMA"])}
    armo = next(r for r in recs.values() if r[0] == b"ARMO" and sfplugin.edid(r[1]) == editor_id)
    addon = next(struct.unpack_from("<I", bytes(d), 0)[0] for s, d in armo[1] if s == b"MODL" and len(d) >= 4
                 and struct.unpack_from("<I", bytes(d), 0)[0] in recs)
    mod2 = next(bytes(d).split(b"\0")[0].decode("latin-1") for s, d in recs[addon][1] if s == b"MOD2")
    path = "meshes/" + mod2.replace("\\", "/")
    return hkx_to_af.vanilla_file(path, sf_data)[0], path


def skinned_shape_count(nif_bytes: bytes) -> int:
    try:
        n = nifmod.parse(nif_bytes)
    except Exception:
        return 0
    return sum(1 for i in range(len(n.blocks)) if n.type_of(i) == "BSSkin::Instance")


def find_multi(sf_data: str, min_shapes: int = 3, want: int = 2, folder: str = "meshes/clothes/",
               limit: int = 3000):
    """[(path, bytes)] of the first `want` vanilla worn NIFs under `folder` with at least `min_shapes` skinned
    shapes (first-person and face models skipped); reads at most `limit` NIFs."""
    from fo4sf import ba2
    out, seen = [], 0
    for fn in sorted(os.listdir(sf_data)):
        low = fn.lower()
        if not (low.startswith("starfield - meshes") and low.endswith(".ba2")):
            continue
        arc = ba2.Ba2(os.path.join(sf_data, fn))
        for i, name in enumerate(arc.names):
            p = name.replace("\\", "/").lower()
            if not (p.startswith(folder) and p.endswith(".nif")) or "1stperson" in p or "_1st" in p:
                continue
            seen += 1
            if seen > limit:
                return out
            data = arc.read(i)
            if skinned_shape_count(data) >= min_shapes:
                out.append((p, data))
                if len(out) >= want:
                    return out
    return out


def summary(name: str, d: dict) -> list:
    lines = [f"{name}: {len(d['blocks'])} blocks, bs_version {d['bs_version']}"]
    for b in d["blocks"]:
        extra = ""
        if b["type"] == "BSSkin::Instance":
            refs = b["bone_refs"]
            extra = f" root {b['root']} data {b['data']} bones {len(refs)} refs {refs[:4]}... tail {b['tail'] or '-'}"
        elif b["type"] == "BSSkin::BoneData":
            extra = f" count {b['count']} x {b['bytes_per_bone']} bytes"
        elif b["type"] == "SkinAttach":
            extra = f" '{b['name']}' {len(b['bones'])} bones, first {b['bones'][:2]} tail {b['tail'] or '-'}"
        elif "name" in b:
            extra = f" '{b['name']}'"
        lines.append(f"  [{b['i']}] {b['type']} ({b['size']} B){extra}")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--vanilla-armor", default="Clothes_Nightwear_01", help="EditorID of a vanilla ARMO")
    ap.add_argument("--find-multi", type=int, default=0,
                    help="also dump the first vanilla clothes NIFs with at least this many skinned shapes")
    ap.add_argument("--file", action="append", default=[], help="a NIF on disk (repeatable)")
    ap.add_argument("--out", required=True, help="folder for nif_dump.json")
    a = ap.parse_args(argv)
    sf_data = os.path.join(a.starfield, "Data")
    rep = {}
    data, path = vanilla_armor_nif(sf_data, a.vanilla_armor)
    rep[path] = describe(data)
    if a.find_multi:
        for p, d in find_multi(sf_data, a.find_multi):
            rep[p] = describe(d)
    for f in a.file:
        with open(f, "rb") as fh:
            rep[f] = describe(fh.read())
    os.makedirs(a.out, exist_ok=True)
    dst = os.path.join(a.out, "nif_dump.json")
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    for k, d in rep.items():
        print("\n".join(summary(k, d)))
    print("wrote", dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
