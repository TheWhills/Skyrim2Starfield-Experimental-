"""The shapes of Starfield head-part NIFs, side by side (2026-11-11: the Orc player shows the human teeth and no Orc
mouth, though every record names our mouth and NPCs draw it; the player is drawn from the _facebones twins - do
Starfield's own facebones head / teeth NIFs hold the teeth, and how do ours differ?). Read-only.

    python -I scripts\\npc\\nif_parts.py --starfield "<Starfield>" ^
        meshes\\actors\\human\\characterassets\\male\\teeth.nif ^
        meshes\\actors\\human\\characterassets\\male\\teeth_facebones.nif ^
        "<mod>\\meshes\\s2s\\races\\orc\\mouth_m_facebones.nif"

Each argument: a file on disk, or a Data-relative path read from the game's archives. Per NIF: every node and
BSGeometry (name, flags, transform, per LOD vertex count and mesh path, material, skin bone count and first bones).
"""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "scripts", "armor"))

from fo4sf import headbake, nif as nifmod, sfnif  # noqa: E402


def _name(n, k):
    return n.strings[k].decode("latin-1") if 0 <= k < len(n.strings) else ""


def parts(nif_bytes):
    """Lines describing a NIF's nodes and geometries."""
    n = nifmod.parse(nif_bytes)
    out = []
    for i, b in enumerate(n.blocks):
        t = n.type_of(i)
        if t == "BSGeometry":
            g = sfnif.parse_bsgeometry(b)
            mat = ""
            if 0 <= g.shader < len(n.blocks):
                mat = _name(n, struct.unpack_from("<i", n.blocks[g.shader], 0)[0])
            lods = [(m.num_verts, m.path.decode("latin-1")) for m in g.meshes if m is not None]
            sk = headbake.geometry_skin(n, g)
            bones = [x.decode("latin-1") if isinstance(x, bytes) else str(x) for x in sk.get("bones", [])]
            t_ = tuple(round(v, 4) for v in g.translation)
            out.append(f"[{i}] BSGeometry '{_name(n, g.name_idx)}' flags {g.flags:#x} t {t_} scale {g.scale:.4g} "
                       f"material '{mat}'")
            out.append(f"      LODs {[v for v, _p in lods]} first mesh {lods[0][1] if lods else '-'}")
            out.append(f"      skin {len(bones)} bones {bones[:8]}{' ...' if len(bones) > 8 else ''}")
        elif t in ("NiNode", "BSFadeNode", "BSLeafAnimNode"):
            out.append(f"[{i}] {t} '{_name(n, struct.unpack_from('<i', b, 0)[0])}'")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True, help="the game folder (with Data)")
    ap.add_argument("nifs", nargs="+")
    a = ap.parse_args(argv)
    import hkx_to_af
    data = os.path.join(a.starfield, "Data")
    for p in a.nifs:
        try:
            if os.path.isfile(p):
                with open(p, "rb") as fh:
                    raw = fh.read()
            else:
                raw = hkx_to_af.vanilla_file(p.replace("\\", "/"), data)[0]
        except SystemExit as e:
            print(f"{p}: {e}")
            continue
        print(f"{p} ({len(raw)} bytes)")
        for line in parts(raw):
            print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
