"""scripts/npc/skyrim_hairs.py: Skyrim hair head parts read across plugins, chosen, and exported as Starfield looks-menu
hairstyles, on synthetic games only."""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import nif, sfnif, sfplugin, smpcloth  # noqa: E402
import skyrim_fixtures as F  # noqa: E402
from test_smpcloth import hair_nif_bytes, template_root  # noqa: E402
import skyrim_hairs as SH  # noqa: E402

INFO = {"hedr_version": 1.7, "form_version": 44}


def hdpt(edid, model, kind, flags, extra=(), races=None):
    subs = [(b"EDID", edid.encode() + b"\0"), (b"MODL", model.encode() + b"\0"), (b"DATA", bytes([flags])),
            (b"PNAM", struct.pack("<I", kind))]
    subs += [(b"HNAM", struct.pack("<I", x)) for x in extra]
    if races is not None:
        subs.append((b"RNAM", struct.pack("<I", races)))
    return subs


def rec(t, subs, fid):
    return (t, struct.pack("<4sIII", t, 0, 0, 0) + bytes(4) + struct.pack("<HH", 44, 0), subs, fid)


def skyrim_esms(d):
    """Skyrim.esm: a woman's hair with a hairline extra part, a man's hair, a Khajiit hair, a beard; Dawnguard.esm:
    a hair whose extra part is Skyrim.esm's hairline."""
    sky = [rec(b"FLST", [(b"EDID", b"HeadPartsHumansandVampires\0")], 0x000A0001),
           rec(b"FLST", [(b"EDID", b"HeadPartsKhajiitandVampire\0")], 0x000A0002),
           rec(b"HDPT", hdpt("HairLineFemaleNord01", "Actors\\Character\\Hair\\HairLineF01.nif", 3, 0x0C), 0x000B0001),
           rec(b"HDPT", hdpt("HairFemaleNord01", "Actors\\Character\\Hair\\HairF01.nif", 3, 0x05, [0x000B0001],
                             0x000A0001), 0x000B0002),
           rec(b"HDPT", hdpt("HairMaleNord01", "Actors\\Character\\Hair\\HairM01.nif", 3, 0x03, (), 0x000A0001),
               0x000B0003),
           rec(b"HDPT", hdpt("HairKhajiitFemale01", "Actors\\Character\\Hair\\HairKF01.nif", 3, 0x05, (),
                             0x000A0002), 0x000B0004),
           rec(b"HDPT", hdpt("BeardNord01", "Actors\\Character\\Hair\\Beard01.nif", 4, 0x03, (), 0x000A0001),
               0x000B0005)]
    with open(os.path.join(d, "Skyrim.esm"), "wb") as fh:
        fh.write(sfplugin.build(sky, INFO, masters=()))
    dg = [rec(b"HDPT", hdpt("HairFemaleSerana", "DLC01\\Hair\\Serana.nif", 3, 0x04, [0x000B0001], 0x000A0001),
              0x01000801)]
    with open(os.path.join(d, "Dawnguard.esm"), "wb") as fh:
        fh.write(sfplugin.build(dg, INFO, masters=("Skyrim.esm",)))


class PartTests(unittest.TestCase):
    def test_strand_copies(self):
        self.assertEqual(SH.strand_copies(""), SH.STRANDS)
        self.assertEqual([k for k, _l in SH.strand_copies("thin, strandsedge")], ["strandsthin", "strandsedge"])
        self.assertEqual([k for k, _l in SH.strand_copies("strands")], ["strands"])
        with self.assertRaises(SystemExit):
            SH.strand_copies("curly")

    def test_hairline_shapes_are_the_blended_ones(self):
        from fo4sf import skyrimhair
        shapes = [skyrimhair.HairShape(b"S%d" % i, np.zeros((1, 3)), None, None, [], [], [], -1, ref, 0)
                  for i, ref in enumerate((-1, 4, 5))]
        hair = skyrimhair.Hair(shapes, [], None, {})
        with mock.patch.object(SH.skyrimnif, "alpha_test",
                               lambda n, ref: (True, ref == 5, 128)):
            self.assertEqual(SH.hairline_shapes([None] * 3, hair), [2])

    def test_load_choose_and_merge_across_plugins(self):
        with tempfile.TemporaryDirectory() as d:
            skyrim_esms(d)
            self.assertEqual(SH.plugin_masters(os.path.join(d, "Dawnguard.esm")), ["skyrim.esm"])
            parts, lists = SH.load_parts(d)
        by = {p["edid"]: p for p in parts.values()}
        serana = by["HairFemaleSerana"]
        self.assertEqual(serana["key"], ("dawnguard.esm", 0x801))
        self.assertEqual(serana["extra_parts"], [("skyrim.esm", 0xB0001)])        # resolved through its master
        self.assertEqual(SH.part_models(serana["key"], parts),
                         ["DLC01\\Hair\\Serana.nif", "Actors\\Character\\Hair\\HairLineF01.nif"])
        chosen = sorted(p["edid"] for p in parts.values() if SH.wanted(p, lists))
        self.assertEqual(chosen, ["HairFemaleNord01", "HairFemaleSerana", "HairMaleNord01"])   # no extra / beast
        self.assertIn("BeardNord01", [p["edid"] for p in parts.values()
                                      if SH.wanted(p, lists, (SH.HAIR, SH.FACIAL_HAIR))])
        self.assertEqual(sorted(p["edid"] for p in parts.values() if SH.wanted(p, lists, playable_only=True)),
                         ["HairFemaleNord01", "HairMaleNord01"])                 # Serana's is not playable
        self.assertTrue(SH.is_female(by["HairFemaleNord01"]))
        self.assertFalse(SH.is_female(by["HairMaleNord01"]))
        self.assertFalse(SH.is_female(by["BeardNord01"]))
        self.assertTrue(SH.is_female({"type": 3, "flags": 0, "edid": "HairFemaleOdd"}))
        self.assertFalse(SH.is_female({"type": 3, "flags": 0, "edid": "HairMaleOdd"}))


