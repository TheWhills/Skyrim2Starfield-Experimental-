"""Texture size caps: textures.cap_dds drops top mip levels of a block-compressed DDS, the converter applies a cap per
texture kind and logs full and written sizes, and convert_batch --max-texture reaches the converter, the checkpoint
signature and texture_log.json (synthetic DDS files only)."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
from fo4sf import pipeline, textures  # noqa: E402

spec = importlib.util.spec_from_file_location("convert_batch_cap", root / "scripts" / "convert_batch.py")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


def read(path):
    with open(path, "rb") as f:
        return f.read()


def level_bytes(w, h, bb):
    return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * bb


def bc_dds(w, h, dxgi=71, bb=8, mips=None, legacy=None, array=1):
    """A DX10 (or legacy FourCC) DDS whose level i is filled with byte i + 1, so dropped levels are recognisable."""
    n = mips or (max(w, h).bit_length())
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | (0x20000 if n > 1 else 0)
    caps = 0x1000 | (0x400008 if n > 1 else 0)
    hdr = b"DDS " + struct.pack("<7I", 124, flags, h, w, level_bytes(w, h, bb), 0, n) + b"\0" * 44
    if legacy:
        hdr += struct.pack("<II4sIIIII", 32, 0x4, legacy, 0, 0, 0, 0, 0)
        hdr += struct.pack("<5I", caps, 0, 0, 0, 0)
    else:
        hdr += struct.pack("<II4sIIIII", 32, 0x4, b"DX10", 0, 0, 0, 0, 0)
        hdr += struct.pack("<5I", caps, 0, 0, 0, 0)
        hdr += struct.pack("<5I", dxgi, 3, 0, array, 0)
    body = b"".join(bytes([i + 1]) * level_bytes(max(1, w >> i), max(1, h >> i), bb) for i in range(n))
    return hdr + body * array


class CapDdsTests(unittest.TestCase):
    def test_drops_levels_until_it_fits(self):
        data = bc_dds(64, 32)                                    # BC1: 7 levels 64x32 .. 1x1
        out, info = textures.cap_dds(data, 16)
        h = textures.read_dds_header(out)
        self.assertEqual((h["width"], h["height"], h["mips"]), (16, 8, 5))
        self.assertTrue(info["capped"])
        self.assertEqual(info["dropped"], 2)
        self.assertEqual(out[148:149], bytes([3]))              # the old level 2 is the new top level
        self.assertEqual(out[148:], data[148 + level_bytes(64, 32, 8) + level_bytes(32, 16, 8):])
        self.assertEqual(struct.unpack_from("<I", out, 20)[0], level_bytes(16, 8, 8))
        self.assertEqual(info["bytes"], len(data))
        self.assertEqual(info["out_bytes"], len(out))
        again, info2 = textures.cap_dds(out, 16)                 # idempotent
        self.assertEqual(again, out)
        self.assertFalse(info2["capped"])

    def test_bc5_and_legacy_fourcc(self):
        out, info = textures.cap_dds(bc_dds(32, 32, dxgi=83, bb=16), 8)
        self.assertEqual((info["out_width"], info["out_mips"]), (8, 4))
        self.assertEqual(len(out), 148 + sum(level_bytes(8 >> i, 8 >> i, 16) for i in range(4)))
        out, info = textures.cap_dds(bc_dds(32, 32, bb=8, legacy=b"DXT1"), 16)
        self.assertEqual(textures.read_dds_header(out)["width"], 16)
        self.assertEqual(len(out), 128 + sum(level_bytes(16 >> i, 16 >> i, 8) for i in range(5)))

    def test_last_level_clears_the_mip_flags(self):
        out, info = textures.cap_dds(bc_dds(8, 8, mips=2), 4)
        self.assertEqual(info["out_mips"], 1)
        self.assertFalse(struct.unpack_from("<I", out, 8)[0] & 0x20000)
        self.assertFalse(struct.unpack_from("<I", out, 108)[0] & 0x400000)

    def test_left_alone(self):
        for data, cap, why in ((bc_dds(16, 16), 16, "fits"), (bc_dds(16, 16), 0, "fits"),
                               (bc_dds(16, 16, mips=1), 8, "no smaller mip level"),
                               (bc_dds(16, 16, dxgi=28), 8, "not block-compressed"),
                               (bc_dds(16, 16, array=2), 8, "not a single 2-D texture"),
                               (bc_dds(16, 16) + b"x", 8, "does not match"), (b"PNG", 8, "not a DDS")):
            out, info = textures.cap_dds(data, cap)
            self.assertEqual(out, data)
            self.assertFalse(info["capped"])
            self.assertIn(why, info["reason"])

    def test_parse_caps(self):
        self.assertEqual(textures.parse_texture_caps(""), {})
        self.assertEqual(textures.parse_texture_caps("512"), {k: 512 for k in textures.TEXTURE_KINDS})
        self.assertEqual(textures.parse_texture_caps("color=1024,normal=512"), {"color": 1024, "normal": 512})
        for bad in ("color=0", "albedo=512", "color:512", "-4"):
            with self.assertRaises(ValueError):
                textures.parse_texture_caps(bad)


class ConverterCapTests(unittest.TestCase):
    def converter(self, staging, caps):
        conv = pipeline.Converter.__new__(pipeline.Converter)    # no texconv, no templates
        conv.staging = staging
        conv.texture_caps = textures.parse_texture_caps(caps)
        conv.texture_log = {}
        return conv

    def test_cap_per_kind_and_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "in.dds")
            with open(src, "wb") as f:
                f.write(bc_dds(64, 64))
            conv = self.converter(tmp, "color=32,rough=16")
            for kind in ("color", "rough", "normal"):
                dst = os.path.join(tmp, "textures", "p", f"x_{kind}.dds")
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                conv._publish_texture(src, dst, kind)
            widths = {k: textures.read_dds_header(read(os.path.join(tmp, "textures", "p", f"x_{k}.dds")))["width"]
                      for k in ("color", "rough", "normal")}
            self.assertEqual(widths, {"color": 32, "rough": 16, "normal": 64})      # normal: no cap for its kind
            log = conv.texture_log
            self.assertEqual(sorted(log), ["textures/p/x_color.dds", "textures/p/x_normal.dds", "textures/p/x_rough.dds"])
            self.assertTrue(log["textures/p/x_color.dds"]["capped"])
            self.assertFalse(log["textures/p/x_normal.dds"]["capped"])
            self.assertEqual(log["textures/p/x_rough.dds"]["bytes"], len(bc_dds(64, 64)))

    def test_no_cap_copies_unchanged_without_a_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "in.dds")
            with open(src, "wb") as f:
                f.write(bc_dds(64, 64))
            conv = self.converter(tmp, "")
            dst = os.path.join(tmp, "out.dds")
            conv._publish_texture(src, dst, "color")
            self.assertEqual(read(dst), bc_dds(64, 64))
            self.assertEqual(conv.texture_log, {})


class BatchCapTests(unittest.TestCase):
    def run_batch(self, tmp, extra, log=None):
        staging = Path(tmp) / "staging"
        collision = Path(tmp) / "collision.nif"
        collision.write_bytes(b"synthetic")
        cell = Path(tmp) / "cell.json"
        cell.write_text(json.dumps({"refs": [{"model": "a\\chair.nif", "type": "Static"}]}))
        seen = {}

        def converter(*args, **kw):
            seen.update(kw)
            return SimpleNamespace(stats={}, material_errors={}, texture_log=dict(log or {}), convert_nif=lambda name: {
                "ok": True, "out_name": "fo4port/a/chair", "shapes": 1, "fallback_materials": 0})
        argv = ["convert_batch.py", "--fo4-data", "unused", "--staging", str(staging), "--content-resources", "unused",
                "--texconv", "unused", "--collision-template", str(collision), "--cell-json", str(cell)] + extra
        with patch.object(sys, "argv", argv), \
                patch.object(batch.pipeline, "Fo4Archives", return_value=SimpleNamespace()), \
                patch.object(batch.pipeline, "Converter", side_effect=converter), \
                patch.object(batch.convert_static, "collision_template_from_nif", return_value=b"template"), \
                patch("builtins.print"):
            batch.main()
        return seen, json.loads((staging / "manifest.json").read_text()), staging

    def test_cap_reaches_the_converter_and_the_log_is_kept_across_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = {"textures/a_color.dds": {"capped": True, "bytes": 100, "out_bytes": 30}}
            seen, manifest, staging = self.run_batch(tmp, ["--max-texture", "color=512"], first)
            self.assertEqual(seen["max_texture"], "color=512")
            self.assertEqual(manifest["stats"]["textures"],
                             {"textures": 1, "capped": 1, "full_bytes": 100, "written_bytes": 30, "caps": {"color": 512}})
            second = {"textures/b_rough.dds": {"capped": False, "bytes": 10, "out_bytes": 10}}
            _seen, manifest, staging = self.run_batch(tmp, ["--max-texture", "color=512"], second)
            log = json.loads((staging / "texture_log.json").read_text())
            self.assertEqual(sorted(log), ["textures/a_color.dds", "textures/b_rough.dds"])
            self.assertEqual(manifest["stats"]["textures"]["full_bytes"], 110)

    def test_no_cap_writes_no_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen, manifest, staging = self.run_batch(tmp, [])
            self.assertEqual(seen["max_texture"], "")
            self.assertNotIn("textures", manifest["stats"])
            self.assertFalse((staging / "texture_log.json").exists())

    def test_bad_cap_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                self.run_batch(tmp, ["--max-texture", "albedo=512"])

    def test_signature_names_only_a_set_cap(self):
        a = SimpleNamespace(fo4_data="", starfield_data="", texconv="t", content_resources="c", collision_template="x",
                            prefix="fo4port", max_texture="")
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(batch.checkpoints, "digest", return_value="d"), \
                patch.object(batch.checkpoints, "archive_identity", return_value={}):
            a.fo4_data = tmp
            self.assertNotIn("max_texture", batch.checkpoint_signature(a))
            a.max_texture = "1024"
            self.assertEqual(batch.checkpoint_signature(a)["max_texture"], {k: 1024 for k in textures.TEXTURE_KINDS})


if __name__ == "__main__":
    unittest.main()
