"""scripts/terrain/vanilla_btd_survey.py (2026-11-22): reads a BTD's quad map and sampled cells and reports byte
positions across neighbours and how often a position that differs from the neighbour's is drawn near an edge."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))

from fo4sf import btd  # noqa: E402
import vanilla_btd_survey as V  # noqa: E402


def synthetic(avoid_edges):
    """2 x 1 cells (4 x 2 quadrants): textures 1, 2 everywhere at bytes 0 / base 1 ... and texture 3 at byte 0 in the
    east quadrants instead of 1. Samples draw byte 0 in a checker; with avoid_edges, not within 4 of the east-west
    edge where byte 0 differs."""
    q = np.zeros((2, 4, 8), np.uint8)
    q[:, :, 0] = 1
    q[:, 2:, 0] = 3
    q[:, :, 1] = 2
    w = np.zeros((256, 256), np.uint16)
    rr, cc = np.mgrid[0:256, 0:256]
    on = ((rr // 8 + cc // 8) % 2 == 0)
    if avoid_edges:
        on &= ~((cc >= 128 - 4) & (cc < 128 + 4))
    w[on] = 7
    t = btd.Btd(6, 0.0, 10.0, [0x100, 0x200, 0x300], np.zeros((128, 256), np.uint16), w[:128], q)
    return btd.write(t)


class SurveyTest(unittest.TestCase):
    def test_quads_and_edges(self):
        sv = V.Survey()
        ltex, quad, (ncy, ncx), read_cell = V.parse(synthetic(True))
        self.assertEqual((ncy, ncx, len(ltex)), (1, 2, 3))
        sv.quads("x", quad)
        for cy in range(ncy):
            for cx in range(ncx):
                sv.cell(quad, cy, cx, read_cell(cy, cx))
        rep = "\n".join(sv.report())
        self.assertIn("quadrants read: 8", rep)
        self.assertIn("used bytes contiguous from byte 0: 100.0%", rep)
        c = sv.c
        self.assertEqual(c["side_ew_across_cells_positions_equal"], 2)     # byte 1 equal, byte 0 not, 2 rows
        d = sv.edge["diff"]
        self.assertEqual(int(d[0:4, 0].sum()), 0)                        # never drawn near the edge where it differs
        self.assertGreater(int(d[8:16, 0].sum()), 0)                     # but drawn further in
        sv2 = V.Survey()
        ltex, quad, _n, read_cell = V.parse(synthetic(False))
        for cx in range(2):
            sv2.cell(quad, 0, cx, read_cell(0, cx))
        self.assertGreater(int(sv2.edge["diff"][0:4, 0].sum()), 0)       # without the rule: drawn there too


if __name__ == "__main__":
    unittest.main()
