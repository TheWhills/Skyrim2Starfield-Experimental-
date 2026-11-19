"""Skyrim with mods over it (src/fo4sf/skyrimload.py; 2026-11-19, children from Realistic RS Children over RS Children
Overhaul). Synthetic plugins, BSAs and loose files only."""
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fo4sf import bsa, sfplugin, skyrimload as SL, skyrimnpc  # noqa: E402

INFO = {"hedr_version": 1.71, "form_version": 44}
HDR = bytes(24)


def u32(v):
    return struct.pack("<I", v)


def npc(edid, race, parts=(), female=False):
    acbs = struct.pack("<I", 1 if female else 0) + bytes(20)
    return [(b"EDID", sfplugin.zs(edid)), (b"ACBS", acbs), (b"RNAM", u32(race))] + [(b"PNAM", u32(p)) for p in parts]


def hdpt(edid, model, typ, extra=()):
    return ([(b"EDID", sfplugin.zs(edid)), (b"MODL", sfplugin.zs(model)), (b"PNAM", u32(typ))]
            + [(b"HNAM", u32(e)) for e in extra])


def race(edid, male_parts, female_parts):
    return ([(b"EDID", sfplugin.zs(edid)), (b"NAM0", b""), (b"MNAM", b"")] + [(b"HEAD", u32(p)) for p in male_parts]
            + [(b"FNAM", b"")] + [(b"HEAD", u32(p)) for p in female_parts])


class Fixture:
    """Data/Skyrim.esm (+ HearthFires.esm), mods/A (A.esm: overrides a Skyrim NPC, adds a head part; A.bsa; loose),
    mods/B (B.esp, masters Skyrim + USSEP (absent) + A: overrides the same NPC again, a new NPC)."""

    def __init__(self, d):
        self.data = os.path.join(d, "Data")
        self.a = os.path.join(d, "mods", "A")
        self.b = os.path.join(d, "mods", "B")
        for p in (self.data, self.a, self.b):
            os.makedirs(p)
        sky = [(b"RACE", HDR, race("NordRaceChild", [0x1C22E], [0x1C558]), 0x02C65B),
               (b"NPC_", HDR, npc("Dorthe", 0x02C65B, [0x1C559], True), 0x013477),
               (b"HDPT", HDR, hdpt("FemaleHeadChild", "Actors\\Character\\ChildHead.nif", 1), 0x01C559)]
        self.write(self.data, "Skyrim.esm", sky, ())
        self.write(self.data, "HearthFires.esm", [], ("Skyrim.esm",))
        a_recs = [(b"HDPT", HDR, hdpt("RSHead", "ranaline\\childhead.nif", 1), 0x01000800),
                  (b"RACE", HDR, race("NordRaceChild", [0x01000800], [0x01000800]), 0x02C65B),
                  (b"NPC_", HDR, npc("Dorthe", 0x02C65B, [0x01000800], True), 0x013477)]
        self.write(self.a, "A.esm", a_recs, ("Skyrim.esm",))
        # in B, 0x01 = USSEP (absent), 0x02 = A, 0x03 = B itself
        b_recs = [(b"HDPT", HDR, hdpt("Mellow", "KS\\Mellow.nif", 3, extra=[0x01000999]), 0x03000800),
                  (b"NPC_", HDR, npc("Dorthe", 0x02C65B, [0x02000800, 0x03000800], True), 0x013477),
                  (b"NPC_", HDR, npc("NewKid", 0x02C65B, [0x02000900]), 0x03000801)]
        self.write(self.b, "B.esp", b_recs, ("Skyrim.esm", "Unofficial Skyrim Special Edition Patch.esp", "A.esm"))
        with open(os.path.join(self.data, "Skyrim - Meshes0.bsa"), "wb") as fh:
            fh.write(bsa.build({"meshes\\actors\\character\\childhead.nif": b"vanilla",
                                "meshes\\shared.nif": b"vanilla shared"}))
        with open(os.path.join(self.a, "A.bsa"), "wb") as fh:
            fh.write(bsa.build({"meshes\\ranaline\\childhead.nif": b"rs head", "meshes\\shared.nif": b"A shared"}))
        loose = os.path.join(self.b, "Meshes", "Actors", "Character", "FaceGenData", "FaceGeom", "Skyrim.esm")
        os.makedirs(loose)
        with open(os.path.join(loose, "00013477.NIF"), "wb") as fh:
            fh.write(b"facegen from B")

    @staticmethod
    def write(folder, name, recs, masters):
        with open(os.path.join(folder, name), "wb") as fh:
            fh.write(sfplugin.build(recs, INFO, masters=masters))


class LoadOrderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = Fixture(self.tmp.name)
        self.lo = SL.LoadOrder(self.f.data, [self.f.a, self.f.b])

    def tearDown(self):
        self.tmp.cleanup()

    def test_order(self):
        self.assertEqual(self.lo.loaded(), ["Skyrim.esm", "A.esm", "B.esp"])
        self.assertEqual(self.lo.missing, ["Unofficial Skyrim Special Edition Patch.esp"])
        self.assertEqual(self.lo.order[3], "Unofficial Skyrim Special Edition Patch.esp")

    def test_last_plugin_wins_and_formids_are_remapped(self):
        recs = self.lo.records([b"NPC_", b"HDPT", b"RACE"])
        typ, _h, subs, plugin = recs[0x013477]
        self.assertEqual(plugin, "B.esp")
        n = SL.remap_npc(skyrimnpc.parse_npc(subs, 0x013477), self.lo.remap(plugin))
        self.assertEqual(n["head_parts"], [0x01000800, 0x02000800])      # A's part (B's master 2), B's own part
        self.assertEqual(n["race"], 0x02C65B)
        self.assertIn(0x02000801, recs)                                    # B's new NPC: B is index 2
        self.assertEqual(self.lo.origin(0x013477), ("Skyrim.esm", 0x013477))
        self.assertEqual(self.lo.origin(0x02000801), ("B.esp", 0x000801))
        # a FormID of the absent USSEP master stays distinct
        hp = SL.remap_head_part(skyrimnpc.parse_head_part(recs[0x02000800][2], 0x02000800), self.lo.remap("B.esp"))
        self.assertEqual(hp["extra_parts"], [0x03000999])

    def test_flat_records_rewrite_fields(self):
        flat = {fid: subs for _t, _h, subs, fid in SL.records(self.lo, [b"NPC_", b"RACE"])}
        pn = [struct.unpack("<I", d)[0] for s, d in flat[0x013477] if s == b"PNAM"]
        self.assertEqual(pn, [0x01000800, 0x02000800])
        self.assertEqual(SL.race_head_parts(flat[0x02C65B]), {False: [0x01000800], True: [0x01000800]})
        plain = SL.records(os.path.join(self.f.data, "Skyrim.esm"), [b"NPC_"])     # a path: as sfplugin.records
        self.assertEqual([r[3] for r in plain], [0x013477])

    def test_assets(self):
        ar = self.lo.archives
        self.assertEqual(ar.mesh("ranaline\\childhead.nif"), b"rs head")
        self.assertEqual(ar.mesh("shared.nif"), b"A shared")                       # mod BSA over Skyrim's
        self.assertEqual(ar.mesh("actors\\character\\childhead.nif"), b"vanilla")
        fg = self.lo.facegen_paths(0x013477)["mesh"]
        self.assertEqual(ar.mesh(fg), b"facegen from B")                           # loose, case-insensitive
        self.assertEqual(ar.source_of(fg), "B")
        self.assertEqual(ar.source_of("meshes\\shared.nif"), "A.bsa")

    def test_no_mods_is_skyrim_esm(self):
        lo = SL.LoadOrder(self.f.data)
        self.assertEqual(lo.loaded(), ["Skyrim.esm"])
        self.assertIsInstance(lo.archives, bsa.SkyrimArchives)
        recs = lo.records([b"NPC_"])
        self.assertEqual(SL.remap_npc(skyrimnpc.parse_npc(recs[0x013477][2], 0x013477), lo.remap("Skyrim.esm"))
                         ["head_parts"], [0x01C559])


if __name__ == "__main__":
    unittest.main()
