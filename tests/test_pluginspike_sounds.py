"""dotnet/PluginSpike (uncompiled here): copies of Starfield lights and furniture lose their looping sounds (2026-11-21,
owner: "an ambient electrical buzz i hear, cant trace it"). Source checks, as the other PluginSpike tests."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


class LoopingSoundsTest(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(HERE, "..", "dotnet", "PluginSpike", "Program.cs"), encoding="utf-8") as fh:
            self.cs = fh.read()

    def test_light_copies_lose_their_sound(self):
        i = self.cs.index("var nl = (Light)tpl.Duplicate(")
        self.assertRegex(self.cs[i:i + 600], r"nl\.SoundReference = null")

    def test_furniture_copies_lose_their_loop(self):
        i = self.cs.index('var f = (Furniture)tpl.Duplicate(')
        self.assertRegex(self.cs[i:i + 700], r"f\.LoopingSound = null")

    def test_the_build_names_what_it_removed(self):
        self.assertTrue(re.search(r"looping sounds removed from copies of", self.cs))


if __name__ == "__main__":
    unittest.main()
