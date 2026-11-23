"""scripts/armor/sam_dodge_pack.py on synthetic files: own tags per direction, the SAM fragment (every clip file, every
tag), the graphs (one dodge state per direction playing its own tag, on the NPC attack events; the player switch
learns them), and main wiring with the conversion stubbed (no game files, no CALUMI)."""
import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import agx_edit, agx_write  # noqa: E402
import sam_dodge_pack as S  # noqa: E402
from test_dodge_pack import attacks_graph  # noqa: E402


def player_graph() -> bytes:
    """A graph with one Switch option row listing the power attack events (as test_dodge_pack's switch test)."""
    import copy
    base = agx_write.write({"name": "Data\\Meshes\\AnimTextData\\Tables\\Graphs\\Player_Melee.agx", "default": 0,
                            "nodes": [{"kind": "anim", "tag": "A"}], "links": []})
    root = agx_edit.load(base)
    sheet = root.find("node").find("property_sheet")
    row = copy.deepcopy(sheet.find("row"))
    props = row.findall("prop")
    props[0].find("value").text = "Attacking"
    props[1].find("value").text = "MeleeAttackPowerStart,MeleeAttackSprintStart"
    sheet.append(row)
    return agx_edit.dump(root, base)


def project(clips, motions):
    """One project block and its motion section of an animationdatasinglefile (animdata's layout)."""
    block = ["1", "1", "Behaviors\\x.hkx", "1"]
    for name, ident in clips:
        block += [name, ident, "1", "0", "0", "0", ""]
    motion = []
    for ident, dist in motions:
        motion += [ident, "0.866667", "2", "0 0 0 0", f"0.866667 0 {dist} 0", "1", "0.866667 0 0 0 1", ""]
    return [str(len(block))] + block + [str(len(motion))] + motion


def singlefile() -> str:
    """Another project first, reusing id 3 with another motion; DefaultMale's dodges on ids 3-6."""
    lines = ["2", "Other.txt", "DefaultMale.txt"]
    lines += project([("SomethingElse", "3")], [("3", 999.0)])
    lines += project([("TKDodgeForward", "3"), ("TKDodgeBack", "4"), ("TKDodgeLeft", "5"), ("TKDodgeRight", "6"),
                      ("Unrelated", "7")], [("3", 409.0), ("4", -300.0), ("5", 252.0), ("6", 252.5), ("7", 1.0)])
    return "\r\n".join(lines) + "\r\n"


class SamDodgePackTests(unittest.TestCase):
    def test_motion_by_clip_name(self):
        from fo4sf import rootmotion
        blocks = S.motion_blocks(singlefile())
        self.assertEqual({d: i for d, (i, _b) in blocks.items()},
                         {"Forward": "3", "Back": "4", "Left": "5", "Right": "6"})
        lone = rootmotion.parse_motion_data(S.motion_text(blocks))
        self.assertEqual(lone["3"]["translations"][-1][2], 409.0)      # DefaultMale's id 3, not Other's
        self.assertEqual(lone["6"]["translations"][-1][2], 252.5)
        self.assertAlmostEqual(lone["4"]["duration"], 0.866667)
        self.assertEqual(rootmotion.parse_motion_data(singlefile())["3"]["translations"][-1][2], 999.0)  # why lone
        with self.assertRaises(SystemExit):
            S.motion_blocks(singlefile().replace("TKDodgeLeft", "TKDodgeSideways"))
        with self.assertRaises(SystemExit):
            S.motion_blocks(singlefile(), project="FirstPerson")

    def test_fragment(self):
        t = S.tags()
        self.assertEqual(t, {"Forward": "S2S_DodgeForward", "Back": "S2S_DodgeBack", "Left": "S2S_DodgeLeft",
                             "Right": "S2S_DodgeRight"})
        f = S.fragment_files(t)
        lines = f["meshes/animtextdata/fragments/S2SDodge/animations.txt"].decode().split("\r\n")
        self.assertEqual(len([x for x in lines if x]), 8)
        self.assertIn("Meshes\\actors\\human\\animations\\melee\\onehanded\\player\\S2S_DodgeLeft.af", lines)
        self.assertIn("Meshes\\actors\\human\\animations\\melee\\onehanded\\player\\S2S_DodgeLeft.afx", lines)
        xtbl = f["meshes/animtextdata/fragments/S2SDodge/tables/anim_actions.xtbl"]
        for tag in t.values():
            self.assertIn(f"<entry><name>{tag}</name></entry>".encode(), xtbl)
        self.assertTrue(xtbl.startswith(b"<root>\r\n<table>\r\n"))

    def test_graphs(self):
        files, rep = S.graphs(attacks_graph(), player_graph(), S.tags())
        root = agx_edit.load(files[S.ATTACKS_REL])
        tags = {agx_edit._rows(n).get("TagName") for n in root.findall("node")}
        for d, tag in S.tags().items():
            self.assertIn(tag, tags)
            self.assertEqual(rep["states"][d]["event"], S.dodge_graph.KNOWN_EVENTS[d])
        self.assertEqual(rep["player_switch_lists"], 1)
        self.assertIn(b"MeleeAttack01", files[S.PLAYER_REL])
        self.assertIn(b"MeleeAttack04", files[S.PLAYER_REL])

    def test_main(self):
        vanilla = {S.ATTACKS_REL: attacks_graph(), S.PLAYER_REL: player_graph()}
        fake = types.ModuleType("hkx_to_af")
        fake.vanilla_file = lambda p, d: (vanilla[p], p)
        clips = {f"{S.ANIMS}{S.FOLDER}/{t}{e}": b"X" for t in S.tags().values() for e in (".af", ".afx")}
        saved_mod, saved_conv = sys.modules.get("hkx_to_af"), S.convert
        sys.modules["hkx_to_af"] = fake
        S.convert = lambda tk, tm, sd, rest: (0, clips, {"clips": 4})
        try:
            with tempfile.TemporaryDirectory() as d:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(S.main(["--tk", d, "--starfield-data", d, "--out", d, "--calumi", "x"]), 0)
                for rel in list(clips) + [S.ATTACKS_REL, S.PLAYER_REL,
                                          "meshes/animtextdata/fragments/S2SDodge/tables/anim_actions.xtbl"]:
                    self.assertTrue(os.path.isfile(os.path.join(d, *rel.split("/"))), rel)
                with open(os.path.join(d, "sam_dodge.json")) as fh:
                    rep = json.load(fh)
                self.assertEqual(rep["states"]["Back"]["tag"], "S2S_DodgeBack")
                self.assertEqual(rep["conversion"], {"clips": 4})
                with self.assertRaises(SystemExit):
                    S.main(["--tk", d, "--starfield-data", d, "--out", ROOT])
        finally:
            S.convert = saved_conv
            if saved_mod is None:
                sys.modules.pop("hkx_to_af", None)
            else:
                sys.modules["hkx_to_af"] = saved_mod


if __name__ == "__main__":
    unittest.main()
