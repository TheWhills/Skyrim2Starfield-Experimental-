"""fo4sf.subgraph: RACE subgraph entries (synthetic subrecords in both field orders seen in shipped plugins)."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import subgraph as S  # noqa: E402

k = lambda v: struct.pack("<I", v)  # noqa: E731


class SubgraphTests(unittest.TestCase):
    def test_parse_both_orders_and_roundtrip(self):
        subs = [(b"EDID", b"HumanRace\0"), (b"SADD", k(0x347D)),
                (b"SAKD", k(0xFE00080D)), (b"SGNM", b"AnimTextData\\Tables\\Graphs\\1stPerson_Gun.agx\0"),
                (b"SAPT", b"actors\\mod\\Rank0\0"), (b"SAPT", b"actors\\human\\_1stperson\\animations\\gun\\common\0"),
                (b"STKD", k(0x1FC18)), (b"STKD", k(0x476C6)), (b"SRAF", bytes([1, 0, 1, 0])),
                (b"SAKD", k(0x251535)), (b"STKD", k(0x1FC18)), (b"SGNM", b"X.agx\0"), (b"SAPT", b"a\0"),
                (b"SRAF", bytes([1, 0, 1, 0]))]
        e = S.parse(subs)
        self.assertEqual(len(e), 2)
        self.assertEqual(e[0]["target_keywords"], [0x1FC18, 0x476C6])
        self.assertEqual(e[0]["paths"][0], "actors\\mod\\Rank0")                 # most specific first, as stored
        self.assertEqual((e[1]["actor_keywords"], e[1]["target_keywords"], e[1]["graph"]), ([0x251535], [0x1FC18], "X.agx"))
        again = S.parse(S.build(e[0]))
        self.assertEqual(again, [e[0]])
        sm = S.summary(e, {0x1FC18: "WeaponTypeRifle"})
        self.assertEqual(sm["examples"][1]["target"], ["WeaponTypeRifle"])


if __name__ == "__main__":
    unittest.main()
