"""sound_swap: vanilla events' streamed files and the assignment of Skyrim's files to them (2026-11-20)."""
import os
import struct
import sys
import tempfile
import unittest
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))

import sound_swap as S  # noqa: E402


class SwapTests(unittest.TestCase):
    def test_event_files(self):
        info = {"SoundBanksInfo": {"SoundBanks": [{"IncludedEvents": [
            {"Name": "A", "ReferencedStreamedFiles": [{"Id": "1"}, {"Id": "2"}]},
            {"Name": "B", "ReferencedStreamedFiles": [{"Id": "2"}]}, {"Name": "C"}]}]}}
        files, users = S.event_files(info)
        self.assertEqual(files, {"A": ["1", "2"], "B": ["2"], "C": []})
        self.assertEqual(users["2"], {"A", "B"})

    def test_assign(self):
        self.assertEqual(S.assign(["h1", "h2", "h3", "h4"], ["a", "b", "c"]), [("a", "h1"), ("b", "h2"), ("c", "h3")])
        self.assertEqual(S.assign(["q"], ["a", "b", "c"]), [("a", "q"), ("b", "q"), ("c", "q")])
        self.assertEqual(S.assign([], ["a"]), [])

    def test_pcm_wem_keeps_the_vanilla_format(self):
        """2026-11-20: vanilla food-station files are PCM 0xFFFE mono 48 kHz 16-bit with a JUNK chunk; ours keep
        that fmt and JUNK byte for byte, the data resampled from the Skyrim file's rate."""
        fmt_body = struct.pack("<HHIIHH", 0xFFFE, 1, 48000, 96000, 2, 16) + struct.pack("<HHI", 6, 16, 4)
        fmt = b"fmt " + struct.pack("<I", len(fmt_body)) + fmt_body
        junk = b"JUNK" + struct.pack("<I", 4) + bytes(4)
        data = b"data" + struct.pack("<I", 8) + bytes(8)
        body = b"WAVE" + fmt + junk + data
        vanilla = b"RIFF" + struct.pack("<I", len(body)) + body
        stereo = np.stack([np.linspace(-0.5, 0.5, 2205), np.linspace(-0.5, 0.5, 2205)], 1)   # 0.1 s at 22.05 kHz
        out = S.pcm_wem(vanilla, stereo, 22050)
        chunks = dict(S.riff_chunks(out))
        self.assertEqual(chunks[b"fmt "], fmt)
        self.assertEqual(chunks[b"JUNK"], junk)
        n = struct.unpack_from("<I", chunks[b"data"], 4)[0]
        self.assertEqual(n, 2 * 4800)                                          # 0.1 s at 48 kHz, mono 16-bit
        self.assertEqual(struct.unpack_from("<I", out, 4)[0], len(out) - 8)
        pcm = np.frombuffer(chunks[b"data"][8:8 + n], "<i2")
        self.assertAlmostEqual(pcm[0] / 32767.0, -0.5, places=3)
        bad = vanilla.replace(struct.pack("<H", 0xFFFE), struct.pack("<H", 0xFFFF), 1)
        with self.assertRaises(ValueError):
            S.pcm_wem(bad, stereo, 22050)

    def test_read_wav(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.wav")
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(44100)
                w.writeframes(np.array([0, 16384, -16384], "<i2").tobytes())
            x, rate = S.read_wav(path)
            self.assertEqual((x.shape, rate), ((3, 1), 44100))
            self.assertAlmostEqual(float(x[1, 0]), 0.5)

    def test_pool_and_plan(self):
        info = {"SoundBanksInfo": {"SoundBanks": [{"ShortName": "Starfield_NPC", "IncludedEvents": [
            {"Name": "B_Station", "ObjectPath": "\\Events\\X\\Crafting_Events\\B", "DurationType": "OneShot",
             "MaxAttenuation": "13.", "ReferencedStreamedFiles": [{"Id": "1"}]},
            {"Name": "A_Station", "ObjectPath": "\\Events\\X\\Crafting_Events\\A", "DurationType": "OneShot",
             "MaxAttenuation": "13.", "ReferencedStreamedFiles": [{"Id": "2"}]},
            {"Name": "Shared", "ObjectPath": "\\Events\\X\\Crafting_Events\\S", "DurationType": "OneShot",
             "MaxAttenuation": "13.", "ReferencedStreamedFiles": [{"Id": "3"}]},
            {"Name": "Other", "ObjectPath": "\\Events\\X\\Furniture\\O", "DurationType": "OneShot",
             "MaxAttenuation": "13.", "ReferencedStreamedFiles": [{"Id": "3"}]},
            {"Name": "Quiet", "ObjectPath": "\\Events\\X\\Furniture\\Q", "DurationType": "OneShot",
             "MaxAttenuation": "5.", "ReferencedStreamedFiles": [{"Id": "4"}]},
            {"Name": "Loop", "ObjectPath": "\\Events\\X\\Furniture\\L", "DurationType": "Infinite",
             "MaxAttenuation": "13.", "ReferencedStreamedFiles": [{"Id": "5"}]},
            {"Name": "Ambient", "ObjectPath": "\\Events\\X\\AMB\\Z", "DurationType": "OneShot",
             "MaxAttenuation": "13.", "ReferencedStreamedFiles": [{"Id": "6"}]}]}]}}
        _files, users = S.event_files(info)
        pool = S.pool_events(info, users, {"B_Station"})
        self.assertEqual(pool, ["A_Station"])                # shared, quiet, looping, ambient and taken left out
        p = S.plan({"SkyChair", "SkyChairDistant", "Hammer"}, {"Hammer": "B_Station"}, ["A_Station", "C"])
        self.assertEqual(p, {"Hammer": "B_Station", "SkyChair": "A_Station"})

    def test_set_clips(self):
        c = S.set_clips(["Forge"])["Forge"]
        self.assertIn("blacksmithforgehammer.hkx", c)
        self.assertIn("blacksmithforgepull.hkx", c)              # joined clips split into their parts

    def test_swap_table(self):
        self.assertNotIn("NPCHumanBlacksmithHammerDistant", S.SWAP)
        self.assertEqual(len(set(S.SWAP.values())), len(S.SWAP))


class LoopTests(unittest.TestCase):
    def test_tile_repeats_and_cuts(self):
        x = np.array([[0.1], [0.2], [0.3]], np.float32)
        t = S.tile(x, 10, 0.8)
        self.assertEqual(t.shape, (8, 1))
        np.testing.assert_allclose(t[:, 0], [0.1, 0.2, 0.3, 0.1, 0.2, 0.3, 0.1, 0.2])
        self.assertEqual(len(S.tile(x, 10, 0.2)), 2)
        self.assertEqual(len(S.tile(x[:0], 10, 1.0)), 0)

    def test_grindstone_loops_cover_the_spin(self):
        import furniture_anim_pack as FP
        for _t, _rel, snd in FP.OBJECT_SOUNDS["blacksmithsharpeningwheelspin.hkx"]:
            self.assertAlmostEqual(S.LOOPS[snd], 274 / 30, places=3)


class TemplateFoleyTests(unittest.TestCase):
    def test_foley_of_our_template_folders(self):
        import furniture_anim_pack as FP
        tpl = FP.SETS["Tanning"][1].lower()
        files = {tpl + "\\idle.afx": b"<audios><audio><frame>3</frame><foley>NPC_Wipe_Wall</foley></audio></audios>",
                 tpl + "\\exittostand.afx": b"<audio><foley> NPC_Wipe_Stop </foley></audio>",
                 "meshes\\actors\\human\\animations\\furniture\\other\\idle.afx":
                     b"<foley>NPC_Not_Ours</foley>",
                 tpl + "\\idle.af": b"<foley>Binary</foley>"}
        got = S.template_foley(list(files), files.get)
        self.assertEqual(sorted(got), ["NPC_Wipe_Stop", "NPC_Wipe_Wall"])
        self.assertEqual(S.template_foley(list(files), files.get, sets=["Sit"]), {})


if __name__ == "__main__":
    unittest.main()
