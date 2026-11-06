"""scripts/armor/armor_check.py: bind agreement against a skeleton, flagged bones and far vertices (synthetic)."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
from fo4sf import skyrimhair  # noqa: E402
import armor_check as C  # noqa: E402
import os_export as E  # noqa: E402

OFF = np.eye(4)
OFF[:3, 3] = (0, 0, -1.0)                     # mesh -> skeleton offset shared by every good bone


def world_at(x, y, z):
    w = np.eye(4)
    w[:3, 3] = (x, y, z)
    return w


WORLD = {"A": world_at(0, 0, 1), "B": world_at(0, 0, 2), "C": world_at(1, 0, 0), "D": world_at(0, 1, 1)}


def bind_for(w, off=OFF):
    m = np.linalg.inv(w) @ off
    return ((0.0, 0.0, 0.0, 0.5), tuple(m[:3, :3].reshape(9)), tuple(m[:3, 3]), 1.0)


def shape(name, pos, weights):
    pos = np.array(pos, float)
    n = np.tile([0.0, 0.0, 1.0], (len(pos), 1))
    uv = [(0.0, 0.0)] * len(pos)
    tri = [(0, 1, 2)]
    return skyrimhair.HairShape(name.encode(), pos, n, E.tangents(pos, n, uv, tri), uv, tri, weights, -1, -1, -1,
                                colors=[(255, 255, 255, 255)] * len(pos))


class CheckTests(unittest.TestCase):
    def test_flags_bad_and_unused_bones_and_far_vertices(self):
        bad = np.eye(4)
        bad[:3, 3] = (0, 0, -3.0)
        binds = {"A": bind_for(WORLD["A"]), "B": bind_for(WORLD["B"]), "C": bind_for(WORLD["C"]),
                 "D": bind_for(WORLD["D"], bad)}
        body = shape("Body", [[0, 0, 0], [0.5, 0, 0], [0, 0.5, 1.8]],
                     [[("A", 1.0)], [("B", 0.995), ("C", 0.005)], [("A", 0.5), ("D", 0.5)]])  # C: in the skin, moves nothing
        bf = E.body_nif_files([body], ["m.mat"], binds, "Body")
        body_mesh = next(v for k, v in bf.items() if k.endswith(".mesh"))
        gear = shape("Gear", [[0, 0, 0.1], [0.3, 0, 0.1], [0, 0, 9.0]],
                     [[("A", 1.0)], [("C", 1.0)], [("D", 1.0)]])
        af = E.body_nif_files([gear], ["m.mat"], binds, "S2S/G")
        rep = C.check(bf["meshes/Body.nif"], body_mesh, af["meshes/S2S/G.nif"],
                      {k: v for k, v in af.items() if k.endswith(".mesh")}, WORLD)
        self.assertEqual(rep["flagged_bones"], ["C", "D"])
        self.assertLess(rep["body"]["bones"]["A"]["bind_error_m"], 1e-3)
        self.assertAlmostEqual(rep["body"]["bones"]["D"]["bind_error_m"], 2.0, places=3)
        s = next(iter(rep["shapes"].values()))
        self.assertEqual(sorted(s["flagged_bones"]), ["C", "D"])
        self.assertEqual(s["outside_body_box"], 1)
        self.assertEqual(s["outside_examples"][0]["weights"], [("D", 1.0)])
        self.assertEqual(s["top"][0]["v"], 2)
        self.assertEqual(s["bone_vertices"], {"A": 1, "C": 1, "D": 1})


if __name__ == "__main__":
    unittest.main()
