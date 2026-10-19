"""fo4sf.skyrimbehavior on a synthetic hk_2010 behaviour graph (no game data), with and without the 8-byte object
bias of Pandora's template copies."""
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
from fo4sf import skyrimbehavior as SB  # noqa: E402
from test_skyrim_hkx import Hkx2010  # noqa: E402


def graph(bias=0):
    h = Hkx2010()
    B = bias
    root = h.obj("hkRootLevelContainer", 16 + B)
    g = h.obj("hkbBehaviorGraph", 160 + B)
    gd = h.obj("hkbBehaviorGraphData", 128 + B)
    sd = h.obj("hkbBehaviorGraphStringData", 80 + B)
    sm = h.obj("hkbStateMachine", 176 + B)
    s0 = h.obj("hkbStateMachineStateInfo", 120 + B)
    s1 = h.obj("hkbStateMachineStateInfo", 120 + B)
    ta = h.obj("hkbStateMachineTransitionInfoArray", 32 + B)
    c0 = h.obj("hkbClipGenerator", 120 + B)
    c1 = h.obj("hkbClipGenerator", 120 + B)
    nv = h.alloc(24)
    h.array(root + B, nv, 1)
    h.ptr(nv + 16, g)
    h.string(g + B + 56, "TestBehavior")
    h.ptr(g + B + 128, sm)
    h.ptr(g + B + 136, gd)
    h.ptr(gd + B + 120, sd)
    ev = h.alloc(16)
    h.string(ev, "moveStart")
    h.string(ev + 8, "moveStop")
    h.array(sd + B + 16, ev, 2)
    var = h.alloc(8)
    h.string(var, "Speed")
    h.array(sd + B + 48, var, 1)
    h.string(sm + B + 56, "Locomotion")
    h.put(sm + B + 104, "<i", 0)
    st = h.alloc(16)
    h.ptr(st, s0)
    h.ptr(st + 8, s1)
    h.array(sm + B + 144, st, 2)
    for s, sid, name, clip in ((s0, 0, "Idle", c0), (s1, 1, "Walk", c1)):
        h.string(s + B + 96, name)
        h.put(s + B + 104, "<ifB", sid, 1.0, 1)
        h.ptr(s + B + 88, clip)
    h.ptr(s0 + B + 80, ta)
    rec = h.alloc(72)
    h.put(rec + 48, "<4i", 0, 1, -1, -1)                         # moveStart -> state 1
    h.array(ta + B + 16, rec, 1)
    for c, name, anim in ((c0, "IdleClip", "Animations\\Idle.hkx"), (c1, "WalkClip", "Animations\\Walk.hkx")):
        h.string(c + B + 56, name)
        h.string(c + B + 72, anim)
        h.put(c + B + 88, "<4f", 0, 0, 0, 1.25)
    return h.bytes()


class SkyrimBehaviorTests(unittest.TestCase):
    def test_read_with_and_without_bias(self):
        for bias in (0, 8):
            b = SB.read(graph(bias))
            self.assertEqual(b["bias"], bias)
            self.assertEqual((b["name"], b["events"], b["variables"]), ("TestBehavior", ["moveStart", "moveStop"], ["Speed"]))
            sm = b["nodes"][b["root"]]
            self.assertEqual((sm["name"], sm["start_state"], len(sm["states"])), ("Locomotion", 0, 2))
            idle = b["nodes"][sm["states"][0]]
            self.assertEqual((idle["name"], idle["state_id"]), ("Idle", 0))
            t = b["nodes"][idle["transitions"]]["transitions"][0]
            self.assertEqual((t["event"], t["to_state"]), (0, 1))
            walk = b["nodes"][b["nodes"][sm["states"][1]]["generator"]]
            self.assertEqual((walk["animation"], walk["speed"]), ("Animations\\Walk.hkx", 1.25))
            self.assertEqual(b["checks"], [])
            self.assertEqual(SB.summary(b)["transitions"], 1)

    def test_checks_catch_a_bad_target(self):
        data = bytearray(graph())
        b = SB.read(bytes(data))
        # point the transition at a state that does not exist by rewriting toStateId in the raw bytes
        i = bytes(data).find(struct.pack("<4i", 0, 1, -1, -1))
        data[i + 4:i + 8] = struct.pack("<i", 7)
        self.assertTrue(any("transition to 7" in c for c in SB.read(bytes(data))["checks"]))

    def test_dump_tree(self):
        import behavior_dump as D
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "test.hkx")
            with open(p, "wb") as fh:
                fh.write(graph())
            D.dump(p, d)
            with open(os.path.join(d, "test.txt"), encoding="utf-8") as fh:
                txt = fh.read()
        self.assertIn("SM Locomotion (start 0)", txt)
        self.assertIn("[0] Idle: moveStart->1", txt)
        self.assertIn("clip WalkClip: Animations\\Walk.hkx x1.25", txt)


if __name__ == "__main__":
    unittest.main()
