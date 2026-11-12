"""scripts/harness: the headless test instance's pure parts on synthetic data (no game, any OS).

The live parts (hidden desktop, injection, screenshots, cdb) are Windows calls checked by the owner's smoke run."""
import argparse
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "harness"))
import crash_capture as C  # noqa: E402
import hidden_launch as H  # noqa: E402
import test_instance as T  # noqa: E402

#: sfse_loader/Inject.cpp kCode (ianpatt/sfse), copied by hand from the source: the stub must match it.
SFSE_KCODE = bytes([0x48, 0x83, 0xEC, 0x28, 0x48, 0x8B, 0xD9, 0x48, 0x8D, 0x4B, 0x10, 0xFF, 0x13, 0x48, 0x8B,
                    0xC8, 0xBA, 0x01, 0x00, 0x00, 0x00, 0xFF, 0x53, 0x08, 0xFF, 0xD0, 0x48, 0x83, 0xC4, 0x28, 0xC3])


class Payload(unittest.TestCase):
    def test_stub_is_sfse_loaders(self):
        self.assertEqual(H.LOADER_STUB, SFSE_KCODE)
        self.assertEqual(H.LOADER_STUB[H.ORDINAL_AT - 1], 0xBA)  # mov edx, imm32

    def test_layout_matches_inject_dll_thread_data(self):
        block = H.loader_payload(0x1122334455667788, 0x99AABBCCDDEEFF00, b"D:\\S2S Test\\sfse_1_16_244.dll", 1)
        self.assertEqual(block[0:8], (0x1122334455667788).to_bytes(8, "little"))
        self.assertEqual(block[8:16], (0x99AABBCCDDEEFF00).to_bytes(8, "little"))
        self.assertTrue(block[0x10:].startswith(b"D:\\S2S Test\\sfse_1_16_244.dll\0"))
        self.assertEqual(H.CODE_AT, 0x810)
        self.assertEqual(block[H.CODE_AT:], SFSE_KCODE)

    def test_other_ordinal_and_long_path(self):
        block = H.loader_payload(1, 2, b"x.dll", 7)
        self.assertEqual(block[H.CODE_AT + H.ORDINAL_AT:H.CODE_AT + H.ORDINAL_AT + 4], b"\x07\0\0\0")
        with self.assertRaises(ValueError):
            H.loader_payload(1, 2, b"a" * 2048, 1)

    def test_environment_block(self):
        text = H.environment_block({"PATH": "p", "b": "1"}, {"SteamAppId": "1716740", "b": "2"})
        self.assertTrue(text.endswith("\0\0"))
        self.assertEqual(text.split("\0")[:3], ["b=2", "PATH=p", "SteamAppId=1716740"])

    def test_under(self):
        self.assertTrue(H.under(os.path.join("x", "S2S Test", "Starfield.exe"), os.path.join("x", "S2S Test")))
        self.assertFalse(H.under(os.path.join("x", "S2S Test2", "Starfield.exe"), os.path.join("x", "S2S Test")))
        self.assertFalse(H.under("", "x"))


class Ini(unittest.TestCase):
    def test_add_section_and_key(self):
        text = T.set_ini("", "Display", "iSize W", "640")
        self.assertEqual(text, "[Display]\niSize W=640\n")
        text = T.set_ini(text, "display", "ISIZE W", "800")
        self.assertEqual(text, "[Display]\nISIZE W=800\n")

    def test_key_added_before_next_section(self):
        text = "[General]\na=1\n\n[Display]\nb=2\n"
        out = T.set_ini(text, "General", "sIntroSequence", "")
        self.assertEqual(out, "[General]\na=1\nsIntroSequence=\n\n[Display]\nb=2\n")

    def test_override_spec(self):
        self.assertEqual(T.parse_ini_override("StarfieldCustom.ini:General:iFPSClamp=6"),
                         ("StarfieldCustom.ini", "General", "iFPSClamp", "6"))
        self.assertEqual(T.parse_ini_override("StarfieldPrefs.ini:Display:iSize W=1280")[2], "iSize W")
        with self.assertRaises(ValueError):
            T.parse_ini_override("General:iFPSClamp=6")


class Selection(unittest.TestCase):
    def test_sfse_dll_highest(self):
        self.assertEqual(T.sfse_dll(["sfse_1_15_222.dll", "sfse_1_16_244.dll", "sfse_loader.exe",
                                     "sfse_1_9_51.dll"]), "sfse_1_16_244.dll")
        self.assertIsNone(T.sfse_dll(["Starfield.exe"]))

    def test_vanilla_files(self):
        root = ["Starfield.exe", "steam_api64.dll", "dxgi.dll", "sfse_1_16_244.dll", "sfse_loader.exe",
                "Starfield.ccc", "readme.txt"]
        data = ["Starfield.esm", "Constellation.esm", "SFBGS009.esm", "S2SArmorTest.esm", "Starfield - Meshes01.ba2",
                "Constellation - Textures.ba2", "SFBGS009 - Main.ba2", "S2SArmorTest - Main.ba2", "Mod - x.ba2"]
        files = T.vanilla_files(root, data, ["versionlib-1-16-244-0.bin", "SomePlugin.dll"], "SFBGS009.esm\n")
        names = [f.replace("\\", "/") for f in files]
        self.assertEqual(names, ["Starfield.exe", "steam_api64.dll", "sfse_1_16_244.dll", "Starfield.ccc",
                                 "Data/Starfield.esm", "Data/Constellation.esm", "Data/SFBGS009.esm",
                                 "Data/Starfield - Meshes01.ba2", "Data/Constellation - Textures.ba2",
                                 "Data/SFBGS009 - Main.ba2", "Data/SFSE/Plugins/versionlib-1-16-244-0.bin"])

    def test_plugins(self):
        self.assertEqual(T.mod_plugins(["b.esp", "meta.ini", "A.esm", "c.esl"]), ["A.esm", "b.esp", "c.esl"])
        self.assertEqual(T.plugins_txt(["A.esm", "b.esp"]).splitlines()[1:], ["*A.esm", "*b.esp"])

    def test_sfse_problems(self):
        lines = ["plugin S2SCombat.dll (00000001 S2SCombat 00000001) loaded correctly",
                 "plugin Old.dll (00000001 Old 00000001) disabled, incompatible with current runtime version"]
        self.assertEqual(T.sfse_problems(lines), lines[1:])


