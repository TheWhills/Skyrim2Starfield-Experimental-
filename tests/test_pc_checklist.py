"""scripts/armor/skyrim_anim_extract.py and weapon_anim_survey.maam_users on synthetic data (no game files)."""
import json
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
from fo4sf import bsa  # noqa: E402
import sf_animcache_survey as C  # noqa: E402
import skyrim_anim_extract as X  # noqa: E402
import weapon_anim_survey as W  # noqa: E402


class ExtractTests(unittest.TestCase):
    def test_picks_vanilla_stance_files_in_load_order(self):
        base = {
            r"meshes\animationdatasinglefile.txt": b"old",
            r"meshes\actors\character\animations\2hm_idle.hkx": b"2h",
            r"meshes\actors\character\animations\dw1hm1hmblockidle.hkx": b"dw",
            r"meshes\actors\character\animations\mt_walkforward.hkx": b"mt",       # not wanted
            r"meshes\actors\character\behaviors\2hm_behavior.hkx": b"beh",
            r"meshes\actors\character\animations\sub\2hm_x.hkx": b"deep",           # not directly in animations
            r"textures\x.dds": b"t",
        }
        with tempfile.TemporaryDirectory() as d:
            data = os.path.join(d, "Data")
            os.makedirs(data)
            with open(os.path.join(data, "Skyrim - Animations.bsa"), "wb") as fh:
                fh.write(bsa.build(base))
            with open(os.path.join(data, "Update.bsa"), "wb") as fh:          # later archive overrides
                fh.write(bsa.build({r"meshes\animationdatasinglefile.txt": b"new"}))
            loose = os.path.join(data, "meshes", "actors", "character", "animations")
            os.makedirs(loose)
            with open(os.path.join(loose, "2hm_idle.hkx"), "wb") as fh:       # a mod's loose file: ignored
                fh.write(b"MOD")
            out = os.path.join(d, "out")
            os.makedirs(out)
            m = X.extract(data, out)
            paths = {e["path"]: e for e in m}
            self.assertEqual(sorted(paths), sorted([r"meshes\animationdatasinglefile.txt",
                                                    r"meshes\actors\character\animations\2hm_idle.hkx",
                                                    r"meshes\actors\character\animations\dw1hm1hmblockidle.hkx",
                                                    r"meshes\actors\character\behaviors\2hm_behavior.hkx"]))
            with open(os.path.join(out, "meshes", "animationdatasinglefile.txt"), "rb") as fh:
                self.assertEqual(fh.read(), b"new")
            self.assertEqual(paths[r"meshes\animationdatasinglefile.txt"]["source"], "Update.bsa")
            with open(os.path.join(out, "meshes", "actors", "character", "animations", "2hm_idle.hkx"), "rb") as fh:
                self.assertEqual(fh.read(), b"2h")                             # vanilla, not the loose mod file
            self.assertTrue(json.load(open(os.path.join(out, "manifest.json"))))
            m2 = X.extract(data, out, loose=True)
            self.assertEqual({e["path"]: e["source"] for e in m2}[r"meshes\actors\character\animations\2hm_idle.hkx"],
                             "loose")


class MaamUserTests(unittest.TestCase):
    def test_finds_weapon_fields_pointing_at_aim_assist_models(self):
        recs = {1: [(b"EDID", b"Sword\0"), (b"DNAM", struct.pack("<IfI", 7, 1.5, 0x00AA0001))],
                2: [(b"EDID", b"Gun\0"), (b"KWDA", struct.pack("<2I", 5, 6))],
                3: [(b"EDID", b"Knife\0"), (b"DNAM", struct.pack("<IfI", 7, 1.0, 0x00AA0001))]}
        orig = W.fields
        W.fields = lambda p, off: recs[off]
        try:
            u = W.maam_users(None, [(10, "Sword", 1), (11, "Gun", 2), (12, "Knife", 3)], {0x00AA0001})
        finally:
            W.fields = orig
        self.assertEqual(dict(u["fields"]), {"DNAM@8": 2})
        self.assertEqual(u["by_model"][0x00AA0001], ["Sword", "Knife"])
        self.assertEqual(dict(W.maam_users(None, [], set())["fields"]), {})


class AnimCacheTests(unittest.TestCase):
    def test_melee_sets_are_reported_and_copied(self):
        fd = ("3\n1\n1234567890\n3\nAnimTextData\\Tables\\Graphs\\Player_Melee.agx\n"
              "Meshes\\Actors\\Human\\Animations\\Melee\\OneHanded\\Player\\Sword\\MeleeAttack_A.af\n"
              "Meshes\\Actors\\Human\\Animations\\Melee\\OneHanded\\MeleeBlock_Idle.af\n")
        files = {
            r"meshes\animtextdata\animationfiledata\1234567890.txt": fd.encode(),
            r"meshes\animtextdata\animationoffsets\1234567890.txt": b"V5\n...",
            r"meshes\animtextdata\animationfiledata\5555555555.txt": b"3\n1\n5555555555\n1\nGun\\x.af\n",
            r"meshes\animtextdata\animationoffsets\persistantsubgraphinfoandoffsetdata.txt": b"list",
            r"meshes\other.nif": b"x",
        }
        entries = [("Starfield - Animations.ba2", n, (lambda d=d: d)) for n, d in files.items()]
        with tempfile.TemporaryDirectory() as out:
            rep = C.survey(entries, out)
            self.assertEqual(rep["families"], {"animationfiledata": 2, "animationoffsets": 2})
            self.assertEqual(len(rep["melee_sets"]), 1)
            s = rep["melee_sets"][0]
            self.assertEqual((s["set"], s["paths"]), ("1234567890", 3))
            self.assertEqual(s["ours_listed"], ["meleeattack_a", "meleeblock_idle"])
            self.assertEqual(s["graphs"], ["AnimTextData\\Tables\\Graphs\\Player_Melee.agx"])
            self.assertEqual(sorted(rep["copied"]), sorted([
                r"meshes\animtextdata\animationfiledata\1234567890.txt",
                r"meshes\animtextdata\animationoffsets\1234567890.txt",
                r"meshes\animtextdata\animationoffsets\persistantsubgraphinfoandoffsetdata.txt"]))
            self.assertTrue(os.path.isfile(os.path.join(out, "samples", "meshes", "animtextdata",
                                                        "animationoffsets", "1234567890.txt")))


if __name__ == "__main__":
    unittest.main()
