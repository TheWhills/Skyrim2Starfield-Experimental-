import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts", "interior"))

import flame_probe  # noqa: E402


class FakeNif:
    def __init__(self, blocks):
        self.blocks = [b for _t, b in blocks]
        self.types = [t for t, _b in blocks]
        self.strings = []

    def type_of(self, i):
        return self.types[i]


def time_ctrl(nxt, freq=1.0, phase=0.0, start=0.0, stop=2.0, target=0):
    return struct.pack("<iHffffi", nxt, 8, freq, phase, start, stop, target)


class FlameProbeTest(unittest.TestCase):
    def test_float_controller_chain_reads_variable_and_keys(self):
        keys = struct.pack("<II", 2, 1) + struct.pack("<ff", 0.0, 0.0) + struct.pack("<ff", 2.0, 1.0)
        ctrl = time_ctrl(-1, freq=0.5, stop=2.0) + struct.pack("<iI", 1, 6)       # interpolator 1, U Offset
        interp = struct.pack("<fi", 0.25, 2)
        n = FakeNif([("BSEffectShaderPropertyFloatController", ctrl), ("NiFloatInterpolator", interp),
                     ("NiFloatData", keys)])
        c, = flame_probe.controllers(n, 0)
        self.assertEqual(c["variable"], "U Offset")
        self.assertEqual(c["frequency"], 0.5)
        self.assertEqual(c["stop"], 2.0)
        self.assertEqual(c["value"], 0.25)
        self.assertEqual(c["data"]["keys"], [(0.0, 0.0), (2.0, 1.0)])

    def test_chain_follows_next_and_stops_on_loops(self):
        a = time_ctrl(1) + struct.pack("<iI", -1, 0)
        b = time_ctrl(0) + struct.pack("<iI", -1, 5)                              # points back at a
        n = FakeNif([("BSEffectShaderPropertyFloatController", a), ("BSEffectShaderPropertyFloatController", b)])
        out = flame_probe.controllers(n, 0)
        self.assertEqual([c.get("variable") for c in out], ["Emissive Multiple", "Alpha Transparency"])

    def test_float_keys_quadratic_stride(self):
        d = struct.pack("<II", 2, 2) + struct.pack("<4f", 0, 1, 0, 0) + struct.pack("<4f", 1, 3, 0, 0)
        n = FakeNif([("NiFloatData", d)])
        self.assertEqual(flame_probe.float_keys(n, 0)["keys"], [(0.0, 1.0), (1.0, 3.0)])

    def test_particle_system_gets_shader_texture_and_emitter_fields(self):
        shader = struct.pack("<iI", -1, 0) + b"\x00" * 7 + b"textures\\effects\\candleflame01.dds\x00"
        system = struct.pack("<i", 0) + b"\x01" + struct.pack("<i", 1)      # name 0, a bool, then shader ref 1
        head = struct.pack("<iIi", -1, 0, 2) + b"\x01"                     # name, order, target system 2, active
        emitter = head + struct.pack("<14f", *range(14)) + struct.pack("<i", -1) + struct.pack("<2f", 2.5, 4.0)
        color = head + struct.pack("<18f", *[0.1 * k for k in range(18)])
        n = FakeNif([("NiNode", b"\x00" * 8), ("BSEffectShaderProperty", shader), ("NiParticleSystem", system),
                     ("NiPSysCylinderEmitter", emitter), ("BSPSysSimpleColorModifier", color)])
        n.strings = [b"Flame"]
        ps, = flame_probe.particle_systems(n)
        self.assertEqual(ps["name"], "Flame")
        self.assertEqual(ps["textures"], ["textures\\effects\\candleflame01.dds"])
        em, col = ps["modifiers"]
        self.assertEqual(em["fields"]["radius"], 10.0)
        self.assertEqual(em["fields"]["life_span"], 12.0)
        self.assertEqual(em["volume"], [2.5, 4.0])
        self.assertAlmostEqual(col["fields"]["c3a"], 1.7, places=4)

    def test_sf_nif_layout_reads_geometry_material_and_mesh_bounds(self):
        from fo4sf import nif as nifmod, sfmesh, sfnif
        scale, raw = sfmesh.encode_positions([(0, 0, 0), (0.02, 0, 0.05), (0, 0.02, 0.05)])
        m = sfmesh.SfMesh(triangles=[(0, 1, 2)], scale=scale, positions=raw,
                          uv1=[(sfmesh.float_to_half(u), sfmesh.float_to_half(v)) for u, v in ((0, 0), (1, 0), (0, 1))])
        shape = sfnif.StaticShape(b"Flame", b"0123456789abcdef0123\\0123456789abcdef0123", 6, 3,
                                  "Materials\\Effects\\Fires\\FireCandleFlame.mat", (0, 0, 0, 1), (0, 0, 0, 1, 1, 1))
        n = nifmod.parse(nifmod.serialize(sfnif.build_static_nif(b"Candle", [shape])))
        meshes = {"geometries/0123456789abcdef0123/0123456789abcdef0123.mesh": sfmesh.serialize(m)}
        rows = flame_probe.sf_nif_layout(n, meshes.get)
        geo = next(r for r in rows if r["type"] == "BSGeometry")
        self.assertEqual(geo["name"], "Flame")
        self.assertEqual(geo["verts"], 3)
        self.assertEqual(geo["pos_max"], [0.02, 0.02, 0.05])
        self.assertEqual(geo["uv"], [0.0, 1.0, 0.0, 1.0])
        shader = rows[geo["shader"]]
        self.assertEqual(shader["name"], "Materials\\Effects\\Fires\\FireCandleFlame.mat")


if __name__ == "__main__":
    unittest.main()
