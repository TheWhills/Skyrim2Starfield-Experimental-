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


def graph(bias=0, triggers=False, enter=False):
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
    if triggers:                                       # objects first: data allocated later is outside their ranges
        ta2 = h.obj("hkbClipTriggerArray", 32 + B)
        pay = h.obj("hkbStringEventPayload", 24 + B)
    if enter:                                          # Walk's enter events: moveStart with a prop payload
        epa = h.obj("hkbStateMachineEventPropertyArray", 32 + B)
        pay2 = h.obj("hkbStringEventPayload", 24 + B)
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
    if triggers:                                       # IdleClip: moveStop at 0.5 s with a string payload
        h.string(pay + B + 16, "AnimObjectHammer")
        rec2 = h.alloc(32)
        h.put(rec2, "<f", 0.5)
        h.put(rec2 + 8, "<i", 1)
        h.ptr(rec2 + 16, pay)
        h.put(rec2 + 24, "<3B", 0, 1, 0)
        h.array(ta2 + B + 16, rec2, 1)
        h.ptr(c0 + B + 80, ta2)
    if enter:
        h.string(pay2 + B + 16, "AnimObjectAxe")
        rec3 = h.alloc(16)
        h.put(rec3, "<i", 0)
        h.ptr(rec3 + 8, pay2)
        h.array(epa + B + 16, rec3, 1)
        h.ptr(s1 + B + 64, epa)
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

    def test_clip_triggers_and_string_payloads(self):
        """2026-11-16 (smithing_probe): a clip's triggers (time, event, payload) and string payloads (prop names)."""
        for bias in (0, 8):
            b = SB.read(graph(bias, triggers=True))
            clip = next(n for n in b["nodes"].values() if n.get("name") == "IdleClip")
            tr = b["nodes"][clip["triggers"]]["triggers"]
            self.assertEqual([(t["time"], b["events"][t["event"]], t["acyclic"]) for t in tr], [(0.5, "moveStop", True)])
            self.assertEqual(b["nodes"][tr[0]["payload"]]["data"], "AnimObjectHammer")

    def test_smithing_probe_reads_the_machine_and_triggers(self):
        import re
        import smithing_probe as P
        b = SB.read(graph(triggers=True))
        rx = re.compile("walk|idle", re.I)
        m, = P.machines_with(b, rx)
        self.assertEqual((m["name"], m["start"]), ("Locomotion", "Idle"))
        self.assertEqual([(s["name"], s["clips"], s["transitions"]) for s in m["states"]],
                         [("Idle", ["Idle.hkx"], [("moveStart", "Walk")]), ("Walk", ["Walk.hkx"], [])])
        self.assertEqual(P.clip_triggers(b, rx), [("IdleClip", "Idle.hkx", [(0.5, "moveStop", "AnimObjectHammer")])])
        self.assertEqual(P.payload_strings(b), ["AnimObjectHammer"])
        self.assertEqual(P.machines_with(b, re.compile("anvil")), [])

    def test_state_enter_events_and_prop_sources(self):
        """2026-11-17: a state's enter events (the axe / hoe / pickaxe are sent there, not in clip triggers)."""
        import smithing_probe as P
        for bias in (0, 8):
            b = SB.read(graph(bias, triggers=True, enter=True))
            walk = next(n for n in b["nodes"].values() if n.get("name") == "Walk")
            e, = b["nodes"][walk["enter_events"]]["events"]
            self.assertEqual((b["events"][e["event"]], b["nodes"][e["payload"]]["data"]), ("moveStart", "AnimObjectAxe"))
            self.assertEqual(P.prop_sources(b), {"AnimObjectAxe": ["state 'Walk' enter moveStart"],
                                                 "AnimObjectHammer": ["clip 'IdleClip' 0.5 s moveStop"]})

    def test_clip_file_index_prefers_third_person(self):
        import smithing_probe as P
        names = ["meshes\\actors\\character\\_1stperson\\animations\\animobjectmillloadstart.hkx",
                 "meshes\\actors\\character\\animations\\animobjectmillloadstart.hkx",
                 "meshes\\actors\\character\\_1stperson\\animations\\only1st.hkx"]
        ix = P.clip_file_index(names)
        self.assertEqual(ix["animobjectmillloadstart.hkx"], names[1])
        self.assertEqual(ix["only1st.hkx"], names[2])

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
