"""scripts/interior/sf_imagespace.py on a synthetic BETH reflection blob laid out like the vanilla IMGS ones (no game
data): classes from CLAS, the OBJT walked field by field, enums as strings, a user-serialised class skipped."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))
import sf_imagespace as SI  # noqa: E402

BOOL, FLOAT, ENUM, STRING = 0xFFFFFF10, 0xFFFFFF11, 0xFFFFFF02, 0xFFFFFF01


def blob():
    names = ["TESImageSpace", "Settings", "ImageSpaceSettings", "Exposure", "ExposureSettings", "CameraExposureMode",
             "FixedValue", "BSBlendable::FloatValue", "Op", "Value", "BlendAmount", "Curve", "BSFloatCurve",
             "Lut", "Override"]
    strt, off = b"", {}
    for n in names:
        off[n] = len(strt)
        strt += n.encode() + b"\0"

    def clas(name, flags, fields):
        body = struct.pack("<IIHH", off[name], 0, flags, len(fields))
        body += b"".join(struct.pack("<IIHH", off[f], t if isinstance(t, int) else off[t], 0, 0) for f, t in fields)
        return b"CLAS" + struct.pack("<I", len(body)) + body
    cl = [clas("TESImageSpace", 0, [("Settings", "ImageSpaceSettings")]),
          clas("ImageSpaceSettings", 0, [("Exposure", "ExposureSettings"), ("Override", BOOL), ("Lut", STRING)]),
          clas("ExposureSettings", 0, [("CameraExposureMode", ENUM), ("Curve", "BSFloatCurve"),
                                       ("FixedValue", "BSBlendable::FloatValue")]),
          clas("BSBlendable::FloatValue", 0, [("Op", ENUM), ("Value", FLOAT), ("BlendAmount", FLOAT)]),
          clas("BSFloatCurve", 0xC, [("Value", FLOAT)])]

    def s(x):
        x = x.encode() + b"\0"
        return struct.pack("<H", len(x)) + x
    objt = struct.pack("<I", off["TESImageSpace"]) + s("EXPOSURE_MODE_FIXED") + s("Replace") + \
        struct.pack("<ff", 5.0, 1.0) + b"\x01" + s("Effects\\LUTs\\ColorLUT.dds")
    chunks = [b"STRT" + struct.pack("<I", len(strt)) + strt, b"TYPE" + struct.pack("<II", 4, len(cl))] + cl + \
        [b"OBJT" + struct.pack("<I", len(objt)) + objt]
    return b"BETH" + struct.pack("<III", 8, 4, len(chunks)) + b"".join(chunks)


class DecodeTest(unittest.TestCase):
    def test_walks_the_object(self):
        root, val, used, size = SI.decode(blob())
        self.assertEqual(root, "TESImageSpace")
        self.assertEqual(used, size)                                  # every byte accounted for
        f = dict(SI.flat(val))
        self.assertEqual(f["Settings.Exposure.CameraExposureMode"], "EXPOSURE_MODE_FIXED")
        self.assertEqual(f["Settings.Exposure.FixedValue.Value"], 5.0)
        self.assertIsNone(f["Settings.Exposure.Curve"])               # user-serialised: not in OBJT
        self.assertIs(f["Settings.Override"], True)
        self.assertEqual(f["Settings.Lut"], "Effects\\LUTs\\ColorLUT.dds")

    def test_not_a_blob(self):
        with self.assertRaises(ValueError):
            SI.decode(b"nope" + bytes(20))


if __name__ == "__main__":
    unittest.main()


class PatchTest(unittest.TestCase):
    def test_enum_length_and_float(self):
        out = SI.patch(blob(), {"Settings.Exposure.CameraExposureMode": "EXPOSURE_MODE_AUTO",
                                "Settings.Exposure.FixedValue.Value": 3.5})
        root, val, used, size = SI.decode(out)
        self.assertEqual(used, size)
        f = dict(SI.flat(val))
        self.assertEqual(f["Settings.Exposure.CameraExposureMode"], "EXPOSURE_MODE_AUTO")
        self.assertEqual(f["Settings.Exposure.FixedValue.Value"], 3.5)
        self.assertEqual(f["Settings.Lut"], "Effects\\LUTs\\ColorLUT.dds")         # the rest untouched
        self.assertEqual(len(out), len(blob()) - 1)                                 # FIXED -> AUTO: one byte shorter
        with self.assertRaises(KeyError):
            SI.patch(blob(), {"Settings.Nope": 1.0})


class UserPatchTest(unittest.TestCase):
    def test_user_object_field(self):
        b = blob()
        cs = SI.chunks(b)
        name, _classes = SI.schema(cs)
        strt = next(c for t, c in cs if t == "STRT")
        curve = strt.index(b"BSFloatCurve\0")
        user = struct.pack("<II", curve, curve) + struct.pack("<f", 2.0)
        cs.append(("USER", user))
        out = b[:12] + struct.pack("<I", len(cs))
        for t, c in cs:
            out += t.encode() + struct.pack("<I", len(c)) + c
        new = SI.patch(out, {"USER:BSFloatCurve.Value": -3.0})
        u = [c for t, c in SI.chunks(new) if t == "USER"][0]
        self.assertEqual(struct.unpack_from("<f", u, 8)[0], -3.0)
        self.assertEqual(SI.decode(new)[1], SI.decode(out)[1])          # the object itself untouched
        with self.assertRaises(KeyError):
            SI.patch(out, {"USER:Nope.Value": 1.0})


class ListPatchTest(unittest.TestCase):
    def test_every_entry_of_a_list(self):
        b = blob()
        cs = SI.chunks(b)
        strt = next(c for t, c in cs if t == "STRT")
        # add a class BSFloatCurve::Control (Input, Value) and a LIST of two controls
        extra = b"BSFloatCurve::Control\0Input\0"
        base = len(strt)
        strt2 = strt + extra
        ctrl, inp = base, base + len("BSFloatCurve::Control") + 1
        val = strt.index(b"Value\0")
        clas = struct.pack("<IIHH", ctrl, 0, 0, 2) + struct.pack("<IIHH", inp, 0xFFFFFF11, 0, 4) + \
            struct.pack("<IIHH", val, 0xFFFFFF11, 4, 4)
        lst = struct.pack("<II", ctrl, 2) + struct.pack("<4f", -3.0, 0.5, 11.0, 0.5)
        out_chunks = [("STRT" if t == "STRT" else t, strt2 if t == "STRT" else c) for t, c in cs]
        out_chunks.insert(2, ("CLAS", clas))
        out_chunks.append(("LIST", lst))
        data = b[:12] + struct.pack("<I", len(out_chunks))
        for t, c in out_chunks:
            data += t.encode() + struct.pack("<I", len(c)) + c
        new = SI.patch(data, {"LIST:BSFloatCurve::Control.Value": -2.0})
        L = [c for t, c in SI.chunks(new) if t == "LIST"][0]
        self.assertEqual(struct.unpack_from("<4f", L, 8), (-3.0, -2.0, 11.0, -2.0))
        with self.assertRaises(KeyError):
            SI.patch(data, {"LIST:Nope.Value": 1.0})


class SkyrimGradingTest(unittest.TestCase):
    def test_most_used_image_space_and_changes(self):
        import make_skyrim_interior as MSI
        exports = [{"lighting": {"image_space": "059B60:Skyrim.esm"}}] * 2 + [{"lighting": {"image_space": "000100:Skyrim.esm"}},
                                                                           {"lighting": {}}]
        ims = {0x059B60: {"editor_id": "FarmInteriorIS", "cinematic": {"saturation": 1.05, "brightness": 1.15,
                                                                         "contrast": 1.2},
                          "tint": [0.05, 0.627, 0.392, 0.039]}, 0x000100: {"editor_id": "Other"}}
        g = MSI.skyrim_grading(exports, ims)
        self.assertEqual((g["editor_id"], g["formkey"]), ("FarmInteriorIS", "059B60:Skyrim.esm"))
        ch = MSI.grading_changes(g)
        self.assertEqual(ch["Settings.Cinematic.Contrast.Value"], 1.2)
        self.assertEqual(ch["Settings.Cinematic.Saturation.Value"], 1.05)
        self.assertEqual(ch["Settings.Cinematic.TintColorValue.Value.w"], 0.05)
        self.assertEqual(ch["Settings.Cinematic.TintColorValue.Value.x"], 0.627)
        self.assertNotIn("Settings.Cinematic.Brightness.Value", ch)
        self.assertEqual(MSI.grading_changes({}), {})
        self.assertEqual(MSI.skyrim_grading([{"lighting": {}}], ims), {})

    def test_grading_off_by_default(self):
        import make_skyrim_interior as MSI
        self.assertFalse(MSI.parser().parse_args(["batch"]).skyrim_grading)
        self.assertTrue(MSI.parser().parse_args(["batch", "--skyrim-grading"]).skyrim_grading)

    def test_darker_defaults(self):
        # owner 2026-11-21 17:18 "darken it a bit", the earlier build "felt more real": metering 90 .. 97 %, ambient 35
        import make_skyrim_interior as MSI
        from fo4sf import lightmodel
        a = MSI.parser().parse_args(["batch"])
        self.assertEqual((a.meter_darks, a.meter_brights), (90.0, 3.0))
        self.assertEqual(lightmodel.ENV_AMBIENT_SCALE, 35.0)
        ps = open(os.path.join(ROOT, "tools", "owner", "riverwood_doors.ps1"), encoding="utf-8").read()
        for line in ("[double]$AmbientScale = 35,", "[double]$MeterDarks = 90,", "[double]$MeterBrights = 3,"):
            self.assertIn(line, ps)


class AdaptImageSpaceTest(unittest.TestCase):
    """2026-11-21: Skyrim adapts per view; --exposure auto writes LGT_NoLut with Starfield's auto exposure."""

    def test_written_and_removed(self):
        import tempfile
        from types import SimpleNamespace
        from unittest import mock
        import make_skyrim_interior as MSI
        seen = {}
        with tempfile.TemporaryDirectory() as work, \
                mock.patch.object(SI, "read_imgs", lambda esm, fid: seen.setdefault("fid", fid) and blob()), \
                mock.patch.object(SI, "patch", lambda data, ch: seen.setdefault("changes", ch) and b"BLOB"):
            a = SimpleNamespace(exposure="auto", starfield_esm="Starfield.esm", exposure_min=3.0, exposure_max=6.5,
                                exposure_compensation=-3.0)
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(MSI.write_adapt_imagespace(work, a), b"BLOB")
            path = os.path.join(work, "convert", MSI.ADAPT_IMAGESPACE)
            self.assertTrue(os.path.exists(path))
            self.assertEqual(seen["fid"], 0x000167)
            self.assertEqual(seen["changes"]["Settings.Exposure.CameraExposureMode"], "EXPOSURE_MODE_AUTO")
            self.assertEqual(seen["changes"]["Settings.Exposure.AutoExposure.ExposureMin.Value"], 3.0)
            self.assertEqual(seen["changes"]["USER:BSFloatCurve.DefaultValue"], -3.0)
            self.assertEqual(seen["changes"]["LIST:BSFloatCurve::Control.Value"], -3.0)
            self.assertIs(seen["changes"]["Settings.OverrideToneMapping"], False)
            self.assertEqual(seen["changes"]["Settings.Cinematic.Brightness.Value"], 1.0)
            self.assertEqual(seen["changes"][
                "Settings.Exposure.AutoExposure.LuminanceHistogram.IgnoredDarksPercentile.Value"], 20.0)
            self.assertIsNone(MSI.write_adapt_imagespace(work, SimpleNamespace(exposure="fixed", starfield_esm="x")))
            self.assertFalse(os.path.exists(path))

    def test_pluginspike_and_script(self):
        with open(os.path.join(ROOT, "dotnet", "PluginSpike", "Program.cs"), encoding="utf-8") as fh:
            cs = fh.read()
        self.assertIn('Path.Combine(outDir, "imagespace_skyrim_adapt.bin")', cs)
        self.assertIn("if (adaptIs is FormKey aIs && Setting(src4, \"ADAPT_IS\", \"1\") != \"0\") cell.ImageSpace.SetTo(aIs);", cs)
        with open(os.path.join(ROOT, "tools", "owner", "riverwood_doors.ps1"), encoding="utf-8") as fh:
            ps = fh.read()
        self.assertIn('[ValidateSet("auto", "fixed")][string]$Exposure = "auto"', ps)
        self.assertIn('"--starfield-esm"', ps)
        self.assertIn('"--exposure-compensation"', ps)
        self.assertIn('"--exposure-brightness"', ps)
        self.assertIn('"--meter-darks"', ps)
        with open(os.path.join(ROOT, "scripts", "interior", "make_skyrim_interior.py"), encoding="utf-8") as fh:
            py = fh.read()
        self.assertIn('cell["light_scale"] = 1.0', py)
