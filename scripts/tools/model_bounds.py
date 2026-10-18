"""Print a vanilla Starfield model's real extent (read-only): finds meshes\\<model> in the game's archives, every node
and BSGeometry transform in it, and each geometry's vertex bounds from its .mesh (also read from the archives), in
the model's own frame (transforms applied). For placing vanilla objects exactly, e.g. the placeable water
Water\\Water50m.nif that make_skyrim_objects.py lod --river-water scales to each 100 m river cell (owner's view
2026-10-18: the water lay beside the rivers, so its size / origin is not the assumed 50 m centred square).

    python -I scripts\\tools\\model_bounds.py --sf-data "<Starfield>\\Data" --model Water\\Water50m.nif
"""
import argparse
import glob
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import ba2, nif as nifmod, sfmesh, sfnif  # noqa: E402


class Archives:
    def __init__(self, data):
        self.arcs = []
        for p in sorted(glob.glob(os.path.join(data, "*.ba2"))):
            try:
                self.arcs.append(ba2.Ba2(p))
            except Exception:                            # noqa: BLE001 (texture archives etc.)
                pass

    def read(self, name):
        for a in self.arcs:
            if a.find(name) is not None:
                return a.read(name)
        raise FileNotFoundError(name)


def rot(m9):
    return np.asarray(m9, np.float64).reshape(3, 3)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sf-data", required=True)
    ap.add_argument("--model", required=True, help="path under meshes\\, e.g. Water\\Water50m.nif")
    a = ap.parse_args(argv)
    arcs = Archives(a.sf_data)
    n = nifmod.parse(arcs.read("meshes\\" + a.model.replace("/", "\\")))
    print(f"{a.model}: {len(n.blocks)} blocks: {[n.type_of(i) for i in range(len(n.blocks))]}")
    allpts = []
    for i in range(len(n.blocks)):
        t = n.type_of(i)
        if t in ("NiNode", "BSFadeNode", "BSLeafAnimNode", "BSMultiBoundNode"):
            b = n.blocks[i]
            # NiNode: name, extra refs, controller, flags, translation, rotation, scale (as BSGeometry's header)
            _name, ne = struct.unpack_from("<iI", b, 0)
            p = 8 + 4 * ne + 8
            tr = struct.unpack_from("<3f", b, p)
            sc = struct.unpack_from("<f", b, p + 48)[0]
            print(f"  [{i}] {t}: translation {tuple(round(v, 3) for v in tr)}, scale {sc:g}")
        if t != "BSGeometry":
            continue
        g = sfnif.parse_bsgeometry(n.blocks[i])
        R, T = rot(g.rotation), np.asarray(g.translation)
        print(f"  [{i}] BSGeometry: translation {tuple(round(v, 3) for v in g.translation)}, scale {g.scale:g}, "
              f"rotation {[round(v, 3) for v in g.rotation]}, box {tuple(round(v, 3) for v in g.box)}")
        ref = next((m for m in g.meshes if m), None)
        if ref is None:
            continue
        m = sfmesh.parse(arcs.read("geometries\\" + ref.path.decode("latin-1") + ".mesh"))
        pos = np.asarray(m.positions, np.float64) / 32767.0 * m.scale
        lo, hi = pos.min(0), pos.max(0)
        world = (pos * g.scale) @ R.T + T
        allpts.append(world)
        print(f"      mesh {ref.path.decode()}: {len(pos)} vertices, {len(m.triangles)} triangles; "
              f"local min {tuple(round(v, 3) for v in lo)} max {tuple(round(v, 3) for v in hi)}")
    if allpts:
        p = np.concatenate(allpts)
        lo, hi = p.min(0), p.max(0)
        print(f"model extent (geometry transforms applied): min {tuple(round(v, 3) for v in lo)} "
              f"max {tuple(round(v, 3) for v in hi)}; size {tuple(round(v, 3) for v in hi - lo)}; "
              f"centre {tuple(round(v, 3) for v in (hi + lo) / 2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
