import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))

import object_sound_probe as P  # noqa: E402
from fo4sf import nif as N  # noqa: E402


class ModelInfo(unittest.TestCase):
    def test_graph_and_text_keys(self):
        n = N.NifFile(bs_version=100)
        n.strings = [b"BGED", b"Furniture\\Wheel\\WheelBehavior.hkx", b"start", b"sound: OBJWheelLP"]
        n.add_block("NiNode", b"\0" * 8)
        n.add_block("BSBehaviorGraphExtraData", struct.pack("<iiB", 0, 1, 1))
        n.add_block("NiTextKeyExtraData", struct.pack("<iI", -1, 2) + struct.pack("<fi", 0.0, 2)
                    + struct.pack("<fi", 1.5, 3))
        info = P.model_info(n)
        self.assertEqual(info["graphs"], ["Furniture\\Wheel\\WheelBehavior.hkx"])
        self.assertEqual(info["text_keys"], [(0.0, "start"), (1.5, "sound: OBJWheelLP")])
        self.assertEqual(info["types"]["NiNode"], 1)
        self.assertIn("Furniture\\Wheel\\WheelBehavior.hkx", info["paths"])

    def test_short_blocks_skipped(self):
        n = N.NifFile(bs_version=100)
        n.add_block("NiTextKeyExtraData", b"\0\0")
        self.assertEqual(P.model_info(n)["text_keys"], [])


class GraphLines(unittest.TestCase):
    def test_triggers_and_state_events(self):
        b = {"events": ["SoundPlay", "Spin"], "nodes": {
            1: {"class": "hkbClipGenerator", "name": "Spin", "animation": "Anims\\Spin.hkx", "triggers": 2,
                "children": []},
            2: {"class": "hkbClipTriggerArray", "triggers": [{"time": 0.5, "event": 0, "payload": 3}],
                "children": []},
            3: {"class": "hkbStringEventPayload", "data": "OBJWheelLP", "children": []},
            4: {"class": "hkbStateMachineStateInfo", "name": "SpinState", "enter_events": 5, "children": []},
            5: {"class": "hkbStateMachineEventPropertyArray", "events": [{"event": 0, "payload": 3}],
                "children": []},
            6: {"class": "hkbClipGenerator", "name": "Still", "animation": "Anims\\Still.hkx", "children": []}}}
        text = "\n".join(P.graph_lines(b))
        self.assertIn("clip 'Spin' (Anims\\Spin.hkx): 0.5 SoundPlay OBJWheelLP", text)
        self.assertIn("state 'SpinState' enter: SoundPlay OBJWheelLP", text)
        self.assertIn("clip 'Still' (Anims\\Still.hkx): no triggers", text)


if __name__ == "__main__":
    unittest.main()
