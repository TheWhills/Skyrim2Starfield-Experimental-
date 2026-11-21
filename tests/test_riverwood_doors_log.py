"""tools/owner/riverwood_doors.ps1 output (2026-11-21, owner: "does it need to do all of this every time we test"): the
window shows each step's summary, the full output goes to <Work>\\logs\\riverwood_doors_last.log, steps are timed.
The noise list (tools/owner/log_noise.txt) is checked here against lines of the owner's builds (paths made up)."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def noise():
    with open(os.path.join(ROOT, "tools", "owner", "log_noise.txt"), encoding="utf-8") as fh:
        return [re.compile(l, re.I) for l in fh.read().splitlines() if l and not l.startswith("#")]


def quiet(line, rx):
    return any(r.search(line) for r in rx)


HIDDEN = [
    '{"converted": 250, "assets": 250, "failed": 15, "materials_ok": 161}',
    "package template 01D281:Starfield.esm: no clean vanilla package; copying FFNewHomesteadZ01_Bill_Tour09_EscortPlayer",
    "Orgnar in RiverwoodSleepingGiantInn at [-1312.75, 18.295, 0.0] (its face-test NPC 06000805 in S2SFaceTest.esm):",
    "  S2S_OrgnarWorkInn0x24: SandboxWorking -> Sandbox, hour -1 for 0 min; inputs Location=near_reference",
    "  note: OrgnarWorkInn0x24: inputs without a Starfield counterpart kept vanilla: ['Prefered Path Only? (Bool)']",
    "  A/B: vanilla UC_NA_FaradKallobSandbox 00268B:Starfield.esm added unchanged after ours",
    "actor Alvor: NPC 00080B:S2SFaceTest.esm (its face-test NPC S2SFace_Alvor 00080B:S2SFaceTest.esm, overridden)",
    "  flags 0 -> 0; template actors 0; default template none",
    "  alchemy -> WorkbenchChem: CraftingAlchemyWorkbenchTabletop x1, CraftingAlchemyWorkbench x1",
    "  skipped: WoodPile: no Starfield furniture for it (left as a static)",
    "  alcohol FoodMead                     x10  -> Drink_Alc_Can_Erdebrau_Lager             size [0.093]",
    "  kitchen BasicTankard01               x77  -> Bar_MartiniGlass01                       size [0.149]",
    "  lifted FoodSalmonCooked 0600F3:Skyrim.esm by 3.1 cm onto BasicWoodenPlate01 0600F4:Skyrim.esm",
    "  light FO4Port_SkyLight_000: radius 8 -> 7.3142858 m, lumens 4000 -> 8000",
    "  cell lighting: template 006658:Starfield.esm values + Skyrim ambient [",
    "   45,",
    "  ] x1",
    "furniture: S2S_Furn_WoodenChair01 000E7A:FO4Port.esm: copy of FoundCanvasChair01_Free (chair)",
    'items: S2S_Item_FoodMead 001001:FO4Port.esm: copy of Drink_Alc_Can_Erdebrau_Lager (drink), "Nord Mead"',
    "next: make_skyrim_objects.py convert --work C:\\work ..., then check --work C:\\work",
    "  dotnet run --project dotnet\\PluginSpike -- \"C:\\work\\convert\"",
]
SHOWN = [
    "== 2e. food, drink, potions and clutter as items",
    "  FAIL x15: ValueError: no triangle geometry",
    "Traceback (most recent call last):",
    "ValueError: no Starfield donor",
    "FAILED: make_items",
    "WARNING: outdoor furniture not placed (no EXTERIOR_DIR with EXTERIOR_DOORS / EXTERIOR_NAVMESH)",
    "  skipped FoodRabbit: model Clutter\\DeadAnimals\\RabbitMeat01.nif not converted (left as a static)",
    "579 placed items from 75 Skyrim bases in 6 cells (59 owned in Skyrim: not yet owned here)",
    "items started inside another item's body, lifted onto it: 12 (largest 3.1 cm); holders with things in them kept static: 6",
    "looping sounds removed from copies of: furniture WorkbenchChem, furniture WorkbenchIndustrial",
    "cell FO4Port_RiverwoodSvensHouse 000D6C:FO4Port.esm: placed 53 references + 6 lights (0 initially disabled)",
    "  items: 69 references (ALCH / MISC copies, dynamic)",
    "  RiverwoodSleepingGiantInn                  406/430   converted  coc yes  doors 1",
    "Program.cs(1016,59): error CS1061: 'Ingestible' does not contain a definition for 'Description'",
    "installed. Undo with: python deploy_starfield.py uninstall --starfield <game dir>",
]


class NoiseTest(unittest.TestCase):
    def test_detail_lines_hidden(self):
        rx = noise()
        self.assertEqual([l for l in HIDDEN if not quiet(l, rx)], [])

    def test_summaries_and_every_failure_shown(self):
        rx = noise()
        self.assertEqual([l for l in SHOWN if quiet(l, rx)], [])


class ScriptTest(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "tools", "owner", "riverwood_doors.ps1"), encoding="utf-8") as fh:
            self.ps = fh.read()

    def test_every_native_call_goes_through_run(self):
        code = [l for l in self.ps.splitlines() if not l.lstrip().startswith("#")]
        bare = [l for l in code if re.search(r"(^\s*|\{ )(python -I|dotnet run)", l)]
        self.assertEqual(bare, [])
        self.assertGreaterEqual(sum("Run python -I" in l for l in code), 15)
        self.assertEqual(sum("Run dotnet run" in l for l in code), 1)

    def test_log_file_steps_timed_full_log_switch(self):
        self.assertIn('Join-Path $LogDir "riverwood_doors_last.log"', self.ps)
        self.assertIn("[switch]$FullLog", self.ps)
        self.assertIn("log_noise.txt", self.ps)
        self.assertIn("function Timings", self.ps)
        # the end of every way out prints the step times: full build, assets-only, -NoInstall, a failure
        self.assertGreaterEqual(self.ps.count("Timings"), 6)
        self.assertIn('PYTHONUNBUFFERED = "1"', self.ps)

    def test_assets_only_skips_the_navmesh_defaults_search(self):
        # owner 2026-11-21 -AssetsOnly: 87 s total, 75 s in steps - the C:\Modding search ran before the branch
        search = self.ps.index("-Filter navmesh_defaults.json")
        self.assertGreater(search, self.ps.index("assets-only build:"))
        self.assertGreater(search, self.ps.index('Step "1. interior batch'))


if __name__ == "__main__":
    unittest.main()
