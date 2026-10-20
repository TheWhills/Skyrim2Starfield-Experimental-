"""scripts/armor/dodge_graph.py on a synthetic MeleeActions-like graph (fo4sf.agx_write; no game files)."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import agx_edit, agx_write  # noqa: E402
import dodge_graph as D  # noqa: E402


def actions_graph() -> bytes:
    idle = {"nodes": [{"kind": "empty"}], "links": []}
    g = {"name": "Data\\Meshes\\AnimTextData\\Tables\\Graphs\\MeleeActions.agx", "default": 2,
         "nodes": [{"kind": "anim", "tag": "CastSelf"},
                   {"kind": "anim", "tag": "MeleeBlock_Out", "props": {"Send Event On End": "BlockStop"}},
                   {"kind": "sm", "name": "IdleTimer", "graph": idle}],
         "links": [(0, 0, {"event": "CastSelfStart", "blend": 0}), (0, 2, {"blend": 0.3}),
                   (1, 2, {"blend": 0.3})]}
    return agx_write.write(g)


class DodgeGraphTests(unittest.TestCase):
    def test_four_way(self):
        raw = actions_graph()
        data, rep = D.build(raw, tags={"Back": "MeleeBlock_HitReaction"})
        g = agx_edit.machine(agx_edit.load(data))
        nodes = g.findall("node")
        self.assertEqual(len(nodes), 7)
        t = agx_edit.transitions(g)
        for d, st in rep["states"].items():
            i = st["index"]
            self.assertIn((i, i, f"TKDodge{d}", ""), t)                 # any state -> dodge on the plugin's event
            self.assertIn((i, 2, "", ""), t)                            # back to IdleTimer when the clip ends
            rows = agx_edit._rows(nodes[i])
            self.assertEqual(rows["Send Event On End"], "TKDR_DodgeEnd")
            self.assertEqual(rows["TagName"], "MeleeBlock_HitReaction" if d == "Back" else f"TKDodge{d}")
        self.assertIn((0, 0, "CastSelfStart", ""), t)                    # vanilla links untouched
        self.assertEqual(agx_edit._rows(nodes[1])["Send Event On End"], "BlockStop")
        with self.assertRaises(agx_edit.AgxEditError):                   # applying twice is refused
            D.build(data)

    def test_eight_way_and_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "meleeactions.agx")
            with open(src, "wb") as fh:
                fh.write(actions_graph())
            out = os.path.join(tmp, "pack")
            self.assertEqual(D.main(["--graph", src, "--out", out, "--eight-way", "--tag", "Left=X"]), 0)
            with open(os.path.join(out, *D.GRAPH_REL), "rb") as fh:
                g = agx_edit.machine(agx_edit.load(fh.read()))
            events = {e for _s, _d, e, _c in agx_edit.transitions(g)}
            self.assertTrue({f"TKDodge{d}" for d in D.EIGHT} <= events)
            with self.assertRaises(SystemExit):
                D.main(["--graph", src, "--out", out, "--tag", "Up=X"])

    def test_set_row(self):
        g = agx_edit.machine(agx_edit.load(actions_graph()))
        node = g.findall("node")[0]
        self.assertTrue(agx_edit.set_row(node, "Sync System", "SyncX"))
        self.assertEqual(agx_edit._rows(node)["Sync System"], "SyncX")
        self.assertFalse(agx_edit.set_row(node, "No Such Row", "x"))


if __name__ == "__main__":
    unittest.main()
