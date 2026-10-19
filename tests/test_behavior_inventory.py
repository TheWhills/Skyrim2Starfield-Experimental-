"""scripts/armor/behavior_inventory.py on a synthetic hk_2010 packfile (no game data)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import hkpackfile  # noqa: E402
import behavior_inventory as B  # noqa: E402
from test_skyrim_hkx import Hkx2010  # noqa: E402


def graph_file(bias=0):
    """A clip generator (name + animation path) and a string-data object (an array of event names); `bias` extra
    leading bytes per object, as in Pandora's template copies."""
    h = Hkx2010()
    clip = h.obj("hkbClipGenerator", 64 + bias)
    h.string(clip + bias + 16, "IdleClip")
    h.string(clip + bias + 40, "Animations\\Idle.hkx")
    sd = h.obj("hkbBehaviorGraphStringData", 64 + bias)
    arr = h.alloc(16)
    h.string(arr, "HorseEnter")
    h.string(arr + 8, "HorseExit")
    h.array(sd + bias + 16, arr, 2)
    h.obj("hkbStateMachine", 32)
    return h.bytes()


class BehaviorInventoryTests(unittest.TestCase):
    def test_object_strings_direct_and_arrays(self):
        for bias in (0, 8):
            pf = hkpackfile.Packfile(graph_file(bias))
            got = {c: s for _o, c, s in B.object_strings(pf)}
            self.assertEqual(got["hkbClipGenerator"], ["IdleClip", "Animations\\Idle.hkx"])
            self.assertEqual(got["hkbBehaviorGraphStringData"], ["HorseEnter", "HorseExit"])

    def test_inventory_per_creature(self):
        inv = B.inventory([("meshes\\actors\\horse\\behaviors\\horsebehavior.hkx", graph_file()),
                           ("meshes\\actors\\horse\\broken.hkx", b"not havok")])
        h = inv["horse"]
        self.assertEqual((h["files"], h["failed"], h["clips"], h["state_machines"]), (2, 1, 1, 1))
        self.assertEqual(h["animation_examples"], ["animations/idle.hkx"])
        self.assertEqual(h["graph_string_examples"], ["HorseEnter", "HorseExit"])


if __name__ == "__main__":
    unittest.main()
