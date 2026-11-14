import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import apply_ref_overrides as A  # noqa: E402
from test_ref_overrides import plugin  # noqa: E402


def refs_of(path):
    """{raw FormID: (flags, z)} of the plugin's REFRs."""
    with open(path, "rb") as fh:
        buf = fh.read()
    out = {}
    from fo4sf import fo4land
    with fo4land.Plugin(path) as p:
        for typ, off, flags, fid, _c in A.ref_overrides.walk(p, p.body, len(p.buf)):
            if typ == b"REFR":
                d = A.field_offset(buf, off, b"DATA")
                out[fid] = (flags, round(struct.unpack_from("<f", buf, d + 8)[0], 2))
    return out


class ApplyRefOverridesTests(unittest.TestCase):
    def test_hidden_statics_written_into_the_exterior(self):
        """FO4Port hides 00502E (disabled, sunk) and moves 000777 without disabling it: only 00502E changes in the
        exterior plugin, in place (same size); a second run changes nothing; a backup of the original is kept."""
        with tempfile.TemporaryDirectory() as d:
            terr = os.path.join(d, "Terrain.esm")
            port = os.path.join(d, "Port.esm")
            plugin(terr, ["Starfield.esm"], [(0x0100502E, 0, 384.88, None), (0x01000777, 0, 10.0, None),
                                             (0x0000502E, 0, 1.0, None)])          # Starfield.esm's 00502E: not ours
            plugin(port, ["Starfield.esm", "Terrain.esm"],
                   [(0x0100502E, A.DISABLED, -615.12, 0x00000014), (0x01000777, 0, 99.0, None),
                    (0x0100AAAA, A.DISABLED, 0.0, None)])                            # not in the exterior
            size = os.path.getsize(terr)
            hidden = A.hidden_in(port, "Terrain.esm")
            self.assertEqual(sorted(hidden), [0x00502E, 0x00AAAA])
            self.assertEqual(A.patch(terr, hidden), (1, 0, 1, 0))
            self.assertEqual(os.path.getsize(terr), size)
            got = refs_of(terr)
            self.assertEqual(got[0x0100502E][1], -615.12)
            self.assertTrue(got[0x0100502E][0] & A.DISABLED)
            self.assertEqual(got[0x01000777], (0, 10.0))
            self.assertEqual(A.patch(terr, hidden), (0, 1, 1, 0))
            self.assertEqual(refs_of(terr + A.BACKUP)[0x0100502E], (0, 384.88))
            self.assertEqual(got[0x0000502E], (0, 1.0))                              # Starfield.esm's: untouched


if __name__ == "__main__":
    unittest.main()
