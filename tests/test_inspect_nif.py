"""scripts/tools/inspect_nif.py on a synthetic Skyrim archive: per-shape shader facts and the converter's decision."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "tools"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import bsa, skyrimnif  # noqa: E402
from skyrim_fixtures import SseNif  # noqa: E402

QUAD = [(0, 0, 0), (10, 0, 0), (10, 10, 0)], [(0, 0), (1, 0), (1, 1)], [(0, 1, 2)]


def fire_nif():
    b = SseNif()
    root = b.reserve("BSFadeNode")
    logs = b.trishape(b"Logs", *QUAD, shader=b.lighting("textures\\clutter\\logs.dds", "textures\\clutter\\logs_n.dds"))
    flame = b.trishape(b"Flame", *QUAD, shader=b.effect())
    glow = b.nitrishape(b"Embers", *QUAD, shader=b.lighting("textures\\effects\\embers.dds", ""),
                        alpha=b.alpha(0x1, 0))
    b.node(root, b"FirePit", [logs, flame, glow])
    return b.bytes()


class InspectNifTests(unittest.TestCase):
    def test_shapes_and_decisions(self):
        import inspect_nif
        with tempfile.TemporaryDirectory() as tmp:
            data = os.path.join(tmp, "Data")
            os.makedirs(data)
            with open(os.path.join(data, "Skyrim - Meshes0.bsa"), "wb") as f:
                f.write(bsa.build({"meshes\\effects\\firepit.nif": fire_nif()}, version=105, compress=True))
            work = os.path.join(tmp, "work")
            os.makedirs(work)
            json.dump({"refs": [{"model": "Effects\\FirePit.nif"}, {"model": "Clutter\\Bucket.nif"}]},
                      open(os.path.join(work, "convert_input.json"), "w"))
            zp = os.path.join(tmp, "out", "inspect.zip")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                inspect_nif.main(["--skyrim-data", data, "--work", work, "--find", "fire", "--zip", zp])
            res, = json.load(open(zp + ".json"))
            by = {s["name"]: s for s in res["shapes"]}
            self.assertEqual(by["Logs"]["converter"], "opaque material from the diffuse")
            self.assertEqual(by["Logs"]["shader"]["shader_type"], "environment map")
            self.assertEqual(by["Flame"]["converter"], "SKIPPED (effect shader)")
            self.assertEqual(by["Embers"]["converter"], "decal material from the diffuse")
            self.assertEqual(by["Embers"]["shader"]["textures"], ["textures\\effects\\embers.dds"])
            self.assertTrue(by["Embers"]["alpha"]["blend"])
            self.assertIn("Embers", out.getvalue())
            self.assertNotIn("bucket", out.getvalue().lower())

    def test_refraction_and_normal_map_diffuse(self):
        from fo4sf import nif
        b = SseNif()
        haze = b.lighting("textures\\effects\\VaporTileNormal_n.dds", "x_n.dds", flags1=0x82418309)  # owner's fire
        plain = b.lighting("a.dds", "a_n.dds", flags1=0x82400301)
        n = nif.parse(b.bytes())
        self.assertTrue(skyrimnif.refraction(n, haze))
        self.assertFalse(skyrimnif.refraction(n, plain))
        self.assertTrue(skyrimnif.normal_map_as_diffuse(skyrimnif.texture_set(n, haze)))
        self.assertFalse(skyrimnif.normal_map_as_diffuse(skyrimnif.texture_set(n, plain)))
        import inspect_nif
        info = skyrimnif.shader_info(n, haze)
        self.assertEqual(inspect_nif.converter_decision(info, (False, False, 128), True, True),
                         "SKIPPED (refraction / heat haze)")

    def test_shader_info_lighting_flags(self):
        b = SseNif()
        sh = b.lighting("a.dds", "b.dds", double_sided=True)
        from fo4sf import nif
        n = nif.parse(b.bytes())
        info = skyrimnif.shader_info(n, sh)
        self.assertEqual((info["flags1"], info["flags2"]), ("80000000", "00008011"))
        self.assertEqual(skyrimnif.shader_info(n, -1), {"type": None})


if __name__ == "__main__":
    unittest.main()
