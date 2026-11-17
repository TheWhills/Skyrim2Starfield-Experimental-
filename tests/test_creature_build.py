"""scripts/npc/creature_build.py helpers on synthetic data: finding the chicken's clips, the clip plan against the
critter's descriptors, a model's material, and the bind-vs-rig check."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
import creature_build as B  # noqa: E402
from fo4sf import creature, gearfit, nif, retarget, sfnif  # noqa: E402


class BuildTests(unittest.TestCase):
    def test_plan(self):
        sky = {"meshes\\actors\\ambient\\chicken\\animations\\mt_idle.hkx",
               "meshes\\actors\\ambient\\chicken\\animations\\walkforward.hkx",
               "meshes\\actors\\ambient\\cow\\animations\\runforward.hkx"}
        sf = {"meshes/actors/critter/animations/idle.afx", "meshes/actors/critter/animations/walkforward.afx",
              "meshes/actors/critter/animations/runforward.afx"}
        plan, missing = B.plan_clips(sky, sf, [("idle", "MT_Idle"), ("walkforward", "WalkForward"),
                                               ("runforward", "RunForward"), ("warn", "AggroWarning1")])
        self.assertEqual(plan, [("meshes/actors/critter/animations/idle.afx",
                                 "meshes\\actors\\ambient\\chicken\\animations\\mt_idle.hkx"),
                                ("meshes/actors/critter/animations/walkforward.afx",
                                 "meshes\\actors\\ambient\\chicken\\animations\\walkforward.hkx")])
        self.assertEqual(missing, ["Skyrim RunForward.hkx", "Starfield meshes/actors/critter/animations/warn.afx"])

    def test_material_of(self):
        n = sfnif.build_skinned_nif(b"T", [sfnif.SkinnedShape(b"B", b"a\\b", 3, 3, "materials\\critter\\trilobite.mat",
                                                               [b"COM"], [((0, 0, 0, 1), (1, 0, 0, 0, 1, 0, 0, 0, 1),
                                                                           (0, 0, 0), 1.0)])])
        self.assertEqual(B.material_of(nif.serialize(n)), "materials\\critter\\trilobite.mat")

    def test_bind_vs_rig(self):
        U = retarget.SKYRIM_M_PER_UNIT
        sk = retarget.Rig(["NPC Root [Root]", "Pelvis", "HEAD"], [-1, 0, 1], [(0, 0, 0), (0, 0, 10), (0, 2, 3)],
                          [(0, 0, 0, 1)] * 3)
        cr = creature.creature_rig(sk, "Pelvis")
        pel, head = np.eye(4), np.eye(4)
        pel[2, 3] = 10 * U
        head[:3, 3] = (0, 2 * U, 13 * U + 0.01)                  # 1 cm off the rig
        sh = gearfit.SkyShape(b"c", np.zeros((1, 3)), np.zeros((1, 3)), [], [], ["Pelvis", "HEAD"], [[(0, 1.0)]],
                              {"Pelvis": pel, "HEAD": head})
        r = B.bind_vs_rig(sh, cr)
        self.assertEqual(r["COM"], (0.0, 0.0))
        self.assertAlmostEqual(r["HEAD"][0], 0.01, places=4)

    def test_root_motion(self):
        from fo4sf import rootmotion
        U = retarget.SKYRIM_M_PER_UNIT
        walk = {"duration": 1.0, "translations": [(1.0, 0.0, 0.496 / U, 0.0)], "rotations": [(1.0, 0, 0, 0, 1)]}
        t, q = B.root_motion(walk, 31, rootmotion)
        np.testing.assert_allclose(t[-1], (0, 0.496, 0), atol=1e-6)
        np.testing.assert_allclose(t[15], (0, 0.496 / 2, 0), atol=1e-3)      # one key at the end: steady speed
        s = np.sqrt(0.5)
        turn = {"duration": 0.833, "translations": [(0.833, 0, 0, 0)], "rotations": [(0.833, 0, 0, s, s)]}
        t, q = B.root_motion(turn, 26, rootmotion)
        self.assertAlmostEqual(rootmotion.yaw_degrees(q[-1]), 90.0, places=3)
        self.assertEqual(B.root_motion(None, 10, rootmotion), (None, None))


class MainTests(unittest.TestCase):
    def test_main_with_fake_games(self):
        import struct
        import tempfile
        from unittest import mock
        import sf_anim_survey as SAS
        from fo4sf import af_writer, bsa, skyrimhkx, skyrimskin
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        import test_creature as TC
        import test_skyrim_armor as A
        U = retarget.SKYRIM_M_PER_UNIT
        sky_files = {B.CHICKEN["skeleton"]: b"hkx", B.CHICKEN["model"]: A.skinned_nif_bytes(),
                     "meshes\\actors\\ambient\\chicken\\animations\\mt_idle.hkx": b"clip"}

        class Sky:
            def __init__(self, *_a, **_k):
                self.archives = [type("Ar", (), {"names": list(sky_files)})()]

            def _read(self, n):
                return sky_files.get(n)
        # Starfield: the critter shell (test_creature's), the trilobite model, one descriptor
        f = nif.NifFile(endian=1, user_version=12, bs_version=173, author=b"\x00", unknown_int=0,
                        export_script=b"\x00", sf_data=b"\x7a\x00")
        ident = struct.pack("<9ff", 1, 0, 0, 0, 1, 0, 0, 0, 1, 1.0)
        for name, kids in ((b"Critter_mrRigRoot", [1, 3]), (b"Root", [2]), (b"COM", []), (b"CharacterController", [])):
            f.add_block("NiNode", struct.pack("<iIiI", f.string_index(name), 0, -1, 0xE) + struct.pack("<3f", 0, 0, 0)
                        + ident + struct.pack("<iI", -1, len(kids)) + struct.pack(f"<{len(kids)}i", *kids))
        f.footer = struct.pack("<II", 1, 0)
        trilo = sfnif.build_skinned_nif(b"T", [sfnif.SkinnedShape(b"B", b"a\\b", 3, 3, "materials\\critter\\t.mat",
                                                                   [b"COM"], [((0, 0, 0, 1), (1, 0, 0, 0, 1, 0, 0, 0, 1),
                                                                               (0, 0, 0), 1.0)])])
        sf_files = {B.CRITTER["skeleton"]: nif.serialize(f), B.CRITTER["model"]: nif.serialize(trilo),
                    B.CRITTER["anims"] + "idle.afx": b"<root><is_state>1</is_state><tag>Idle</tag>"
                                                     b"<filename>Idle.af</filename></root>"}

        class Ba2:
            names = list(sf_files)

            def read(self, i):
                return sf_files[self.names[i]]
        desc = {"skeletons": [{"name": "NPC Root [Root]", "bones": ["NPC Root [Root]", "Pelvis", "HEAD"],
                               "parents": [-1, 0, 1], "reference_pose": [{"t": (0, 0, 0), "q": (0, 0, 0, 1)},
                                                                         {"t": (0, 0, 10), "q": (0, 0, 0, 1)},
                                                                         {"t": (0, 2, 3), "q": (0, 0, 0, 1)}]}]}
        pel, head = np.eye(4), np.eye(4)
        pel[2, 3] = 10 * U
        head[:3, 3] = (0, 2 * U, 13 * U)
        shape = gearfit.SkyShape(b"chicken", np.array([[0, 0, 0.1], [0.1, 0, 0.1], [0, 0.1, 0.2]]),
                                 np.array([[0, 0, 1]] * 3, float), [(0, 0), (1, 0), (0, 1)], [(0, 1, 2)],
                                 ["Pelvis", "HEAD"], [[(0, 1.0)], [(1, 1.0)], [(1, 1.0)]], {"Pelvis": pel, "HEAD": head})
        clip = {"fps": 30.0, "duration": 1 / 15, "frames": 3, "bones": ["Pelvis"],
                "tracks": [[((0, 0, 10), (0, 0, 0, 1), (1,))] * 3], "annotations": []}
        calls = []

        def fake_write(lib, out_dir, name, bones, parents, rest_t, rest_q, clip_t, clip_q, rig_path=None, **kw):
            calls.append((name, bones, rig_path, kw.get("file_name")))
            os.makedirs(out_dir, exist_ok=True)
            for ext in (".af", ".afx"):
                open(os.path.join(out_dir, kw["file_name"] + ext), "wb").write(b"x")
            rig = rig_path or os.path.join(out_dir, "skeleton.rig")
            open(rig, "wb").write(b"rig")
            return {"rig": rig, "frames": len(clip_q), "keys": 1}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(bsa, "SkyrimArchives", Sky), \
                mock.patch.object(SAS, "archives", lambda _d: [("Starfield - Animations.ba2", Ba2())]), \
                mock.patch.object(skyrimhkx, "describe", lambda _b: desc), \
                mock.patch.object(skyrimhkx, "decode_clip", lambda _b, _n=None: clip), \
                mock.patch.object(skyrimskin, "skinned_shapes", lambda _n: [type("S", (), {"tangents": []})()]), \
                mock.patch.object(gearfit, "from_skyrim", lambda _s: shape), \
                mock.patch.object(af_writer, "write", fake_write), \
                mock.patch.object(B, "gearfit_find_texconv", lambda _g: ""):
            out = os.path.join(d, "S2S Chicken Test")
            self.assertEqual(B.main(["--skyrim-data", d, "--starfield-data", d, "--calumi", "x.dll", "--out", out]), 0)
            import json
            with open(os.path.join(out, "creature_build.json")) as fh:
                rep = json.load(fh)
            for rel in (B.CRITTER["skeleton"], B.CRITTER["rig"], B.CRITTER["model"], B.CRITTER["anims"] + "Idle.af",
                        B.CRITTER["anims"] + "Idle.afx"):
                self.assertTrue(os.path.isfile(os.path.join(out, *rel.split("/"))), rel)
            self.assertFalse(os.path.isdir(os.path.join(out, "_work")))
        self.assertEqual(calls, [("Idle", ["Root", "COM", "HEAD"], None, "Idle")])
        self.assertEqual(rep["bind_vs_rig_m_deg"], {"COM": [0.0, 0.0], "HEAD": [0.0, 0.0]})
        self.assertEqual(rep["rig"]["com_rest_m"], [0.0, 0.0, round(10 * U, 4)])
        self.assertTrue(any("trilobite" in n for n in rep["notes"]))
        self.assertIn("Starfield meshes/actors/critter/animations/walkforward.afx", rep["clips_missing"])


if __name__ == "__main__":
    unittest.main()