class Build(unittest.TestCase):
    def test_build_links_vanilla_and_mods(self):
        with tempfile.TemporaryDirectory() as tmp:
            sf = os.path.join(tmp, "Starfield")
            files = ["Starfield.exe", "sfse_1_16_244.dll", "dxgi.dll", os.path.join("Data", "Starfield.esm"),
                     os.path.join("Data", "Starfield - Meshes01.ba2"), os.path.join("Data", "Other.esp"),
                     os.path.join("Data", "SFSE", "Plugins", "versionlib-1-16-244-0.bin")]
            for rel in files:
                os.makedirs(os.path.dirname(os.path.join(sf, rel)) or sf, exist_ok=True)
                with open(os.path.join(sf, rel), "w") as f:
                    f.write(rel)
            mod = os.path.join(tmp, "mods", "S2S Armor Test")
            os.makedirs(os.path.join(mod, "Meshes"))
            for rel in ("S2SArmorTest.esm", "meta.ini", os.path.join("Meshes", "a.txt")):
                with open(os.path.join(mod, rel), "w") as f:
                    f.write(rel)
            prefs = os.path.join(tmp, "StarfieldPrefs.ini")
            with open(prefs, "w") as f:
                f.write("[Display]\niSize W=2560\nfRenderResolutionScaleFactor=1.0\n")
            inst_dir = os.path.join(tmp, "S2S Test")
            args = argparse.Namespace(starfield=sf, instance_dir=inst_dir, mod=[mod], prefs_from=prefs,
                                      ini=["StarfieldCustom.ini:General:iFPSClamp=6"])
            with open(os.devnull, "w") as quiet:
                old, sys.stdout = sys.stdout, quiet
                try:
                    self.assertEqual(T.build(args), 0)
                finally:
                    sys.stdout = old
            inst = T.Instance(inst_dir)
            self.assertTrue(os.path.samefile(os.path.join(inst_dir, "Data", "Starfield.esm"),
                                             os.path.join(sf, "Data", "Starfield.esm")))
            self.assertFalse(os.path.exists(os.path.join(inst_dir, "dxgi.dll")))
            self.assertFalse(os.path.exists(os.path.join(inst_dir, "Data", "Other.esp")))
            self.assertTrue(os.path.exists(os.path.join(inst.data, "SFSE", "Plugins", "versionlib-1-16-244-0.bin")))
            self.assertTrue(os.path.exists(os.path.join(inst.data, "Meshes", "a.txt")))
            self.assertFalse(os.path.exists(os.path.join(inst.data, "meta.ini")))
            with open(inst.plugins_txt) as f:
                self.assertIn("*S2SArmorTest.esm", f.read())
            with open(os.path.join(inst.my_games, "StarfieldPrefs.ini")) as f:
                p = f.read()
            self.assertIn("iSize W=640", p)
            self.assertIn("fRenderResolutionScaleFactor=1.0", p)
            with open(os.path.join(inst.my_games, "StarfieldCustom.ini")) as f:
                c = f.read()
            self.assertIn("iFPSClamp=6", c)
            self.assertIn("bInvalidateOlderFiles=1", c)
            with open(inst.state) as f:
                self.assertEqual(json.load(f)["sfse_dll"], "sfse_1_16_244.dll")
            with open(os.path.join(inst_dir, "steam_appid.txt")) as f:
                self.assertEqual(f.read(), "1716740")

    def test_refuses_instance_inside_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "Starfield.exe"), "w").close()
            args = argparse.Namespace(starfield=tmp, instance_dir=os.path.join(tmp, "inside"), mod=[],
                                      prefs_from="", ini=[])
            with self.assertRaises(SystemExit):
                T.build(args)


class Capture(unittest.TestCase):
    def test_section(self):
        log = "noise\nMARKER_ARMED\nMARKER_CRASH\nexr\nMARKER_REGS\nrax=1\nMARKER_STACK\nkb\n"
        self.assertEqual(C.section(log, "MARKER_CRASH"), "MARKER_CRASH\nexr\n")
        self.assertEqual(C.section(log, "MARKER_REGS"), "MARKER_REGS\nrax=1\n")
        self.assertEqual(C.section(log, "MARKER_DUMPED"), "")

    def test_capture_script_arms_before_go_and_detaches(self):
        script = C.CAPTURE.format(dump="x.dmp").splitlines()
        self.assertLess(script.index(".echo MARKER_ARMED"), script.index("g"))
        self.assertIn("sxe c0000409", script)  # fast-fail is caught, not passed
        self.assertEqual(script[-2:], [".detach", "qd"])


if __name__ == "__main__":
    unittest.main()
