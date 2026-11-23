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
        bad = singlefile().replace("0.866667 0 999.0 0", "0.066667 animmotion 0.0 0.0 0.0")   # other project
        self.assertEqual(S.motion_blocks(bad)["Forward"][1]["translations"][-1][2], 409.0)
        bad = singlefile().replace("0.866667 0 1.0 0", "0.066667 animmotion 0.0 0.0 0.0")     # unwanted block
        self.assertEqual(S.motion_blocks(bad)["Right"][1]["translations"][-1][2], 252.5)

    def test_variables(self):
        afx = b"<root><is_state>0</is_state><tag>S2S_DodgeBack</tag><filename>S2S_DodgeBack.af</filename></root>"
        out = S.with_variables(afx, ["bNoLeftHandIK"], 20).decode()
        self.assertIn("<variable><name>bNoLeftHandIK</name><start>0</start><end>20</end></variable>", out)
        self.assertEqual(S.with_variables(afx, [], 20), afx)
        twice = S.with_variables(out.encode(), ["bNoLeftHandIK"], 20).decode()
        self.assertEqual(twice.count("bNoLeftHandIK"), 1)

    def test_head_track_variable(self):
        raw = (b"<root><Name>Player_Melee.agx</Name><node><node_type>NT_DUAL_DIRECT_AT</node_type><name>Dual Direct At"
               b"</name><property_sheet><row><prop><value>No Head Track Variable</value></prop><prop><value>"
               b"bNoHeadTrack</value></prop></row><row><prop><value>No Aim Variable</value></prop><prop><value>bNoAim"
               b"</value></prop></row></property_sheet></node></root>")
        out, n = S.head_track_variable(raw, "bNoAim")
        self.assertEqual(n, 1)
        self.assertIn(b"<value>No Head Track Variable</value></prop><prop><value>bNoAim</value>", out)
        self.assertNotIn(b"bNoHeadTrack", out)
        self.assertEqual(S.head_track_variable(player_graph(), "bNoAim"), (player_graph(), 0))   # no such node
        files, rep = S.graphs(attacks_graph(), player_graph(), S.tags(), "bNoAim")
        self.assertEqual(rep["head_track_nodes"], 0)
        raw2 = raw.replace(b"</property_sheet>", b"<row><prop><value>Disable Heading Min</value></prop><prop><value>-90"
                           b"</value></prop></row><row><prop><value>Disable Heading Max</value></prop><prop><value>90"
                           b"</value></prop></row></property_sheet>")
        out, n = S.head_track_limit(raw2, 180)
        self.assertEqual(n, 1)
        self.assertIn(b"<value>Disable Heading Min</value></prop><prop><value>-180</value>", out)
        self.assertIn(b"<value>Disable Heading Max</value></prop><prop><value>180</value>", out)
        self.assertIn(b"bNoHeadTrack", out)                                  # head tracking itself left on
        self.assertEqual(S.head_track_limit(player_graph(), 180), (player_graph(), 0))

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
        S.convert = lambda tk, tm, sd, rest, variables=(): (0, clips, {"clips": 4})
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
                with contextlib.redirect_stdout(io.StringIO()):            # diagnostic: Back plays a vanilla tag
                    self.assertEqual(S.main(["--tk", d, "--starfield-data", d, "--out", d,
                                             "--state-tag", "Back=MeleeAttackPower_A"]), 0)
                with open(os.path.join(d, "sam_dodge.json")) as fh:
                    st = json.load(fh)["states"]
                self.assertEqual(st["Back"]["tag"], "MeleeAttackPower_A")
                self.assertEqual(st["Forward"]["tag"], "S2S_DodgeForward")
                with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                    S.main(["--tk", d, "--starfield-data", d, "--out", d, "--state-tag", "Up=X"])
                with self.assertRaises(SystemExit):
                    S.main(["--tk", d, "--starfield-data", d, "--out", ROOT])
                with self.assertRaises(SystemExit):
                    S.main(["--tk", d, "--starfield-data", d, "--out", d, "--dll", os.path.join(d, "missing.dll")])
            with tempfile.TemporaryDirectory() as d:                      # the standalone mod: DLL + INI
                dll = os.path.join(d, "built.dll")
                with open(dll, "wb") as fh:
                    fh.write(b"MZ")
                out = os.path.join(d, "mod")
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(S.main(["--tk", d, "--starfield-data", d, "--out", out, "--dll", dll]), 0)
                plugins = os.path.join(out, "SFSE", "Plugins")
                with open(os.path.join(plugins, "S2SDodge.dll"), "rb") as fh:
                    self.assertEqual(fh.read(), b"MZ")
                with open(os.path.join(plugins, "S2SDodge.ini"), encoding="utf-8") as fh:
                    self.assertIn("uDodgeKey = 56", fh.read())
                with open(os.path.join(plugins, "S2SDodge.ini"), "w", encoding="utf-8") as fh:
                    fh.write("mine")                                       # the player's settings are kept
                with contextlib.redirect_stdout(io.StringIO()):
                    S.main(["--tk", d, "--starfield-data", d, "--out", out, "--dll", dll])
                with open(os.path.join(plugins, "S2SDodge.ini"), encoding="utf-8") as fh:
                    self.assertEqual(fh.read(), "mine")
                with open(os.path.join(out, "sam_dodge.json")) as fh:
                    self.assertIn("SFSE/Plugins/S2SDodge.dll", json.load(fh)["files"])
        finally:
            S.convert = saved_conv
            if saved_mod is None:
                sys.modules.pop("hkx_to_af", None)
            else:
                sys.modules["hkx_to_af"] = saved_mod


if __name__ == "__main__":
    unittest.main()
