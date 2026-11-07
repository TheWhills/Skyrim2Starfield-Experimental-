"""scripts/armor/os_convert.py: Skyrim outfit -> worn meshes (synthetic plugin) and the Outfit Studio call sequence
(fake client)."""
import json
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
from fo4sf import sfplugin, skyrimarmor  # noqa: E402
import os_convert as C  # noqa: E402

z = sfplugin.zs
u32 = lambda v: struct.pack("<I", v)       # noqa: E731
HDR = lambda t: struct.pack("<4sIII", t, 0, 0, 0) + bytes(8)       # noqa: E731


def esm(path):
    recs = [
        (b"RACE", HDR(b"RACE"), [(b"EDID", z("NordRace"))], 0x13746),
        (b"RACE", HDR(b"RACE"), [(b"EDID", z("ImperialRace"))], 0x13744),
        (b"ARMA", HDR(b"ARMA"), [(b"EDID", z("CuirassAA")), (b"BODT", u32(1 << 2) + bytes(4) + u32(0)),
                                 (b"RNAM", u32(0x13744)), (b"DNAM", bytes([1, 1, 2, 2]) + bytes(8)),
                                 (b"MOD2", z("armor\\cuirass_0.nif")), (b"MOD3", z("armor\\cuirassf_0.nif"))], 0x900),
        (b"ARMA", HDR(b"ARMA"), [(b"EDID", z("CuirassNordAA")), (b"BODT", u32(1 << 2) + bytes(4) + u32(0)),
                                 (b"RNAM", u32(0x13746)), (b"MOD2", z("armor\\nordcuirass.nif"))], 0x901),
        (b"ARMA", HDR(b"ARMA"), [(b"EDID", z("BootsAA")), (b"BODT", u32(1 << 7) + bytes(4) + u32(0)),
                                 (b"RNAM", u32(0x13744)), (b"MOD2", z("armor\\boots.nif"))], 0x902),
        (b"ARMO", HDR(b"ARMO"), [(b"EDID", z("Cuirass")), (b"BODT", u32(1 << 2) + bytes(4) + u32(0)),
                                 (b"MODL", u32(0x900)), (b"MODL", u32(0x901))], 0x910),
        (b"ARMO", HDR(b"ARMO"), [(b"EDID", z("Boots")), (b"BODT", u32(1 << 7) + bytes(4) + u32(0)),
                                 (b"MODL", u32(0x902))], 0x911),
        (b"LVLI", HDR(b"LVLI"), [(b"EDID", z("LItemBoots")),
                                 (b"LVLO", struct.pack("<HHIHH", 1, 0, 0x911, 1, 0))], 0x920),
        (b"LVLI", HDR(b"LVLI"), [(b"EDID", z("LItemNothingFirst")),      # first entry gives no armor
                                 (b"LVLO", struct.pack("<HHIHH", 1, 0, 0x999, 1, 0)),
                                 (b"LVLO", struct.pack("<HHIHH", 1, 0, 0x910, 1, 0))], 0x921),
        (b"OTFT", HDR(b"OTFT"), [(b"EDID", z("RalofOutfit")), (b"INAM", u32(0x910) + u32(0x920))], 0x930),
        (b"OTFT", HDR(b"OTFT"), [(b"EDID", z("HadvarOutfit")), (b"INAM", u32(0x921) + u32(0x920) + u32(0x998))],
         0x931),
        (b"NPC_", HDR(b"NPC_"), [(b"EDID", z("Hadvar")), (b"ACBS", bytes(24)), (b"RNAM", u32(0x13746)),
                                 (b"DOFT", u32(0x931))], 0x2BF9E),
        (b"NPC_", HDR(b"NPC_"), [(b"EDID", z("Ralof")), (b"ACBS", bytes(24)), (b"RNAM", u32(0x13746)),
                                 (b"DOFT", u32(0x930))], 0x2BF9D),
    ]
    with open(path, "wb") as fh:
        fh.write(sfplugin.build(recs, {"hedr_version": 1.7, "form_version": 44}))


class SkyrimSideTests(unittest.TestCase):
    def test_outfit_to_meshes(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "Skyrim.esm")
            esm(p)
            o = C.outfit_armor(p, "ralof")
            self.assertEqual((o["race"], o["armor"], o["npc"]["female"]), ("NordRace", [0x910, 0x911], False))
            m = C.worn_meshes(skyrimarmor.read_armor(p), o["armor"], o["race"], False)
            self.assertEqual([x["mesh"] for x in m], ["meshes\\armor\\nordcuirass.nif", "meshes\\armor\\boots.nif"])
            m = C.worn_meshes(skyrimarmor.read_armor(p), o["armor"], "ImperialRace", True)
            self.assertEqual(m[0]["mesh"], "meshes\\armor\\cuirassf_1.nif")          # weight slider: the _1 file
            with self.assertRaises(SystemExit):
                C.outfit_armor(p, "Nobody")
            with self.assertRaises(SystemExit) as cm:
                C.outfit_armor(p, "Hadv")
            self.assertIn("EditorIDs containing it: Hadvar", str(cm.exception))
            h = C.outfit_armor(p, "Hadvar")
            self.assertEqual(h["armor"], [0x910, 0x911])                  # past the list's empty first entry
            self.assertEqual(h["skipped"], ["00000998 (not an armor or leveled list)"])     # reported


