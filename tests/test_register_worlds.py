"""register_worlds (several worldspaces on one planet) and make_skyrim_overlay --like (a city built with the installed
Tamriel's options), 2026-11-10 (owner: the walled cities as their own spaces, like Skyrim)."""
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))

from fo4sf import sfplugin  # noqa: E402
import register_worlds as RW  # noqa: E402
import make_skyrim_overlay as MSO  # noqa: E402

Z = lambda t: t.encode() + b"\0"                                         # noqa: E731
I = lambda v: struct.pack("<I", v)                                       # noqa: E731
INFO = {"hedr_version": 0.96, "form_version": 555}


def h(t):
    return struct.pack("<4sIII", t, 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)


def write(path, recs, masters):
    with open(path, "wb") as fh:
        fh.write(sfplugin.build([(t, h(t), s, f) for t, s, f in recs], INFO, masters=masters))


class RegisterTests(unittest.TestCase):
    def test_cities_join_the_planet(self):
        with tempfile.TemporaryDirectory() as d:
            main, city = os.path.join(d, "skyrim_all"), os.path.join(d, "whiterun")
            os.makedirs(main)
            os.makedirs(city)
            with open(os.path.join(main, "overlays_params.json"), "w") as fh:
                json.dump({"mars": {"plugin": "SkyrimTerrainTamriel_Mars.esm"}, "overlays": [{}]}, fh)
            write(os.path.join(main, "SkyrimTerrainTamriel_Mars.esm"), [
                (b"PNDT", [(b"EDID", Z("NirnPlanetData")), (b"CNAM", struct.pack("<ddI", 0.785, 0.0, 0x01000803)),
                           (b"PPBD", I(0x02000801))], 0x02000800),
                (b"LCTN", [(b"EDID", Z("SNirn_PNirn_Surface"))], 0x02000805),
                (b"LCTN", [(b"EDID", Z("SNirn_PNirn"))], 0x02000804)], ["Starfield.esm", "SkyrimTerrainTamriel.esm"])
            with open(os.path.join(city, "overlays_params.json"), "w") as fh:
                json.dump({"overlays": [{"location": "SKY_WhiterunWorldLocation"}]}, fh)
            with open(os.path.join(city, "formids.json"), "w") as fh:
                json.dump({"plugin": "SkyrimTerrainWhiterunWorld.esm", "world_form_id": "000803"}, fh)
            write(os.path.join(city, "SkyrimTerrainWhiterunWorld.esm"), [
                (b"LCTN", [(b"EDID", Z("SKY_WhiterunWorldLocation")), (b"KWDA", I(0x2CA99D) + I(0x01000900)),
                           (b"PNAM", I(0x01B736))], 0x01000802)], ["Starfield.esm"])
            out = os.path.join(d, "reg")
            self.assertEqual(RW.main(["--main", main, "--world", city, "--out", out]), 0)
            pl = os.path.join(out, RW.PLUGIN)
            self.assertEqual(RW.masters_of(pl), ["Starfield.esm", "SkyrimTerrainTamriel.esm",
                                                 "SkyrimTerrainTamriel_Mars.esm", "SkyrimTerrainWhiterunWorld.esm"])
            recs = {sfplugin.edid(s): (s, fid) for _t, _h, s, fid in sfplugin.records(pl, [b"PNDT", b"LCTN"])}
            ps, pfid = recs["NirnPlanetData"]
            self.assertEqual(pfid, 0x02000800)
            ents = RW.cnam_entries(dict(ps)[b"CNAM"])
            self.assertEqual(ents[0], (0.785, 0.0, 0x01000803))                           # Tamriel kept
            self.assertAlmostEqual(ents[1][0], 0.785)
            self.assertAlmostEqual(ents[1][1], 0.02)
            self.assertEqual(ents[1][2], 0x03000803)                                       # the city's world
            self.assertEqual(dict(ps)[b"PPBD"], I(0x02000801))
            ls, lfid = recs["SKY_WhiterunWorldLocation"]
            self.assertEqual(lfid, 0x03000802)
            self.assertEqual(dict(ls)[b"PNAM"], I(0x02000805))                             # Nirn's surface
            self.assertEqual(dict(ls)[b"KWDA"], I(0x2CA99D) + I(0x03000900))
            rep = json.load(open(os.path.join(out, "register_worlds.json")))
            self.assertEqual(rep["entries"], 2)

    def test_spacing_wraps(self):
        self.assertAlmostEqual(math.remainder(math.pi - 0.01 + 0.02, 2 * math.pi), -math.pi + 0.01)


class LikeTests(unittest.TestCase):
    def test_split_and_like(self):
        args = ["C:\\Py\\python.exe", "C:\\repo\\make_skyrim_overlay.py", "build", "--skyrim",
                "C:\\Games\\Skyrim Special Edition\\Data\\Skyrim.esm", "--out", "C:\\staging\\skyrim_all",
                "--height-offset", "385", "--cells", "-10", "10", "-5", "5", "--landmark=-30,-20",
                "--skyrim-water", "--planet", "JemisonPlanetData", "--latlon", "-1.5707963", "0",
                "--biome", "1CBD6A", "--display-name", "Skyrim", 'a "quoted" \\ value\\']
        line = subprocess.list2cmdline(args)
        self.assertEqual(MSO.split_cmdline(line), args)
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "build_command.txt"), "w", encoding="utf-8") as fh:
                fh.write(line + "\n")
            got = MSO.like_args(d)
            self.assertEqual(got, ["--skyrim", "C:\\Games\\Skyrim Special Edition\\Data\\Skyrim.esm",
                                   "--height-offset", "385", "--skyrim-water", "--planet", "JemisonPlanetData",
                                   "--biome", "1CBD6A", 'a "quoted" \\ value\\'])
            raw, st = MSO.expand_like(["build", "--world-edid", "WhiterunWorld", "--like", d, "--out", "X",
                                       "--no-mars"])
            self.assertEqual(st, d)
            self.assertEqual(raw[:3], ["build", "--skyrim", "C:\\Games\\Skyrim Special Edition\\Data\\Skyrim.esm"])
            self.assertEqual(raw[-5:], ["--world-edid", "WhiterunWorld", "--out", "X", "--no-mars"])

    def test_planet_options_without_registration(self):
        import types
        prm = {"mars": None, "overlays": [{}]}
        a = types.SimpleNamespace(planet="JemisonPlanetData", latlon=None, template_world="", template_block="",
                                  template_location="", biome="1CBD6A", climate="24E982", location_parent="01AB2B")
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            MSO.apply_planet(prm, a)                       # no --latlon needed: register_worlds places it
        self.assertEqual(prm["world_overrides"], {"biome": "1CBD6A", "climate": "24E982"})
        self.assertEqual(prm["location_parent"], "01AB2B")


if __name__ == "__main__":
    unittest.main()
