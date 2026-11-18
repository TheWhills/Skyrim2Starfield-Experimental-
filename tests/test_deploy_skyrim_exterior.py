"""deploy_skyrim_exterior.py on a fake staging folder and game folder (Archive2 replaced by a stub)."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import deploy_skyrim_exterior as d  # noqa: E402


def fake_archive2(cmd, cwd=None, capture_output=None, text=None):
    out = next(c.split("=", 1)[1] for c in cmd if c.startswith("-create="))
    assert "-compression=None" in cmd and "-format=General" in cmd
    with open(out, "wb") as f:
        f.write(b"BTDX" + bytes(32))
    return mock.Mock(returncode=0, stdout="", stderr="")


class DeployTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.staging, self.game, self.local = (os.path.join(t, n) for n in ("stage", "game", "local"))
        os.makedirs(os.path.join(self.staging, "Data", "Terrain"))
        os.makedirs(os.path.join(self.staging, "Data", "meshes"))
        open(os.path.join(self.staging, "Data", "Terrain", "x.btd"), "wb").write(b"btd")
        with open(os.path.join(self.staging, "overlays_params.json"), "w") as f:
            json.dump({"plugin": "SkyrimTerrainTamriel.esm", "mars": {"plugin": "SkyrimTerrainTamriel_Mars.esm"},
                       "overlays": [{"coc": "SKY_TamrielRiverwoodSpawn"}]}, f)
        for p in ("SkyrimTerrainTamriel.esm", "SkyrimTerrainTamriel_Mars.esm"):
            open(os.path.join(self.staging, p), "wb").write(b"TES4" + p.encode())
        os.makedirs(os.path.join(self.game, "Data"))
        os.makedirs(os.path.join(self.game, "Tools", "Archive2"))
        open(os.path.join(self.game, "Tools", "Archive2", "Archive2.exe"), "wb").close()
        os.makedirs(os.path.join(self.local, "Starfield"))
        self.pt = os.path.join(self.local, "Starfield", "Plugins.txt")
        open(self.pt, "wb").write(b"# comment\r\n*FO4Port.esm\r\n")
        self.env = mock.patch.dict(os.environ, {"LOCALAPPDATA": self.local})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_main(self, *args):
        with mock.patch.object(d.subprocess, "run", fake_archive2), contextlib.redirect_stdout(io.StringIO()) as out:
            d.main(list(args))
        return out.getvalue()

    def test_install_and_uninstall_round_trip(self):
        out = self.run_main("install", "--staging", self.staging, "--starfield", self.game)
        self.assertIn("coc SKY_TamrielRiverwoodSpawn", out)
        data = os.path.join(self.game, "Data")
        self.assertEqual(sorted(f for f in os.listdir(data) if not f.endswith(".json")),
                         ["SkyrimTerrainTamriel - Main.ba2", "SkyrimTerrainTamriel.esm", "SkyrimTerrainTamriel_Mars.esm"])
        self.assertEqual(open(self.pt, "rb").read(),
                         b"# comment\r\n*FO4Port.esm\r\n*SkyrimTerrainTamriel.esm\r\n*SkyrimTerrainTamriel_Mars.esm\r\n")
        with self.assertRaises(SystemExit):                       # second install refused
            self.run_main("install", "--staging", self.staging, "--starfield", self.game)
        self.run_main("uninstall", "--starfield", self.game)
        self.assertEqual(os.listdir(data), [])
        self.assertEqual(open(self.pt, "rb").read(), b"# comment\r\n*FO4Port.esm\r\n")

    def test_refuses_a_second_terrain_experiment_and_overwrites(self):
        open(os.path.join(self.game, "Data", "TerrainCore64_Mars.esm"), "wb").close()
        with self.assertRaises(SystemExit) as cm:
            self.run_main("install", "--staging", self.staging, "--starfield", self.game)
        self.assertIn("another terrain experiment", str(cm.exception))
        os.remove(os.path.join(self.game, "Data", "TerrainCore64_Mars.esm"))
        open(os.path.join(self.game, "Data", "SkyrimTerrainTamriel.esm"), "wb").close()
        with self.assertRaises(SystemExit) as cm:
            self.run_main("install", "--staging", self.staging, "--starfield", self.game)
        self.assertIn("refusing to overwrite", str(cm.exception))

    def test_refuses_plugins_older_than_params(self):
        pp = os.path.join(self.staging, "overlays_params.json")
        t = os.path.getmtime(os.path.join(self.staging, "SkyrimTerrainTamriel.esm"))
        os.utime(pp, (t + 60, t + 60))                       # params rewritten after the plugin: a failed rebuild
        with self.assertRaises(SystemExit) as cm:
            self.run_main("install", "--staging", self.staging, "--starfield", self.game)
        self.assertIn("older than overlays_params.json", str(cm.exception))

    def test_uninstall_keeps_a_changed_file(self):
        self.run_main("install", "--staging", self.staging, "--starfield", self.game)
        open(os.path.join(self.game, "Data", "SkyrimTerrainTamriel.esm"), "ab").write(b"edited")
        with self.assertRaises(SystemExit):
            self.run_main("uninstall", "--starfield", self.game)
        self.assertTrue(os.path.exists(os.path.join(self.game, "Data", "SkyrimTerrainTamriel.esm")))
        self.assertFalse(os.path.exists(os.path.join(self.game, "Data", "SkyrimTerrainTamriel - Main.ba2")))

    def test_uninstall_removes_our_own_patches(self):
        """2026-11-18 (owner): after riverwood_doors.ps1 (apply_ref_overrides.py on the exterior plugin) and
        set_planet_latlon.py (planet plugin patched in the staging and the game alike), uninstall stopped on both."""
        self.run_main("install", "--staging", self.staging, "--starfield", self.game)
        data = os.path.join(self.game, "Data")
        main = os.path.join(data, "SkyrimTerrainTamriel.esm")
        import shutil
        shutil.copy2(main, main + d.REF_OVERRIDES_BACKUP)
        open(main, "ab").write(b"patched")
        for where in (os.path.join(data, "SkyrimTerrainTamriel_Mars.esm"),
                      os.path.join(self.staging, "SkyrimTerrainTamriel_Mars.esm")):
            open(where, "ab").write(b"latlon")
        with self.assertRaises(SystemExit):                    # without --staging the planet plugin is unknown
            self.run_main("uninstall", "--starfield", self.game)
        self.assertFalse(os.path.exists(main) or os.path.exists(main + d.REF_OVERRIDES_BACKUP))
        self.run_main("uninstall", "--starfield", self.game, "--staging", self.staging)
        self.assertEqual(os.listdir(data), [])


if __name__ == "__main__":
    unittest.main()