class Fake:
    """Outfit Studio's answers as JSON text; list_shapes follows the imports."""

    def __init__(self, fail=None, far=False):
        self.calls, self.shapes, self.fail, self.far = [], [], fail, far
        self.bounds = {"Naked_M:0": ([-28, -11, -113], [28, 8, -6])}

    def call(self, name, args):
        self.calls.append((name, args))
        if name == self.fail:
            return {"isError": True, "content": [{"type": "text", "text": "nope"}]}
        body = {}
        if name == "load_from_archive":
            self.shapes.append("Naked_M:0")
            body = {"loaded": [{"shapes": ["Naked_M:0"]}]}
        elif name == "import_from_game":
            n = "SkyBody" if "body" in args["file"] else os.path.basename(args["file"])
            self.shapes.append(n)
            self.bounds[n] = ([-20, -10, 0], [20, 10, 117])
        elif name == "scale_to_body" and not self.far:      # feet onto the body's (raw space)
            for n in args["shapes"]:
                self.bounds[n] = ([-25, -12, -113], [25, 12, 30])
        elif name == "list_shapes":
            body = {"shapes": [{"name": n, "bounds": {"min": self.bounds[n][0], "max": self.bounds[n][1]}}
                               for n in self.shapes]}
        elif name == "delete_shapes":
            self.shapes = [n for n in self.shapes if n not in args["shapes"]]
        elif name == "validate_project":
            self.validates = getattr(self, "validates", 0) + 1
            body = {"ok": True, "errors": [{"check": "unweighted", "count": 51, "shape": "boots.nif"}]
                    if self.validates == 1 else []}
        elif name == "build_outfits":
            body = {"files": ["meshes/S2S/x.nif"]}
        return {"content": [{"type": "text", "text": json.dumps(body)}]}


class StudioSideTests(unittest.TestCase):
    def test_sequence(self):
        f = Fake()
        with tempfile.TemporaryDirectory() as d:
            rep = C.convert(f, "c:/w/malebody_1.nif", ["c:/w/cuirass.nif", "c:/w/boots.nif"], False, d, "Ralof")
            names = [c[0] for c in f.calls]
        self.assertNotIn("failed_at", rep)
        self.assertEqual(rep["gear"], ["cuirass.nif", "boots.nif"])
        self.assertEqual(rep["old_body"], ["SkyBody"])
        order = ["new_project", "load_from_archive", "set_reference_shape", "import_from_game", "scale_to_body",
                 "fit_pose_to_shapes", "unpose_shapes", "fit_to_body", "delete_shapes", "copy_bone_weights",
                 "validate_project", "render_view", "export_file", "save_project", "build_outfits"]
        pos = [names.index(n) for n in order]
        self.assertEqual(pos, sorted(pos))
        args = dict((n, a) for n, a in f.calls)
        self.assertEqual(args["load_from_archive"]["files"], [C.SF_BODY[False]])
        self.assertEqual(args["fit_to_body"]["gapFrom"], ["SkyBody"])
        copies = [a for n, a in f.calls if n == "copy_bone_weights"]
        self.assertEqual(copies[0], {"shapes": ["cuirass.nif", "boots.nif"], "copySkinTransform": True,
                                     "transformGeometry": False})
        self.assertEqual((copies[1]["shapes"], copies[1]["proximityRadius"]), (["boots.nif"], 25))   # the loose ones
        self.assertEqual(names.count("validate_project"), 2)
        self.assertEqual(args["save_project"]["copyReference"], False)
        self.assertEqual(args["build_outfits"]["outfits"], ["S2S Ralof"])
        self.assertEqual(rep["built"], {"files": ["meshes/S2S/x.nif"]})
        self.assertNotIn("shape_transforms", names)
        self.assertEqual(args["export_file"]["shapes"], ["cuirass.nif", "boots.nif"])
        self.assertTrue(args["export_file"]["path"].endswith("Ralof.nif"))

    def test_misaligned_figure_stops_before_fitting(self):
        f = Fake(far=True)                             # the scaled Skyrim figure is not where the body is
        with tempfile.TemporaryDirectory() as d:
            rep = C.convert(f, "body.nif", ["g.nif"], False, d, "X")
        self.assertIn("does not overlap", rep["failed_at"])
        self.assertNotIn("fit_pose_to_shapes", [c[0] for c in f.calls])

    def test_helpers(self):
        self.assertTrue(C.overlaps(([0, 0, 0], [0, 0, 117]), ([0, 0, 0], [0, 0, 106])))
        self.assertFalse(C.overlaps(([0, 0, -140], [0, 0, -20]), ([0, 0, 0], [0, 0, 106])))
        self.assertEqual(C.union([None, ([0, 0, 0], [1, 1, 1]), ([-1, 2, 0], [0, 3, 5])]), ([-1, 0, 0], [1, 3, 5]))

    def test_stops_at_first_error(self):
        f = Fake(fail="fit_pose_to_shapes")
        with tempfile.TemporaryDirectory() as d:
            rep = C.convert(f, "body.nif", ["g.nif"], True, d, "X")
            self.assertTrue(os.path.isdir(os.path.join(d, "calls")))
        self.assertEqual(rep["failed_at"], "fit_pose_to_shapes")
        self.assertNotIn("unpose_shapes", [c[0] for c in f.calls])
        self.assertEqual(dict(f.calls)["load_from_archive"]["files"], [C.SF_BODY[True]])


if __name__ == "__main__":
    unittest.main()
