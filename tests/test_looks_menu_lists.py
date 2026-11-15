"""scripts/npc/looks_menu_lists.py: S2S plugins' overrides of the same Starfield form list merged into one plugin, on
synthetic plugins only."""
import contextlib
import io
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
from fo4sf import sfplugin  # noqa: E402
import looks_menu_lists as L  # noqa: E402

INFO = {"hedr_version": 0.96, "form_version": 555}
FEMALE, MALE, OTHER = 0x0003D9B0, 0x0003D9AF, 0x00024A24


def rec(typ, subs, fid):
    return (typ, typ + bytes(20), subs, fid)


def flst(edid, *ids, fid):
    return rec(b"FLST", [(b"EDID", edid.encode() + b"\0")] + [(b"LNAM", struct.pack("<I", i)) for i in ids], fid)


def write(path, recs, masters):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(sfplugin.build(recs, INFO, masters=masters))


def entries(path, fid):
    subs = next(s for t, _h, s, f in sfplugin.records(path, [b"FLST"]) if f == fid)
    return [struct.unpack("<I", d)[0] for s, d in subs if s == b"LNAM"]


class LooksMenuListsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.esm = os.path.join(d, "Starfield", "Data", "Starfield.esm")
        write(self.esm, [flst("HeadPartsChargenOptionsFemale", 0x2311, fid=FEMALE),
                         flst("HeadPartsChargenOptionsMale", 0x2312, fid=MALE),
                         flst("HeadPartsHumanRace", 0x2400, fid=OTHER)], ())
        self.mods = os.path.join(d, "mods")
        # the owner's case: KS hairs, the Skyrim hairs (keeping the KS entries), the races (vanilla + race copies)
        write(os.path.join(self.mods, "S2S Hair", "S2SHair.esm"),
              [flst("HeadPartsChargenOptionsFemale", 0x2311, 0x01000800, fid=FEMALE)], ("Starfield.esm",))
        write(os.path.join(self.mods, "S2S Skyrim Hairs", "S2SSkyrimHairs.esm"),
              [flst("HeadPartsChargenOptionsFemale", 0x2311, 0x01000800, 0x02000800, fid=FEMALE),
               flst("HeadPartsChargenOptionsMale", 0x2312, 0x02000801, fid=MALE)], ("Starfield.esm", "S2SHair.esm"))
        write(os.path.join(self.mods, "S2S Race Test", "S2SRaceTest.esm"),
              [flst("HeadPartsChargenOptionsFemale", 0x2311, 0x01000900, fid=FEMALE),
               flst("HeadPartsChargenOptionsMale", 0x2312, 0x01000901, fid=MALE),
               flst("HeadPartsHumanRace", 0x2400, 0x01000902, fid=OTHER)], ("Starfield.esm",))

    def tearDown(self):
        self.tmp.cleanup()

    def run_update(self, order=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return L.update(self.mods, self.esm, order)

    def test_hairs_and_race_copies_both_kept(self):
        rep = self.run_update()
        out = os.path.join(self.mods, L.FOLDER, L.PLUGIN)
        self.assertTrue(rep["written"])
        self.assertEqual(L.masters_of(out), ["Starfield.esm", "S2SHair.esm", "S2SRaceTest.esm", "S2SSkyrimHairs.esm"])
        # vanilla, KS (S2SHair 01), race copy (S2SRaceTest 02), Skyrim hair (S2SSkyrimHairs 03), each once
        self.assertEqual(entries(out, FEMALE), [0x2311, 0x01000800, 0x02000900, 0x03000800])
        self.assertEqual(entries(out, MALE), [0x2312, 0x02000901, 0x03000801])
        # a list only one plugin overrides is left to that plugin
        self.assertNotIn(OTHER, [f for _t, _h, _s, f in sfplugin.records(out, [b"FLST"])])

    def test_load_order_file_orders_masters_and_entries(self):
        order = os.path.join(self.tmp.name, "loadorder.txt")
        with open(order, "w") as fh:
            fh.write("Starfield.esm\nS2SHair.esm\nS2SSkyrimHairs.esm\nS2SRaceTest.esm\n")
        self.run_update(order)
        out = os.path.join(self.mods, L.FOLDER, L.PLUGIN)
        self.assertEqual(L.masters_of(out), ["Starfield.esm", "S2SHair.esm", "S2SSkyrimHairs.esm", "S2SRaceTest.esm"])
        self.assertEqual(entries(out, FEMALE), [0x2311, 0x01000800, 0x02000800, 0x03000900])

    def test_rerun_ignores_its_own_plugin(self):
        self.run_update()
        rep = self.run_update()
        self.assertNotIn(L.PLUGIN, [m for r in rep["lists"].values() for m in r["from"]])

    def test_same_name_twice_takes_the_newer(self):
        old = os.path.join(self.mods, "Backup", "S2SRaceTest.esm")
        write(old, [flst("HeadPartsChargenOptionsFemale", 0x2311, 0x01000999, fid=FEMALE)], ("Starfield.esm",))
        os.utime(old, (1, 1))
        self.run_update()
        out = os.path.join(self.mods, L.FOLDER, L.PLUGIN)
        self.assertNotIn(0x02000999, entries(out, FEMALE))
        self.assertIn(0x02000900, entries(out, FEMALE))

    def test_no_conflict_writes_nothing(self):
        os.remove(os.path.join(self.mods, "S2S Race Test", "S2SRaceTest.esm"))
        os.remove(os.path.join(self.mods, "S2S Hair", "S2SHair.esm"))
        # S2SSkyrimHairs.esm alone (its S2SHair master missing is fine for reading)
        rep = self.run_update()
        self.assertFalse(rep["written"])
        self.assertFalse(os.path.exists(os.path.join(self.mods, L.FOLDER, L.PLUGIN)))


if __name__ == "__main__":
    unittest.main()
