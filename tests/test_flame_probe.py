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


if __name__ == "__main__":
    unittest.main()
