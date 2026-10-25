"""Faster melee block for Starfield: the MeleeActions graph with shorter block transitions.

Vanilla raises the guard with a 0.3 s blend into MeleeBlock_Into, a 26-frame (0.87 s) raise; Skyrim blends into its
block pose in about a tenth of a second (owner, 2026-10-25: "the block is slow ... timed blocks would be on a delay").
This writes <out>/meshes/animtextdata/tables/graphs/meleeactions.agx from the vanilla graph with the BlockStart
transitions (into the block tree and into MeleeBlock_Into) at --raise-blend and BlockStop (to MeleeBlock_Out) at
--lower-blend; the clips themselves are made short by hkx_to_af.py --fit (MeleeBlock_Into = Skyrim's block pose).
Usage: block_pack.py --graph meleeactions.agx --out PACK [--raise-blend 0.1] [--lower-blend 0.15]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))
from fo4sf import agx  # noqa: E402

GRAPH_PATH = ("meshes", "animtextdata", "tables", "graphs", "meleeactions.agx")


def build(data: bytes, raise_blend: float = 0.1, lower_blend: float = 0.15):
    """(graph bytes, report)."""
    out, n_start = agx.set_link_blend(data, "BlockStart", raise_blend)
    out, n_stop = agx.set_link_blend(out, "BlockStop", lower_blend)
    return out, {"BlockStart": n_start, "BlockStop": n_stop, "raise_blend": raise_blend, "lower_blend": lower_blend}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--graph", required=True, help="the vanilla meleeactions.agx")
    ap.add_argument("--out", required=True, help="pack folder")
    ap.add_argument("--raise-blend", type=float, default=0.1)
    ap.add_argument("--lower-blend", type=float, default=0.15)
    a = ap.parse_args(argv)
    with open(a.graph, "rb") as fh:
        data, rep = build(fh.read(), a.raise_blend, a.lower_blend)
    if not rep["BlockStart"]:
        sys.exit("no BlockStart transition found: not the MeleeActions graph?")
    path = os.path.join(a.out, *GRAPH_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    print(rep)


if __name__ == "__main__":
    main()
