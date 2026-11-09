"""scripts/armor/sam_test_pack.py on synthetic files: the combo's first attack retagged to the new tag (nothing else
in the graph changes), the clip's descriptor retagged (variant fields dropped, timing kept), the SAM fragment (clip list
with Data paths from Meshes\\, anim_actions.xtbl with the tag), files written where the mod needs them."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import agx_edit  # noqa: E402
import sam_test_pack as S  # noqa: E402
from test_dodge_pack import attacks_graph  # noqa: E402

AFX = (b"<root>\r\n\t<is_state>0</is_state>\r\n\t<tag>MeleeAttackPower_A</tag>\r\n\t<prefix>Ready</prefix>\r\n"
       b"\t<filename>MeleeAttackPower_A.af</filename>\r\n\t<rampout>10</rampout>\r\n\t<events>\r\n\t\t<event><frame>12"
       b"</frame><name>HitFrame</name><payload></payload></event>\r\n\t</events>\r\n</root>\r\n")


class SamTestPackTests(unittest.TestCase):
    def test_parts(self):
        out = S.retag(AFX, "S2S_SamTest", "S2S_SamTest.af").decode()
        self.assertIn("<tag>S2S_SamTest</tag>", out)
        self.assertIn("<filename>S2S_SamTest.af</filename>", out)
        self.assertNotIn("<prefix>", out)
        self.assertIn("<name>HitFrame</name>", out)
        self.assertIn("<rampout>10</rampout>", out)
        raw = attacks_graph()
        g, n = S.point_host(raw, "MeleeAttack_A", "S2S_SamTest")
        self.assertEqual(n, 1)
        combo = agx_edit.machine(agx_edit.load(g), S.MACHINE)
        self.assertEqual(agx_edit.state(combo, "S2S_SamTest"), agx_edit.state(agx_edit.machine(agx_edit.load(raw),
                                                                                                 S.MACHINE), "MeleeAttack_A"))
        self.assertEqual(g.replace(b"S2S_SamTest", b"MeleeAttack_A"), raw)        # nothing else changed
        with self.assertRaises(agx_edit.AgxEditError):
            S.point_host(raw, "MeleeAttack_Z", "S2S_SamTest")
        f = S.fragment_files("S2S_SamTest", "melee/onehanded/player")
        lines = f["meshes/animtextdata/fragments/S2SSamTest/animations.txt"].decode().split("\r\n")
        self.assertEqual(lines[:2], ["Meshes\\actors\\human\\animations\\melee\\onehanded\\player\\S2S_SamTest.af",
                                     "Meshes\\actors\\human\\animations\\melee\\onehanded\\player\\S2S_SamTest.afx"])
        self.assertIn(b"<entry><name>S2S_SamTest</name></entry>",
                      f["meshes/animtextdata/fragments/S2SSamTest/tables/anim_actions.xtbl"])

    def test_main(self):
        files = {S.GRAPH_REL: attacks_graph(),
                 S.ANIMS + "melee/onehanded/player/sword/meleeattackpower_a.af": b"AFDATA",
                 S.ANIMS + "melee/onehanded/player/sword/meleeattackpower_a.afx": AFX}     # only in the sword folder
        saved = S.read_vanilla
        S.read_vanilla = lambda p, d: (files[p.replace("\\", "/").lower()], p.lower())
        try:
            with tempfile.TemporaryDirectory() as d:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(S.main(["--out", d]), 0)
                with open(os.path.join(d, *S.GRAPH_REL.split("/")), "rb") as fh:
                    self.assertIn(b"S2S_SamTest", fh.read())
                clip = os.path.join(d, "meshes", "actors", "human", "animations", "melee", "onehanded", "player")
                with open(os.path.join(clip, "S2S_SamTest.af"), "rb") as fh:
                    self.assertEqual(fh.read(), b"AFDATA")
                with open(os.path.join(clip, "S2S_SamTest.afx"), "rb") as fh:
                    self.assertIn(b"<tag>S2S_SamTest</tag>", fh.read())
                self.assertTrue(os.path.exists(os.path.join(d, "meshes", "animtextdata", "fragments", "S2SSamTest",
                                                            "tables", "anim_actions.xtbl")))
                with open(os.path.join(d, "sam_test.json")) as fh:
                    rep = json.load(fh)
                self.assertEqual(rep["states_changed"], 1)
                self.assertIn("/sword/", rep["clip_from"])
                with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
                    S.main(["--out", d, "--clip", "nosuchclip"])
                with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                    S.main(["--out", d, "--tag", "bad tag"])
        finally:
            S.read_vanilla = saved


if __name__ == "__main__":
    unittest.main()
