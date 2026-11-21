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
