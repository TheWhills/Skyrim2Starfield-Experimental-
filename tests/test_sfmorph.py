"""fo4sf.sfmorph: morph.dat round trip (synthetic)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import sfmorph  # noqa: E402


class MorphTests(unittest.TestCase):
    def test_empty_entries_carry_running_index(self):
        data = sfmorph.build(3, ["A"], {"A": {0: (0.01, 0, 0), 2: (0, 0.02, 0)}})
        m = sfmorph.parse(data)
        self.assertEqual(m.layout["empty_entries_first_running"], 1)
        self.assertEqual(m.layout["empty_entries_first_0"], 0)
        self.assertEqual(sorted(m.deltas["A"]), [0, 2])

    def test_round_trip(self):
        keys = ["Overweight", "Thin", "Strong"]
        d = {"Overweight": {0: (0.01, 0.0, 0.02), 2: (0.0, 0.005, 0.0)}, "Strong": {2: (0.003, 0.0, 0.0)}}
        data = sfmorph.build(4, keys, d)
        m = sfmorph.parse(data)
        self.assertEqual((m.version, m.num_vertices, m.keys), (3, 4, keys))
        self.assertEqual(m.layout["records"], 3)
        self.assertTrue(m.layout["records_in_vertex_order"])
        self.assertAlmostEqual(m.deltas["Overweight"][0][2], 0.02, places=3)
        self.assertEqual(sorted(m.deltas["Strong"]), [2])
        self.assertEqual(m.deltas["Thin"], {})
        s = sfmorph.summary(m)
        self.assertEqual(s["per_key"]["Overweight"]["vertices"], 2)

    def test_bad_size(self):
        with self.assertRaises(sfmorph.MorphError):
            sfmorph.parse(sfmorph.build(2, ["A"], {"A": {0: (0, 0, 0)}}) + b"x")


if __name__ == "__main__":
    unittest.main()


class ProbeTests(unittest.TestCase):
    def test_mesh_vertices(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        import morph_probe
        import os_export as E
        from test_armor_check import shape, bind_for, WORLD
        binds = {b: bind_for(WORLD[b]) for b in WORLD}
        files = E.body_nif_files([shape("A", [[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0]], [[("A", 1.0)]] * 3)], ["m.mat"],
                                 binds, "S2S/T")
        self.assertEqual(morph_probe.mesh_vertices(files["meshes/S2S/T.nif"]), [("A", 3)])


class NeutralWordsTests(unittest.TestCase):
    def test_new_records_change_nothing_but_position(self):
        """2026-11-09 (owner: race faces dark red): records without given words carry the no-change words, not zeros
        (zero normal words decode to -511 on every axis)."""
        m = sfmorph.parse(sfmorph.build(2, ["A"], {"A": {0: (0.01, 0, 0)}}))
        self.assertEqual(m.extra["A"][0], sfmorph.NEUTRAL_EXTRA)
        self.assertEqual(sfmorph.pack_normal_delta((0, 0, 0)), sfmorph.NEUTRAL_EXTRA[1])
        w = sfmorph.pack_normal_delta((1, -1, 0))
        self.assertEqual((w & 0x3FF, w >> 10 & 0x3FF, w >> 20 & 0x3FF), (1022, 0, 511))