class StrandAxisTests(unittest.TestCase):
    def card(self, along_u):
        """A hanging card 1 cm wide, 10 cm long; strands run along U or V in its texture."""
        from fo4sf import skyrimhair
        p = np.array([[0, 0, 1.6], [0.01, 0, 1.6], [0, 0, 1.5], [0.01, 0, 1.5]])
        uv = [(0, 0), (0, 1), (1, 0), (1, 1)] if along_u else [(0, 0), (1, 0), (0, 1), (1, 1)]
        return skyrimhair.HairShape(b"C", p, np.array([[0, -1.0, 0]] * 4), np.zeros((4, 3)), uv,
                                    [(0, 2, 1), (1, 2, 3)], [[("C_Head", 1.0)]] * 4, 3, -1, 0)

    def test_strands_turned_to_run_down_the_texture(self):
        from fo4sf import skyrimhair
        across, down = self.card(True), self.card(False)
        self.assertEqual(skyrimhair.strand_axis(across), "u")
        self.assertEqual(skyrimhair.strand_axis(down), "v")
        out, flags = skyrimhair.strands_down(skyrimhair.Hair([across, down], [], {}, {}))
        self.assertEqual(flags, [True, False])
        self.assertEqual(skyrimhair.strand_axis(out.shapes[0]), "v")              # now down the texture
        self.assertEqual(out.shapes[0].uvs, [(v, u) for u, v in across.uvs])
        self.assertIs(out.shapes[1], down)
        flat = skyrimhair.HairShape(b"F", np.array([[0, 0, 1.7], [0.1, 0, 1.7], [0, 0.1, 1.7]]), None, None,
                                    [(0, 0), (1, 0), (0, 1)], [(0, 1, 2)], [[("C_Head", 1.0)]] * 3, -1, -1, 0)
        self.assertIsNone(skyrimhair.strand_axis(flat))                          # lying flat: cannot tell

    def test_transposed_texture(self):
        import shutil
        from fo4sf import pipeline, skyrimconvert, textures

        def fake_texconv(exe, src, out_dir, fmt, extra=()):
            dst = os.path.join(out_dir, os.path.basename(src))
            if os.path.abspath(dst) != os.path.abspath(src):
                shutil.copy2(src, dst)
        px = np.zeros((4, 8, 4), np.uint8)                       # 8 wide, 4 tall; alpha rises along U
        px[..., :3] = 120
        px[..., 3] = np.arange(8, dtype=np.uint8)[None, :] * 30
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.dds")
            textures.write_dds_dx10(p, 8, 4, textures.DXGI_R8G8B8A8_UNORM, px.tobytes(), 4)
            raw = open(p, "rb").read()
            conv = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
            conv._materials, conv.stats, conv.material_errors = {}, {"materials_ok": 0}, {}
            conv.staging, conv.texconv, conv.prefix, conv.texture_caps = d, "t.exe", "s2s", {}
            conv.src = mock.Mock(texture=lambda name: raw)
            conv._hair_fill = {"AmbientOcclusion": "a", "DepthOffset": "b", "HairID": "c"}
            with mock.patch.object(textures, "texconv", fake_texconv):
                mat = conv.skyrim_hair_material("textures\\h\\t.dds", "", 40, transpose=True)
            self.assertTrue(mat.endswith("t_hair_rot.mat"))
            col = open(os.path.join(d, "textures", "s2s", "h", "t_hair_rot_color.dds"), "rb").read()
            h = textures.read_dds_header(col)
            self.assertEqual((h["width"], h["height"]), (4, 8))                 # turned
            op = open(os.path.join(d, "textures", "s2s", "h", "t_hair_rot_opacity.dds"), "rb").read()
            ho = textures.read_dds_header(op)
            a = np.frombuffer(op[ho["data_offset"]:], np.uint8)[:ho["width"] * ho["height"]]
            a = a.reshape(ho["height"], ho["width"])
            self.assertEqual((ho["width"], ho["height"]), (4, 8))              # turned too
            self.assertGreater(a[-2:, :].mean(), a[:2, :].mean())              # the old U now runs down


