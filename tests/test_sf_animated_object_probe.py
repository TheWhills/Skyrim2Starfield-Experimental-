"""scripts/interior/sf_animated_object_probe.py on synthetic records: graph / rig / folder found in any subrecord,
grouped by graph, loopy names listed with their folder's clips."""
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import sf_animated_object_probe as P  # noqa: E402

FAN = [(b"EDID", b"ShipFan01\0"), (b"MODL", b"Ships\\Fan01.nif\0"),
       (b"BFCB", b"AnimationGraphComponent\0"),
       (b"ANAM", b"AnimTextData\\Tables\\Graphs\\SimpleLoop01.agx\0"),
       (b"BNAM", b"ships\\animated\\fan01\\characterassets\\skeleton.rig\0"),
       (b"CNAM", b"ships\\animated\\fan01\\animations\0")]
CRATE = [(b"EDID", b"Crate01\0"), (b"MODL", b"Crate.nif\0")]
BOX = [(b"EDID", b"Box01\0"), (b"ANAM", b"AnimTextData\\Tables\\Graphs\\SimpleOpenClose01.agx\0"),
       (b"BNAM", b"x\\skeleton.rig\0")]


class ProbeTests(unittest.TestCase):
    def test_scan_record(self):
        r = P.scan_record(FAN)
        self.assertEqual(r["edid"], "ShipFan01")
        self.assertTrue(r["graph"].endswith("SimpleLoop01.agx"))
        self.assertEqual(r["where"]["rig"], "BNAM")
        self.assertEqual(r["anims"], "ships\\animated\\fan01\\animations")
        self.assertEqual(P.scan_record(CRATE)["graph"], "")
        self.assertTrue(P.loopy(r))
        self.assertFalse(P.loopy(P.scan_record(BOX)))

    def test_main(self):
        import sf_anim_survey as SAS
        files = {"meshes/ships/animated/fan01/animations/idle.afx":
                 b"<root><is_state>1</is_state><tag>Idle</tag><filename>Spin.af</filename></root>",
                 "meshes/ships/animated/fan01/animations/spin.af": b"af"}

        class Ba2:
            names = list(files)

            def read(self, i):
                return files[self.names[i]]
        recs = [(b"STAT", b"", FAN, 0x100), (b"STAT", b"", CRATE, 0x101), (b"ACTI", b"", BOX, 0x102)]
        out = io.StringIO()
        with mock.patch.object(P.sfplugin, "records", lambda _p, _t: recs), \
                mock.patch.object(SAS, "archives", lambda _d: [("x", Ba2())]), contextlib.redirect_stdout(out):
            self.assertEqual(P.main(["--starfield", "S"]), 0)
        text = out.getvalue()
        self.assertIn("== 2 records with a graph and a rig", text)
        self.assertLess(text.index("SimpleLoop01"), text.index("SimpleOpenClose01"))      # loopy graphs first
        self.assertIn("idle.afx  tag Idle file Spin.af", text)
        self.assertNotIn("Crate01", text)


    def test_axis_angle_and_tracks(self):
        import math
        h = math.sqrt(0.5)
        self.assertEqual(P.axis_angle((0, h, 0, h)), ((0.0, 1.0, 0.0), 90.0))
        from fo4sf import af_writer
        rb = {"frames": 5, "bones": ["Root", "Spin"], "translations": {},
              "rotations": {"Spin": [(f, (0, math.sin(math.radians(22.5 * f)), 0, math.cos(math.radians(22.5 * f))))
                                     for f in range(5)]}}
        import tempfile
        with tempfile.TemporaryDirectory() as d, mock.patch.object(af_writer, "read_back", lambda *_a, **_k: rb):
            lines = P.track_lines("x.dll", b"rig", b"af", d)
        self.assertIn("5 frames", lines[0])
        self.assertIn("frame 4: ((0.0, 1.0, 0.0), 180.0)", lines[2])            # half a turn over the clip
        self.assertIn("Root: 0 rotation keys", lines[1])

    def test_dump_and_extract(self):
        import sf_anim_survey as SAS
        import tempfile
        files = {"meshes/ships/animated/fan01/animations/idle.afx": b"<root><tag>Idle</tag></root>",
                 "meshes/ships/animated/fan01/characterassets/skeleton.rig": b"rig",
                 "meshes/ships/fan01.nif": b"nif"}

        class Ba2:
            names = list(files)

            def read(self, i):
                return files[self.names[i]]
        recs = [(b"STAT", b"", FAN, 0x100)]
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as d, mock.patch.object(P.sfplugin, "records", lambda _p, _t: recs), \
                mock.patch.object(SAS, "archives", lambda _d: [("x", Ba2())]), contextlib.redirect_stdout(out):
            dst = os.path.join(d, "fan")
            P.main(["--starfield", "S", "--match", "Fan01", "--dump", "Fan01", "--extract-to", dst])
            got = sorted(os.listdir(dst))
            with self.assertRaises(SystemExit):                        # never into the repository
                P.main(["--starfield", "S", "--match", "Fan01", "--extract-to", ROOT])
        self.assertIn("== STAT 00000100 ShipFan01", out.getvalue())
        self.assertIn("BNAM", out.getvalue())
        self.assertEqual(got, ["meshes_ships_animated_fan01_animations_idle.afx",
                               "meshes_ships_animated_fan01_characterassets_skeleton.rig", "meshes_ships_fan01.nif"])

    def test_extract_every_matched_model(self):
        """2026-11-18: the yard fan blade's model was not copied: a Stroud miniature came first in the shared
        rotate_y01 folder, and only the first record per folder was extracted."""
        import sf_anim_survey as SAS
        import tempfile
        mini = [(b"EDID", b"Miniature01\0"), (b"MODL", b"Mini.nif\0")] + FAN[2:]
        files = {"meshes/ships/fan01.nif": b"nif", "meshes/mini.nif": b"mini",
                 "meshes/ships/animated/fan01/animations/idle.af": b"af"}

        class Ba2:
            names = list(files)

            def read(self, i):
                return files[self.names[i]]
        recs = [(b"STAT", b"", mini, 0x99), (b"STAT", b"", FAN, 0x100)]
        with tempfile.TemporaryDirectory() as d, mock.patch.object(P.sfplugin, "records", lambda _p, _t: recs), \
                mock.patch.object(SAS, "archives", lambda _d: [("x", Ba2())]), contextlib.redirect_stdout(io.StringIO()):
            dst = os.path.join(d, "fan")
            P.main(["--starfield", "S", "--match", "Fan01", "--extract-to", dst])
            self.assertIn("meshes_ships_fan01.nif", os.listdir(dst))

    def test_dump_other_plugin(self):
        """--plugin: dump our own plugin's records (FO4Port.esm turning parts) and stop."""
        seen = []
        recs = [(b"ACTI", b"", FAN, 0x100)]
        out = io.StringIO()
        with mock.patch.object(P.sfplugin, "records", lambda p, _t: seen.append(p) or recs), \
                mock.patch.object(P, "survey", side_effect=AssertionError("no survey")), contextlib.redirect_stdout(out):
            self.assertEqual(P.main(["--starfield", "S", "--dump", "Fan", "--plugin", "FO4Port.esm"]), 0)
        self.assertEqual(seen, [os.path.join("S", "Data", "FO4Port.esm")])
        self.assertIn("== ACTI 00000100 ShipFan01", out.getvalue())


if __name__ == "__main__":
    unittest.main()
