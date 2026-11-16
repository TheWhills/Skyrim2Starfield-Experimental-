"""scripts/npc/idle_marker_timers.py: IDLT / IDLF / IDLA read (synthetic)."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
import idle_marker_timers as T  # noqa: E402


class IdleMarkerTimersTest(unittest.TestCase):
    def test_marker_info(self):
        subs = [(b"IDLF", b"\x10"), (b"IDLT", struct.pack("<f", 30.0)), (b"IDLA", struct.pack("<2I", 1, 2))]
        self.assertEqual(T.marker_info(subs), {"timer_s": 30.0, "flags": 0x10, "anims": 2})


if __name__ == "__main__":
    unittest.main()
