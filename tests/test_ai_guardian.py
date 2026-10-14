"""Resource Guardian admission policy (tools/ai-team/guardian/policy.py): synthetic snapshots, no hardware."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "ai-team", "guardian"))
import policy  # noqa: E402


def snap(vram=40.0, ram=40.0, loaded=True, reachable=True, procs=None):
    return {"gpu": {"available": True, "vram_pct": vram}, "ram": {"used_pct": ram},
            "lmstudio": {"reachable": reachable, "loaded": [{"id": "m"}] if loaded else []},
            "agents": {"processes": procs or {}}}


class PolicyTests(unittest.TestCase):
    cfg = dict(policy.DEFAULTS)

    def test_normal_admits_one_and_queues_the_second(self):
        self.assertEqual(policy.admit(snap(), self.cfg, 0)[0], "admit")
        decision, _, why = policy.admit(snap(), self.cfg, 1)          # max_concurrent_local = 1
        self.assertEqual(decision, "queue")
        self.assertTrue(any("max 1" in w for w in why))

    def test_ram_thresholds(self):
        self.assertEqual(policy.level(snap(ram=69.9), self.cfg)[0], "normal")
        self.assertEqual(policy.level(snap(ram=75), self.cfg)[0], "caution")
        self.assertEqual(policy.level(snap(ram=86), self.cfg)[0], "restrict")
        self.assertEqual(policy.level(snap(ram=91), self.cfg)[0], "block")
        self.assertEqual(policy.admit(snap(ram=86), self.cfg, 0)[0], "queue")   # overload queues new work

    def test_vram_with_resident_model_only_restricts_above_92(self):
        self.assertEqual(policy.level(snap(vram=88, loaded=True), self.cfg)[0], "normal")
        self.assertEqual(policy.level(snap(vram=93, loaded=True), self.cfg)[0], "restrict")
        self.assertEqual(policy.level(snap(vram=96, loaded=True), self.cfg)[0], "block")
        self.assertEqual(policy.level(snap(vram=88, loaded=False), self.cfg)[0], "restrict")

    def test_running_game_or_unreachable_server_blocks(self):
        lv, why = policy.level(snap(procs={"Starfield.exe": {}}), self.cfg)
        self.assertEqual(lv, "block")
        self.assertTrue(any("game running" in w for w in why))
        self.assertEqual(policy.level(snap(reachable=False), self.cfg)[0], "block")
        cfg = dict(self.cfg, game_blocks_inference=False)
        self.assertEqual(policy.level(snap(procs={"Starfield.exe": {}}), cfg)[0], "normal")


if __name__ == "__main__":
    unittest.main()