def mixed_strand_texture(h=64, w=128):
    """RGBA hair texture: the left half's strands run down it (alpha varies along U), the right half's across it
    (alpha varies along V) - a vanilla Skyrim atlas holding both layouts."""
    rng = np.random.default_rng(3)
    px = np.zeros((h, w, 4), np.uint8)
    cols = (rng.random(w) * 255).astype(np.uint8)
    rows = (rng.random(h) * 255).astype(np.uint8)
    px[:, :w // 2, 3] = cols[None, :w // 2]
    px[:, w // 2:, 3] = rows[:, None]
    px[..., :3] = 100
    return px


class StrandOrientationTests(unittest.TestCase):
    def test_regions_read_from_the_texture(self):
        from fo4sf import pipeline
        px = mixed_strand_texture()
        m = pipeline.strand_orientation(px[..., 3], px, block=16)
        self.assertEqual(m.shape, (64, 128))
        self.assertLess(m[:, :64].mean(), 0.05)                     # strands down: V
        self.assertGreater(m[:, 64:].mean(), 0.95)                  # strands across: U
        flat = np.full((32, 32), 200, np.uint8)
        self.assertFalse(pipeline.strand_orientation(flat, block=16).any())   # undecided: V

    def test_strands_cut_along_each_region(self):
        from fo4sf import pipeline
        px = mixed_strand_texture()
        px[..., 3] = 200                                           # full: the cut alone shows the direction
        across = np.zeros((64, 128), bool)
        across[:, 64:] = True
        op, hid = pipeline.strand_maps(px[..., 3], across=across)
        self.assertEqual(op.shape, (128, 256))
        left, right = op[:, :128].astype(float), op[:, 128:].astype(float)
        # down the texture a column keeps its value longer than a row does, and the other way round across it
        self.assertLess(np.abs(np.diff(left, axis=0)).mean(), np.abs(np.diff(left, axis=1)).mean())
        self.assertLess(np.abs(np.diff(right, axis=1)).mean(), np.abs(np.diff(right, axis=0)).mean())
        idr = hid[:, 128:].astype(float)
        self.assertEqual(np.abs(np.diff(idr, axis=1)).max(), 0)    # one HairID per row there

    def test_flatten_turns_its_window(self):
        from fo4sf import pipeline
        px = np.zeros((128, 128, 4), np.uint8)
        px[..., 3] = 255
        band = np.where((np.arange(128) // 32) % 2 == 0, 60, 180).astype(np.uint8)
        px[:, :64, :3] = band[:, None, None]                   # painted bands along V (left: strands down)
        px[:, 64:, :3] = band[None, 64:, None]                 # and along U (right: strands across)
        across = np.zeros((128, 128), bool)
        across[:, 64:] = True
        out = pipeline.flatten_albedo(px, across=across)
        self.assertLess(out[:, :64, 0].astype(float).std(), 0.5 * band.std())
        self.assertLess(out[:, 72:120, 0].astype(float).std(), 0.5 * band.std())

    def test_cards_sampled_and_lit_along_their_strands(self):
        from fo4sf import skyrimhair
        p = np.array([[0, 0, 1.6], [0.01, 0, 1.6], [0, 0, 1.5], [0.01, 0, 1.5]])
        n = np.array([[0, -1.0, 0]] * 4)
        tri = [(0, 2, 1), (1, 2, 3)]
        left = skyrimhair.HairShape(b"L", p, n, np.zeros((4, 3)), [(0, 0), (0.4, 0), (0, 1), (0.4, 1)], tri,
                                    [[("C_Head", 1.0)]] * 4, 3, -1, 0)
        right = skyrimhair.HairShape(b"R", p + [0.05, 0, 0], n, np.zeros((4, 3)),
                                     [(0.6, 0), (1.0, 0), (0.6, 1), (1.0, 1)], tri, [[("C_Head", 1.0)]] * 4, 3, -1, 0)
        across = np.zeros((64, 128), bool)
        across[:, 64:] = True
        a_l, a_r = skyrimhair.strands_across(left, across), skyrimhair.strands_across(right, across)
        self.assertFalse(a_l.any())
        self.assertTrue(a_r.all())
        self.assertFalse(skyrimhair.strands_across(right, None).any())
        out, rep = skyrimhair.uv_tangents(skyrimhair.Hair([left, right], [], {}, {}), along_v=[a_l, a_r])
        self.assertEqual(rep["along_v"], 4)
        self.assertAlmostEqual(abs(out.shapes[0].tangents[0][0]), 1.0, 5)     # dP/du: across the card (x)
        self.assertAlmostEqual(abs(out.shapes[1].tangents[0][2]), 1.0, 5)     # dP/dv: down the card (z)

    def test_material_keeps_its_map(self):
        import shutil
        from fo4sf import skyrimconvert, textures

        def fake_texconv(exe, src, out_dir, fmt, extra=()):
            dst = os.path.join(out_dir, os.path.basename(src))
            if os.path.abspath(dst) != os.path.abspath(src):
                shutil.copy2(src, dst)
        px = mixed_strand_texture()
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.dds")
            textures.write_dds_dx10(p, 128, 64, textures.DXGI_R8G8B8A8_UNORM, px.tobytes(), 4)
            with open(p, "rb") as fh:
                raw = fh.read()
            conv = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
            conv._materials, conv.stats, conv.material_errors = {}, {"materials_ok": 0}, {}
            conv.staging, conv.texconv, conv.prefix, conv.texture_caps = d, "t.exe", "s2s", {}
            conv.src = mock.Mock(texture=lambda name: raw)
            conv._hair_fill = {"AmbientOcclusion": "a", "DepthOffset": "b", "HairID": "c"}
            with mock.patch.object(textures, "texconv", fake_texconv):
                mat = conv.skyrim_hair_material("textures\\h\\t.dds", "", 40, strands=True, orient=True)
                plain = conv.skyrim_hair_material("textures\\h\\t.dds", "", 40, strands=True)
            self.assertTrue(mat.endswith("t_hair_o.mat"))
            m = conv.hair_orientation_of(mat)
            self.assertGreater(m[:, 80:].mean(), 0.9)
            self.assertLess(m[:, :48].mean(), 0.1)
            self.assertIsNone(conv.hair_orientation_of(plain))                # KS's path: no map, as before


class FitTests(unittest.TestCase):
    def test_gaps_by_region(self):
        from fo4sf import skyrimhair
        head = np.eye(4)
        head[:3, 3] = (0, 0, 1.6)
        c = np.array([0, 0, 1.69])
        rng = np.random.default_rng(1)
        d = rng.normal(size=(4000, 3))
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        skull = c + 0.08 * d
        hair = c + np.where(d[:, :1] > 0.75, 0.10, 0.085) * d          # 5 mm over the skull, 20 mm on the right
        g = skyrimhair.fit_gaps(hair, skull, head)
        self.assertAlmostEqual(g["front"]["gap_median_mm"], 5.0, delta=1.5)
        self.assertGreater(g["right"]["gap_p10_mm"], 4.0)
        self.assertGreater(g["right"]["gap_median_mm"], 12.0)
        self.assertLess(g["left"]["gap_median_mm"], 7.0)
        self.assertIsNone(skyrimhair.fit_gaps(hair[:0], skull, head)["top"])
        import types
        sh = skyrimhair.HairShape(b"H", hair, None, None, [(0, 0)] * len(hair), [], [[("C_Head", 1.0)]] * len(hair),
                                  -1, -1, 0)
        h = skyrimhair.Hair([sh], [], {}, {})
        ctx = types.SimpleNamespace(sky_head=skull, head_surface=(skull, d), vanilla_profile=None)
        rep = SH.fit_report(h, h, ctx, {skyrimhair.SF_HEAD: head})
        self.assertEqual(rep["skyrim"], rep["starfield"])


class RegionCoverageTests(unittest.TestCase):
    def test_faint_layer_brought_to_full_in_its_own_region(self):
        from fo4sf import pipeline
        import hair_pack
        from fo4sf import skyrimhair
        a = np.full((64, 64), 230, np.uint8)
        a[:, 32:] = (np.arange(64)[:, None] % 2) * 40              # right half: faint strands (alpha 0 / 40)
        sh = skyrimhair.HairShape(b"L", np.zeros((3, 3)), None, None, [(0.55, 0.1), (0.95, 0.1), (0.75, 0.9)],
                                  [(0, 1, 2)], [[("C_Head", 1.0)]] * 3, 3, 0, 0)
        uv = hair_pack.uv_samples(sh)
        self.assertEqual(uv.shape, (15, 2))
        self.assertTrue((uv[:, 0] >= 0.55).all() and (uv[:, 0] <= 0.95).all())
        out, rep = pipeline.normalize_region_alpha(a, uv)
        self.assertGreater(rep["gain"], 5.0)
        self.assertEqual(int(out[:, 32:].max()), 255)               # the faint strands full
        self.assertEqual(int(out[:, :32].min()), 255)               # (the rest of the atlas clips: own material)
        same, rep2 = pipeline.normalize_region_alpha(np.zeros((8, 8), np.uint8), uv)
        self.assertEqual(rep2["gain"], 1.0)


class HairlineDropAndCutoutTests(unittest.TestCase):
    def test_cutout_draws_what_skyrim_drew(self):
        from fo4sf import pipeline
        a = np.array([[0, 50, 77, 90, 110, 200]], np.uint8)
        out = pipeline.cutout_alpha(a, 77)
        self.assertEqual(out[0, 0], 0)
        self.assertEqual(out[0, 1], 0)                          # well under Skyrim's threshold: not drawn
        self.assertAlmostEqual(int(out[0, 2]), 128, delta=2)     # at it: the strands' ragged ends
        self.assertEqual(out[0, 4], 255)                        # over it: solid, as Skyrim drew it
        self.assertEqual(out[0, 5], 255)

    def test_drop_to_the_symmetric_vanilla_hairline(self):
        from fo4sf import skyrimhair
        angs = skyrimhair.HAIRLINE_ANGLES
        target = {a: 0.098 for a in angs}
        target.update({10: 0.073, 20: 0.047, 30: 0.015})         # the bob's fringe hangs low on one side
        own = {a: 0.115 for a in angs}
        drop = skyrimhair.drop_profile(own, target, 0.02)
        self.assertAlmostEqual(drop[0], -0.017, places=3)
        self.assertAlmostEqual(drop[20], drop[-20], places=6)    # the fringe side not taken as the hairline
        self.assertEqual(drop[70], 0.0)                          # temples left alone
        self.assertTrue(all(v <= 0 for v in drop.values()))
        high = skyrimhair.drop_profile({a: 0.2 for a in angs}, target, 0.02)
        self.assertGreaterEqual(min(high.values()), -0.02 - 1e-9)

    def test_lift_hairline_brings_the_front_down(self):
        from fo4sf import skyrimhair
        head = np.eye(4)
        head[:3, 3] = (0, 0, 1.6)
        rng = np.random.default_rng(2)
        d = rng.normal(size=(3000, 3))
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        c = np.array([0, 0, 1.69])
        skull, nrm = c + 0.08 * d, d
        pts = np.array([[0, 0.085, 1.70], [0, -0.085, 1.70]])     # front of the forehead, back of the head
        sh = skyrimhair.HairShape(b"H", pts, np.array([[0, 1.0, 0], [0, -1.0, 0]]), np.zeros((2, 3)),
                                  [(0, 0)] * 2, [], [[("C_Head", 1.0)]] * 2, -1, -1, 0)
        out = skyrimhair.lift_hairline(skyrimhair.Hair([sh], [], {}, {}), skull, nrm, head,
                                       {a: -0.015 for a in skyrimhair.HAIRLINE_ANGLES})
        p = np.asarray(out.shapes[0].positions)
        self.assertLess(p[0, 2], 1.70 - 0.01)                    # the front came down
        self.assertTrue(np.allclose(p[1], pts[1]))               # the back stayed


class VanillaAlbedoTests(unittest.TestCase):
    def test_brightness_by_rank_onto_vanilla_hair(self):
        from fo4sf import pipeline
        rng = np.random.default_rng(4)
        px = np.zeros((64, 64, 4), np.uint8)
        px[..., :3] = (rng.random((64, 64, 1)) * 200 + 40).astype(np.uint8)   # a light, wide Skyrim albedo
        px[..., 3] = 255
        out = pipeline.vanilla_albedo(px).astype(float)
        lum = out @ [0.2126, 0.7152, 0.0722]
        self.assertAlmostEqual(np.percentile(lum, 50), 21.5, delta=1.5)
        self.assertAlmostEqual(np.percentile(lum, 95), 45.5, delta=3.0)
        src = px[..., 0].astype(float).ravel()
        order = np.argsort(src)
        self.assertTrue(np.all(np.diff(lum.ravel()[order]) >= -1.0))           # the light / dark pattern kept
        self.assertAlmostEqual(out[..., 0].mean() / out[..., 1].mean(), 1.59, delta=0.06)


class CoverageTests(unittest.TestCase):
    def test_blended_fade_and_tested_ramp(self):
        import hair_probe
        from fo4sf import skyrimhair
        alpha = np.tile(np.linspace(255, 0, 8).astype(np.uint8), (8, 1))        # fades out across U
        px = np.zeros((8, 8, 4), np.uint8)
        px[..., 3] = alpha
        uvs = [((k + 0.5) / 8, 0.5) for k in range(8)]
        sh = skyrimhair.HairShape(b"L", np.zeros((8, 3)), None, None, uvs, [(0, 1, 2)], [[("C_Head", 1.0)]] * 8,
                                  0, 1, 0)
        conv = mock.Mock(texconv="t.exe")
        conv.__dict__["_alpha_cache"] = {}
        conv.src.texture = lambda p: b"dds"
        with mock.patch.object(hair_probe, "decode_rgba", lambda dds, tc: px), \
                mock.patch.object(SH.skyrimnif, "texture_set", lambda n, r: ["textures\\h.dds"]), \
                mock.patch.object(SH.skyrimnif, "alpha_test", lambda n, r: (False, True, 164)):
            blend = SH.skyrim_coverage(conv, None, sh)
        self.assertTrue((blend[alpha[0] / 255.0 < SH.BLEND_SOLID] == 0).all())  # the faded part: not hair
        self.assertAlmostEqual(blend[0], 1.0)
        conv.__dict__["_alpha_cache"] = {}
        with mock.patch.object(hair_probe, "decode_rgba", lambda dds, tc: px), \
                mock.patch.object(SH.skyrimnif, "texture_set", lambda n, r: ["textures\\h.dds"]), \
                mock.patch.object(SH.skyrimnif, "alpha_test", lambda n, r: (True, False, 128)):
            test = SH.skyrim_coverage(conv, None, sh)
        self.assertEqual(test[0], 1.0)
        self.assertEqual(test[-1], 0.0)
        self.assertTrue(0 < test[4] < 1)                                          # the ramp round the threshold


class TessellateTests(unittest.TestCase):
    def octahedron(self, seam=False):
        """A unit-radius-0.1 octahedron round (0, 0, 1.7), normals pointing out (a round shell's), optionally with
        one edge's corners duplicated (a UV seam)."""
        from fo4sf import skyrimhair
        c = np.array([0, 0, 1.7])
        d = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1.0]])
        p = list(c + 0.1 * d)
        n = list(d)
        tris = [(4, 0, 2), (4, 2, 1), (4, 1, 3), (4, 3, 0), (5, 2, 0), (5, 1, 2), (5, 3, 1), (5, 0, 3)]
        w = [[("C_Head", 1.0)]] * 6
        if seam:                                    # vertices 6 / 7: copies of 4 / 0 used by one triangle
            p += [p[4], p[0]]
            n += [n[4], n[0]]
            w = w + [[("Hair1", 1.0)], [("C_Head", 1.0)]]
            tris[3] = (6, 3, 7)
        uv = [(float(i) / 8, 0.5) for i in range(len(p))]
        return skyrimhair.HairShape(b"S", np.array(p), np.array(n, float), np.zeros((len(p), 3)), uv, tris, w,
                                    3, -1, 0), c

    def test_rounds_the_shell(self):
        from fo4sf import skyrimhair
        sh, c = self.octahedron()
        out, rep = skyrimhair.tessellate(skyrimhair.Hair([sh], [], {}, {}), 3)
        new = out.shapes[0]
        self.assertEqual(len(new.triangles), 8 * 9)
        self.assertEqual(rep["vertices_before"], 6)
        self.assertEqual(len(new.positions), 6 + 12 * 2 + 8 * 1)    # corners, 2 per edge, 1 inside each face
        r_new = np.linalg.norm(np.asarray(new.positions) - c, axis=1)
        flat = []                                                     # the same points on the flat facets
        P = np.asarray(sh.positions)
        for a, b, cc in sh.triangles:
            for i in range(4):
                for j in range(4 - i):
                    flat.append((1 - (i + j) / 3) * P[a] + i / 3 * P[b] + j / 3 * P[cc])
        r_flat = np.linalg.norm(np.array(flat) - c, axis=1)
        self.assertLess(np.abs(r_new - 0.1).max(), np.abs(r_flat - 0.1).max() * 0.6)   # rounder (even at 90 deg)
        self.assertGreater(rep["largest_edge_bulge_mm"], 0)
        self.assertTrue(all(abs(sum(w for _b, w in vw) - 1) < 1e-9 for vw in new.weights))
        same, _r = skyrimhair.tessellate(skyrimhair.Hair([sh], [], {}, {}), 1)
        self.assertIs(same.shapes[0], sh)

    def test_seam_has_no_crack(self):
        from fo4sf import skyrimhair
        sh, _c = self.octahedron(seam=True)
        out, _rep = skyrimhair.tessellate(skyrimhair.Hair([sh], [], {}, {}), 3)
        pos = np.round(np.asarray(out.shapes[0].positions), 9)
        # the edge 4-0 is built twice (once from 4 / 0, once from the copies 6 / 7): the same points both times
        uniq = {tuple(x) for x in pos}
        self.assertEqual(len(uniq), 6 + 12 * 2 + 8)                 # no extra (cracked) positions
        mixed = [vw for vw in out.shapes[0].weights if len(vw) == 2]
        self.assertTrue(mixed)                                       # Hair1 blended into the seam's side


class NormalTests(unittest.TestCase):
    def shape(self, normals):
        from fo4sf import skyrimhair
        p = np.array([[0, -0.1, 1.6], [0.01, -0.1, 1.6], [0, -0.1, 1.5], [0.01, -0.1, 1.5]])    # behind the head
        return skyrimhair.HairShape(b"C", p, np.array(normals, float), np.zeros((4, 3)),
                                    [(0, 0), (1, 0), (0, 1), (1, 1)], [(0, 1, 2), (1, 3, 2)],
                                    [[("C_Head", 1.0)]] * 4, 3, -1, 0)

    def test_normals_from_the_faces(self):
        from fo4sf import skyrimhair
        sh = self.shape([[0, 1.0, 0], [0, 1.0, 0], [1.0, 0, 0], [0, -1.0, 0]])     # stale: mostly wrong
        out, rep = skyrimhair.geometric_normals(skyrimhair.Hair([sh], [], {}, {}))
        n = np.asarray(out.shapes[0].normals)
        face = np.cross(sh.positions[1] - sh.positions[0], sh.positions[2] - sh.positions[0])
        face /= np.linalg.norm(face)
        self.assertTrue(np.allclose(n, face[None, :]))                           # every vertex: the faces' normal
        self.assertEqual(rep["shapes"][0]["old_against_faces"], 0.25)            # one of four pointed the other way
        out2, rep2 = skyrimhair.geometric_normals(out)
        self.assertEqual(rep2["shapes"][0]["old_against_faces"], 0.0)

    def test_shell_normals_point_away_from_the_head(self):
        from fo4sf import skyrimhair
        head = np.eye(4)
        head[:3, 3] = (0, 0, 1.6)
        out, rep = skyrimhair.shell_normals(skyrimhair.Hair([self.shape([[0, 0, 1.0]] * 4)], [], {}, {}), head)
        n = np.asarray(out.shapes[0].normals)
        self.assertEqual(rep["vertices"], 4)
        self.assertTrue((n[:, 1] < -0.9).all())                                  # behind the head: -Y
        self.assertTrue(np.allclose(np.linalg.norm(n, axis=1), 1.0))

    def test_comb_evens_neighbouring_cards(self):
        from fo4sf import skyrimhair
        n = np.array([[0, -1.0, 0]] * 4)
        tri = [(0, 2, 1), (1, 2, 3)]
        p = np.array([[0, -0.1, 1.6], [0.01, -0.1, 1.6], [0, -0.1, 1.59], [0.01, -0.1, 1.59]])
        down = skyrimhair.HairShape(b"A", p, n, np.array([[1.0, 0, 0]] * 4), [(0, 0)] * 4, tri,
                                    [[("C_Head", 1.0)]] * 4, 3, -1, 0)          # strands vertical
        a = np.radians(40)
        tilt = skyrimhair.HairShape(b"B", p + [0.008, 0, 0], n, np.array([[np.cos(a), 0, np.sin(a)]] * 4),
                                    [(0, 0)] * 4, tri, [[("C_Head", 1.0)]] * 4, 3, -1, 0)   # strands 40 deg off
        far = skyrimhair.HairShape(b"C", p + [0.2, 0, 0], n, np.array([[0, 0, 1.0]] * 4), [(0, 0)] * 4, tri,
                                   [[("C_Head", 1.0)]] * 4, 3, -1, 0)           # out of reach: kept
        out, rep = skyrimhair.comb_strands(skyrimhair.Hair([down, tilt, far], [], {}, {}))
        ta, tb, tc = (np.asarray(sh.tangents) for sh in out.shapes)
        ang = lambda u, v: np.degrees(np.arccos(np.clip(abs(float(u @ v)), 0, 1)))     # noqa: E731
        self.assertLess(ang(ta[0], tb[0]), 15.0)                           # the two cards now close
        self.assertTrue(np.allclose(tc, [[0, 0, 1.0]] * 4))
        self.assertTrue(np.allclose((ta * n).sum(1), 0))                    # still across the normal
        self.assertGreater(float(ta[0] @ [1.0, 0, 0]), 0)                   # on the old tangent's side
        self.assertGreater(rep["turn_median_deg"], 0)

    def test_diagnostic_texture_looks(self):
        import shutil
        from fo4sf import skyrimconvert, textures

        def fake_texconv(exe, src, out_dir, fmt, extra=()):
            dst = os.path.join(out_dir, os.path.basename(src))
            if os.path.abspath(dst) != os.path.abspath(src):
                shutil.copy2(src, dst)
        px = mixed_strand_texture()
        px[:, :, 0] = np.arange(128, dtype=np.uint8)[None, :] * 2               # colour varies
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t.dds")
            textures.write_dds_dx10(p, 128, 64, textures.DXGI_R8G8B8A8_UNORM, px.tobytes(), 4)
            with open(p, "rb") as fh:
                raw = fh.read()
            conv = skyrimconvert.SkyrimConverter.__new__(skyrimconvert.SkyrimConverter)
            conv._materials, conv.stats, conv.material_errors = {}, {"materials_ok": 0}, {}
            conv.staging, conv.texconv, conv.prefix, conv.texture_caps = d, "t.exe", "s2s", {}
            conv.src = mock.Mock(texture=lambda name: raw)
            conv._hair_fill = {"AmbientOcclusion": "a", "DepthOffset": "b", "HairID": "c"}
            with mock.patch.object(textures, "texconv", fake_texconv):
                flat = conv.skyrim_hair_material("textures\\h\\t.dds", "", 40, strands=True, orient=True, look="flat")
                solid = conv.skyrim_hair_material("textures\\h\\t.dds", "", 40, strands=True, orient=True,
                                                  look="solid")
            self.assertTrue(flat.endswith("t_hair_o_flat.mat"))
            self.assertTrue(solid.endswith("t_hair_o_solid.mat"))

            def pixels(name, ch):
                with open(os.path.join(d, "textures", "s2s", "h", name), "rb") as fh:
                    b = fh.read()
                h = textures.read_dds_header(b)
                return np.frombuffer(b[h["data_offset"]:], np.uint8)[:h["width"] * h["height"] * ch]
            with mock.patch.object(textures, "texconv", fake_texconv):
                dense = conv.skyrim_hair_material("textures\\h\\t.dds", "", 40, strands=True, orient=True,
                                                  coverage=3.0)
                base = conv.hair_coverage_of(conv.skyrim_hair_material("textures\\h\\t.dds", "", 40, strands=True,
                                                                       orient=True))
            self.assertTrue(dense.endswith("t_hair_o_c3.mat"))
            with mock.patch.object(textures, "texconv", fake_texconv):
                van = conv.skyrim_hair_material("textures\\h\\t.dds", "", 40, strands=True, orient=True,
                                                vanilla_maps=True)
            self.assertTrue(van.endswith("t_hair_o_v.mat"))
            with open(os.path.join(d, *van.split("\\")), encoding="utf-8") as fh:
                vm = fh.read()
            self.assertIn("t_hair_o_v_ao.dds", vm)                               # its own AO, not the white filler
            ao = pixels("t_hair_o_v_ao.dds", 1)
            self.assertGreaterEqual(int(ao.min()), 108)
            self.assertLessEqual(int(ao.max()), 190)
            hid = pixels("t_hair_o_v_hairid.dds", 1)
            self.assertGreaterEqual(int(hid.min()), 28)
            self.assertLessEqual(int(hid.max()), 101)
            vc = pixels("t_hair_o_v_color.dds", 4).reshape(-1, 4)[:, :3].astype(float)
            lum = vc @ [0.2126, 0.7152, 0.0722]
            self.assertLess(lum.mean(), 35)                                      # Starfield's dark brown albedo
            self.assertAlmostEqual(vc[:, 0].mean() / max(vc[:, 1].mean(), 1e-6), 1.59, delta=0.1)
            with mock.patch.object(textures, "texconv", fake_texconv):
                reg = conv.skyrim_hair_material("textures\\h\\t.dds", "", 40, strands=True, orient=True,
                                                coverage=3.0, region=np.array([[0.6, 0.5], [0.9, 0.2]]))
            self.assertIn("_c3_r", reg)
            with mock.patch.object(textures, "texconv", fake_texconv):
                soft = conv.skyrim_hair_material("textures\\h\\t.dds", "", 40, strands=True, orient=True,
                                                 look="soft")
            self.assertTrue(soft.endswith("t_hair_o_soft.mat"))
            sop = pixels("t_hair_o_soft_opacity.dds", 1)
            self.assertGreater(len(np.unique(sop)), 2)                           # soft alpha kept, not cut
            self.assertIn("gain", conv.hair_coverage_of(reg)["region"])
            with mock.patch.object(textures, "texconv", fake_texconv):    # the same part of the texture: shared
                reg2 = conv.skyrim_hair_material("textures\\h\\t.dds", "", 40, strands=True, orient=True,
                                                 coverage=3.0, region=np.array([[0.61, 0.51], [0.91, 0.21]]))
            self.assertEqual(reg2, reg)
            rough = SH.settings_variant(conv, reg, "rough", {"Roughness": "0.85"})
            self.assertTrue(rough.endswith("_rough.mat"))
            with open(os.path.join(d, *rough.split("\\")), encoding="utf-8") as fh:
                rm = fh.read()
            with open(os.path.join(d, *reg.split("\\")), encoding="utf-8") as fh:
                base_txt = fh.read()
            self.assertIn('"Roughness" : "0.85"', rm)
            tex = lambda txt: sorted(x for x in txt.split('"') if x.lower().endswith(".dds"))   # noqa: E731
            self.assertEqual(tex(rm), tex(base_txt))                             # the same textures
            self.assertGreater(pixels("t_hair_o_c3_opacity.dds", 1).astype(float).mean() / 255,
                               base["after_cut"] + 0.1)                           # Skyrim's blended layers: denser
            col = pixels("t_hair_o_flat_color.dds", 4).reshape(-1, 4)
            self.assertEqual(len(np.unique(col[:, 0])), 1)                       # one colour
            op = pixels("t_hair_o_solid_opacity.dds", 1)
            self.assertEqual(int(op.min()), 255)                                 # nothing seen through


class MainTests(unittest.TestCase):
    def test_main_on_synthetic_games(self):
        from fo4sf import textures
        import hair_pack
        with tempfile.TemporaryDirectory() as d:
            sky = os.path.join(d, "Skyrim", "Data")
            os.makedirs(sky)
            skyrim_esms(sky)
            for rel in ("meshes/actors/character/hair/hairf01.nif", "meshes/actors/character/hair/hairlinef01.nif",
                        "meshes/actors/character/hair/hairm01.nif", "meshes/dlc01/hair/serana.nif"):
                p = os.path.join(sky, *rel.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as fh:
                    fh.write(hair_nif_bytes())
            for rel in ("textures/hair/h.dds", "textures/hair/h_n.dds"):
                p = os.path.join(sky, *rel.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as fh:
                    fh.write(F.rgba_dds(alpha=100))
            sf = os.path.join(d, "Starfield")
            os.makedirs(os.path.join(sf, "Data"))
            os.makedirs(os.path.join(sf, "Tools"))
            bob = hdpt("Human_Female_Hair_Bob", "Actors\\Human\\Mesh\\hairs\\bob\\bob_f.nif", 3, 0x01, [0x2313])
            short = hdpt("Human_Male_Hair_Short", "Actors\\Human\\Mesh\\hairs\\short\\short_m.nif", 3, 0x01)
            lnam = lambda *ids: [(b"LNAM", struct.pack("<I", i)) for i in ids]     # noqa: E731
            sfr = [rec(b"HDPT", bob, 0x00002311), rec(b"HDPT", short, 0x00002312),
                   rec(b"HDPT", hdpt("Human_Female_Hairline01", "hairline_f.nif", 11, 0x0C), 0x00002313),
                   rec(b"FLST", [(b"EDID", b"HeadPartsChargenOptionsFemale\0")] + lnam(0x2311), 0x0003D9B0),
                   rec(b"FLST", [(b"EDID", b"HeadPartsChargenOptionsMale\0")] + lnam(0x2312), 0x0003D9AF)]
            with open(os.path.join(sf, "Data", "Starfield.esm"), "wb") as fh:
                fh.write(sfplugin.build(sfr, {"hedr_version": 0.96, "form_version": 555}, masters=()))
            F.content_resources(os.path.join(sf, "Tools", "ContentResources.zip"))
            ident = (1, 0, 0, 0, 1, 0, 0, 0, 1)

            def game_nif(bones, binds):
                sh = sfnif.SkinnedShape(b"Hair", b"aa\\bb", 3, 3, "materials\\hair.mat", bones,
                                        [((0.0, 0.0, 0.0, 1.0), ident, t, 1.0) for t in binds])
                return nif.serialize(sfnif.build_skinned_nif(b"Hair", [sh]))
            fbn = game_nif([b"faceBone_C_Chin", b"faceBone_C_HeadTop"], [(0, -0.1, -1.55), (0, 0, -1.75)])
            game = {"meshes/actors/human/mesh/hairs/bob/bob_f_facebones.nif": fbn,
                    "meshes/actors/human/mesh/hairs/short/short_m_facebones.nif": fbn}
            ks_dir = os.path.join(d, "S2S Hair")                                  # the KS hairstyles next to it
            os.makedirs(ks_dir)
            ks = [rec(b"HDPT", hdpt("S2S_Hair_Anna", "s2s\\hair\\anna.nif", 3, 0x01), 0x01000800),
                  rec(b"FLST", [(b"EDID", b"HeadPartsChargenOptionsFemale\0")] + lnam(0x2311, 0x01000800), 0x0003D9B0)]
            with open(os.path.join(ks_dir, "S2SHair.esm"), "wb") as fh:
                fh.write(sfplugin.build(ks, {"hedr_version": 0.96, "form_version": 555}))
            out = os.path.join(d, "mod")
            with mock.patch.object(textures, "texconv", lambda *a, **k: None), \
                    mock.patch.object(hair_pack, "read_game_file",
                                      lambda sfp, rel: game.get(rel.replace("\\", "/").lower())), \
                    mock.patch.object(hair_pack, "read_template", lambda spec: b"cloth"), \
                    mock.patch.object(smpcloth, "check_template", lambda blob: template_root()), \
                    contextlib.redirect_stdout(io.StringIO()):
                rc = SH.main(["--skyrim-data", sky, "--starfield", sf, "--texconv", "texconv.exe", "--out", out,
                              "--cloth-template", "bob/bob_f.nif"])
                rc_diag = SH.main(["--skyrim-data", sky, "--starfield", sf, "--texconv", "texconv.exe", "--out",
                                   os.path.join(d, "diag"), "--cloth-template", "bob/bob_f.nif", "--only",
                                   "HairMaleNord01", "--diagnose", "--merge-plugin",
                                   os.path.join(ks_dir, "S2SHair.esm")])
            self.assertEqual(rc_diag, 0)

            seen = []

            def fake_cards(h, head, st, **kw):           # the fixture is one tiny card: the growing has its own tests
                self.assertEqual(len(kw["dirs"]), len(h.shapes))
                self.assertEqual(kw["layers"], SH.DENSE_CARDS["layers"])
                seen.append((kw.get("slots", 0), kw.get("hairline", False)))
                from fo4sf import skyrimhair
                sh = h.shapes[0]
                p = np.asarray(sh.positions)[:3]
                card = skyrimhair.HairShape(b"Cards0", p, np.asarray(sh.normals)[:3], np.zeros((3, 3)),
                                            [(st[0][0], st[0][1]), (st[0][2], st[0][1]), (st[0][0], st[0][3])],
                                            [(0, 1, 2)], list(sh.weights)[:3], -1, -1, 0)
                return skyrimhair.Hair([card], h.bones, h.host_of_root, h.report), {"cards": 1, "layers": [{}]}
            with mock.patch.object(textures, "texconv", lambda *a, **k: None), \
                    mock.patch.object(hair_pack, "read_game_file",
                                      lambda sfp, rel: game.get(rel.replace("\\", "/").lower())), \
                    mock.patch.object(hair_pack, "read_template", lambda spec: b"cloth"), \
                    mock.patch.object(smpcloth, "check_template", lambda blob: template_root()), \
                    mock.patch.object(SH.hairstrands, "grow_cards", fake_cards), \
                    mock.patch.object(SH, "strand_material",
                                      lambda *a, **k: ("Materials\\Actors\\Human\\Hair\\Medium_Hair_Shared.mat",
                                                       [(0.0, 0.0, 0.5, 1.0), (0.5, 0.0, 1.0, 1.0)])), \
                    contextlib.redirect_stdout(io.StringIO()):
                rc_cards = SH.main(["--skyrim-data", sky, "--starfield", sf, "--texconv", "texconv.exe", "--out",
                                    os.path.join(d, "cards"), "--cloth-template", "bob/bob_f.nif", "--only",
                                    "HairMaleNord01", "--strand-cards", "--merge-plugin",
                                    os.path.join(ks_dir, "S2SHair.esm")])
            self.assertEqual(rc_cards, 0)
            self.assertEqual(seen, [(0, False), (3, False), (3, True)])                                 # [strands] as before, the thin ones
            with open(os.path.join(d, "cards", "skyrim_hairs.json")) as fh:
                cards = json.load(fh)
            row = cards["parts"][1]
            self.assertEqual((row["variant"], row["ok"]), ("strands", True), row.get("reason"))
            self.assertGreater(row["strand_cards"]["cards"], 0)
            self.assertEqual(row["materials"], ["Materials\\Actors\\Human\\Hair\\Medium_Hair_Shared.mat"])
            thin, edge = cards["parts"][2], cards["parts"][3]               # rounds 7 and 8
            self.assertEqual((thin["variant"], thin["ok"]), ("strandsthin", True), thin.get("reason"))
            self.assertEqual((edge["variant"], edge["ok"]), ("strandsedge", True), edge.get("reason"))
            self.assertEqual(edge["materials"], ["Materials\\Actors\\Human\\Hair\\Medium_Hair_Shared.mat"])
            cparts = {sfplugin.edid(r[2]): dict(r[2]) for r in sfplugin.records(os.path.join(d, "cards", SH.PLUGIN),
                                                                                 [b"HDPT"])}
            self.assertEqual(cparts["S2S_HairMaleNord01_strands"][b"FULL"],
                             b"HairMaleNord01 (Skyrim, Starfield strands)\0")
            self.assertTrue(os.path.isfile(os.path.join(d, "cards", "meshes", "s2s", "skyrimhair",
                                                        "hairmalenord01_strands_facebones.nif")))
            with open(os.path.join(d, "diag", "README.txt"), encoding="utf-8") as fh:
                readme = fh.read()
            self.assertIn("    1. HairMaleNord01\n", readme)
            self.assertIn("    2. HairMaleNord01 [depth]", readme)
            with open(os.path.join(d, "diag", "skyrim_hairs.json")) as fh:
                diag = json.load(fh)
            self.assertEqual([(r["skyrim"], r.get("variant"), r["ok"]) for r in diag["parts"]],
                             [("HairMaleNord01", None, True), ("HairMaleNord01", "depth", True)])
            self.assertEqual(diag["parts"][1]["fit"], diag["parts"][0]["fit"])   # the copies reuse the shaping
            nt = [m for m in diag["parts"][1]["materials"] if "_depth" in m]
            self.assertTrue(nt)
            with open(os.path.join(d, "diag", *nt[0].split("\\")), encoding="utf-8") as fh:
                self.assertIn('"MaxDepthOffset" : "0.01"', fh.read())                    # IDG's depth offset
            plain = diag["parts"][0]["materials"][0]
            with open(os.path.join(d, "diag", *plain.split("\\")), encoding="utf-8") as fh:
                txt = fh.read()
            self.assertIn('"MaxDepthOffset" : "0"', txt)                                 # vanilla Skyrim: none
            self.assertIn('"Roughness" : "0.5125"', txt)                                 # the rest IDG's
            self.assertIn("normals", diag["parts"][0])                           # vanilla: normals from the faces
            self.assertGreater(diag["parts"][0]["tessellated"]["vertices_after"],
                               diag["parts"][0]["tessellated"]["vertices_before"])   # low-poly shells rounded
            self.assertEqual(diag["parts"][0]["fit"], {})                       # no head mesh in this game
            detail = diag["parts"][0]["shape_detail"][0]
            self.assertIn("opacity", detail, detail)
            self.assertAlmostEqual(detail["opacity"]["after_cut"], detail["opacity"]["alpha_mean"], delta=0.05)
            dparts = {sfplugin.edid(r[2]): dict(r[2]) for r in sfplugin.records(os.path.join(d, "diag", SH.PLUGIN),
                                                                                 [b"HDPT"])}
            self.assertNotIn(b"HNAM", dparts["S2S_HairMaleNord01_depth"])           # the male template has none
            self.assertEqual(dparts["S2S_HairMaleNord01_depth"][b"FULL"],
                             b"HairMaleNord01 (Skyrim, old depth offset)\0")
            self.assertEqual(dparts["S2S_HairMaleNord01_depth"][b"MODL"],
                             b"s2s\\skyrimhair\\hairmalenord01_depth.nif\0")
            self.assertEqual(rc, 0)
            rep = json.load(open(os.path.join(out, "skyrim_hairs.json")))
            rows = {r["skyrim"]: r for r in rep["parts"]}
            self.assertEqual(sorted(rows), ["HairFemaleNord01", "HairFemaleSerana", "HairMaleNord01"])
            for r in rows.values():
                self.assertTrue(r["ok"], r)
                self.assertTrue(r["facebones"])
            self.assertEqual(len(rows["HairFemaleNord01"]["models"]), 2)            # the hairline merged in
            self.assertFalse(rows["HairMaleNord01"]["female"])
            self.assertEqual(rep["templates"], {"female type 3": "Human_Female_Hair_Bob",
                                                "male type 3": "Human_Male_Hair_Short"})
            hair_dir = os.path.join(out, "meshes", "s2s", "skyrimhair")
            self.assertTrue(os.path.isfile(os.path.join(hair_dir, "hairfemalenord01.nif")))
            fb = sfnif.parse_skin(nif.parse(open(os.path.join(hair_dir, "hairfemalenord01_facebones.nif"),
                                                 "rb").read()))
            self.assertNotIn(b"C_Head", fb["bones"])
            got = sfplugin.records(os.path.join(out, SH.PLUGIN), [b"HDPT", b"FLST"])
            parts = {sfplugin.edid(r[2]): r for r in got if r[0] == b"HDPT"}
            self.assertEqual(sorted(parts), ["S2S_HairFemaleNord01", "S2S_HairFemaleSerana", "S2S_HairMaleNord01"])
            nord = dict(parts["S2S_HairFemaleNord01"][2])
            self.assertEqual(struct.unpack("<I", nord[b"HNAM"])[0], 0x2313)          # Starfield's hairline kept
            self.assertEqual(rep["template_extra_parts"]["Human_Female_Hair_Bob"],
                             [{"form_id": "00002313", "edid": "Human_Female_Hairline01", "type": 11,
                               "model": "hairline_f.nif"}])
            self.assertEqual(nord[b"MODL"], b"s2s\\skyrimhair\\hairfemalenord01.nif\0")
            self.assertEqual(nord[b"FULL"], b"HairFemaleNord01 (Skyrim)\0")
            lists = {sfplugin.edid(r[2]): r for r in got if r[0] == b"FLST"}
            fem = [struct.unpack("<I", x)[0] for s, x in lists["HeadPartsChargenOptionsFemale"][2] if s == b"LNAM"]
            self.assertEqual(fem[0], 0x2311)                                        # the vanilla entry kept
            self.assertEqual(fem[1], 0x01000800)                                    # the KS hairstyle kept (master 1)
            self.assertEqual(set(fem[2:]), {parts["S2S_HairFemaleNord01"][3], parts["S2S_HairFemaleSerana"][3]})
            self.assertEqual({parts[k][3] >> 24 for k in parts}, {2})               # ours after both masters
            self.assertEqual(rep["masters"], ["Starfield.esm", "S2SHair.esm"])
            male = [struct.unpack("<I", x)[0] for s, x in lists["HeadPartsChargenOptionsMale"][2] if s == b"LNAM"]
            self.assertEqual(male, [0x2312, parts["S2S_HairMaleNord01"][3]])
            mats = rows["HairFemaleNord01"]["materials"]
            self.assertTrue(all(m and m.lower().endswith(".mat") for m in mats))
            self.assertTrue(any("_hair" in m for m in mats))                       # the hair shader
            self.assertTrue(np.isfinite(rows["HairMaleNord01"]["vertices"]))


if __name__ == "__main__":
    unittest.main()
