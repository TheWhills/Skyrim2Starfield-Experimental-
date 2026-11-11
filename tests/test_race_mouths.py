"""race_mouths: a Skyrim race's mouth (the orc's teeth and tusks) as the race's Starfield teeth part (2026-11-10, owner:
"teeth and tusks"). Synthetic: a two-row vanilla 'teeth' mesh whose jawOpen drops the lower row; a Skyrim 'mouth'
of two rows (jaw / upper) placed through an alignment; its morph keys copied per side."""
import os
import struct
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))

from fo4sf import nif as nifmod, sfmesh, sfmorph, sfnif, sfplugin  # noqa: E402
from fo4sf.convert_static import mesh_file_path  # noqa: E402
import race_mouths as RM  # noqa: E402
import race_heads as H  # noqa: E402

IDENT = ((0, 0, 0, 1), (1, 0, 0, 0, 1, 0, 0, 0, 1), (0, 0, 0), 1.0)


def teeth_rows():
    xs = np.linspace(-0.02, 0.02, 5)
    upper = np.c_[xs, np.zeros(5), np.zeros(5)]
    lower = np.c_[xs, np.zeros(5), np.full(5, -0.01)]
    return np.r_[upper, lower]


def vanilla_teeth():
    pts = teeth_rows()
    tris = [(0, 1, 5), (1, 6, 5), (2, 3, 7), (3, 8, 7)]
    scale, raw = sfmesh.encode_positions([tuple(p) for p in pts], margin=0.02)
    m = sfmesh.SfMesh(triangles=tris, scale=scale, positions=raw, uv1=[(0, 0)] * 10,
                      normals=[sfmesh.encode_packed(0, -1, 0)] * 10, weights_per_vertex=1,
                      weights=[(0, 65535)] * 10, lods=[])
    sfmesh.build_meshlets(m)
    data = sfmesh.serialize(m)
    d, f = mesh_file_path(data)
    nb = nifmod.serialize(sfnif.build_skinned_nif(b"Teeth", [sfnif.SkinnedShape(
        b"Teeth", f"{d}\\{f}".encode(), 12, 10, "Materials\\Actors\\Human\\Teeth.mat", [b"C_Head"], [IDENT])]))
    perf = sfmorph.parse(sfmorph.build(10, ["jawOpen", "smile"], {
        "jawOpen": {i: (0.0, 0.0, -0.025) for i in range(5, 10)},
        "smile": {i: (0.001, 0.0, 0.0) for i in range(0, 5)}}))
    return pts, nb, {f"geometries/{d}/{f}.mesh": data}, perf


class ConvertTests(unittest.TestCase):
    def test_mouth_keys_follow_the_jaw(self):
        tpts, nb, files, perf = vanilla_teeth()
        # Skyrim 'mouth': 6 vertices, 3 upper + 3 jaw (tusks), in a frame the alignment halves and shifts
        sky_head = np.array([[-0.01, 0.002, 0.0], [0.0, 0.002, 0.0], [0.01, 0.002, 0.0],
                             [-0.01, 0.002, -0.011], [0.0, 0.002, -0.011], [0.012, 0.004, -0.004]])
        t = np.array([0.1, 0.0, 0.0])
        sky_model = (sky_head - t) / 0.5
        shape = {"shape": None, "pts": sky_model, "skin_pts": sky_model, "normals": np.tile([0, -1.0, 0], (6, 1)),
                 "uvs": [(i / 6, 0.5) for i in range(6)], "tris": np.array([[0, 1, 3], [1, 4, 3], [1, 2, 5]]),
                 "M": np.eye(4)}
        jaw = np.array([False, False, False, True, True, True])
        saved = (RM.skyrim_shapes, RM.jaw_labels)
        RM.skyrim_shapes = lambda data: (None, [shape])
        RM.jaw_labels = lambda shapes, tri: jaw
        try:
            def read_sky(p):
                if p.endswith(".tri"):
                    raise OSError("no tri")
                return b""
            out, info = RM.convert_mouth(read_sky, files.__getitem__, r"meshes\mouthorc.nif",
                                         (0.5, np.eye(3), t), tpts, {"bones": [b"C_Head"], "binds": [IDENT]}, nb,
                                         {"TMPP": perf, "TCMP": None}, "meshes/s2s/races/orc/mouth_m",
                                         "materials\\s2s\\mouthorc.mat")
        finally:
            RM.skyrim_shapes, RM.jaw_labels = saved
        self.assertEqual(info["vertices"], 6)
        self.assertEqual(info["jaw_vertices"], 3)
        self.assertEqual(info["vanilla_lower_vertices"], 5)
        self.assertEqual(info["lower_key"], "jawOpen")
        self.assertEqual(info["model"], "s2s\\races\\orc\\mouth_m.nif")
        self.assertEqual(info["morph_folders"]["TMPP"], "meshes\\morphs\\s2s\\races\\orc\\mouth_m\\performance")
        md = sfmorph.parse(out["meshes/morphs/s2s/races/orc/mouth_m/performance/morph.dat"])
        self.assertEqual(md.num_vertices, 6)
        self.assertEqual(sorted(md.deltas["jawOpen"]), [3, 4, 5])                 # the jaw and the tusk drop
        self.assertAlmostEqual(md.deltas["jawOpen"][5][2], -0.025, places=3)
        self.assertEqual(sorted(md.deltas["smile"]), [0, 1, 2])
        self.assertNotIn("meshes/morphs/s2s/races/orc/mouth_m/chargen/morph.dat", out)
        n = nifmod.parse(out["meshes/s2s/races/orc/mouth_m.nif"])
        g = next(sfnif.parse_bsgeometry(b) for i, b in enumerate(n.blocks) if n.type_of(i) == "BSGeometry")
        self.assertEqual(RM.vanilla_material(out["meshes/s2s/races/orc/mouth_m.nif"]), "materials\\s2s\\mouthorc.mat")
        # 2026-11-11: the player (face bones) is drawn from the _facebones twin
        self.assertEqual(out["meshes/s2s/races/orc/mouth_m_facebones.nif"], out["meshes/s2s/races/orc/mouth_m.nif"])
        mesh = sfmesh.parse(out["geometries/" + g.meshes[0].path.decode().replace("\\", "/") + ".mesh"])
        pos = np.array([sfmesh.decode_position(p, mesh.scale) for p in mesh.positions])
        self.assertLess(np.abs(pos - sky_head).max(), 1e-4)                          # aligned, teeth frame = head's
        self.assertEqual(len(mesh.triangles), 3)
        self.assertEqual(RM.vanilla_material(nb), "Materials\\Actors\\Human\\Teeth.mat")

    def test_lower_vertices_without_key(self):
        low, key = RM.lower_vertices(None, 4)
        self.assertEqual((low.tolist(), key), ([False] * 4, None))


class RecordTests(unittest.TestCase):
    def test_mouth_records(self):
        Z = lambda t: t.encode() + b"\0"                                              # noqa: E731
        by = {0x900: (b"H", [(b"EDID", Z("HumanMaleTeethMorph")), (b"TMPP", Z("Meshes\\Morphs\\Human\\Male\\Perf\\Teeth")),
                             (b"MOBC", struct.pack("<II", 7, 410))]),
              0x512: (b"H", [(b"EDID", Z("Human_Male_Teeth")), (b"MODL", Z("Actors\\Teeth.nif")), (b"DATA", b"\x03"),
                             (b"PNAM", struct.pack("<I", 9)), (b"RNAM", struct.pack("<I", 0x24A)),
                             (b"MNAM", struct.pack("<I", 0x900))])}
        info = {"part_fid": 0x512, "mrph_fid": 0x900, "vanilla_vertices": 410, "vertices": 348,
                "model": "s2s\\races\\orc\\mouth_m.nif", "replaces": [0x512, 0x513],
                "morph_folders": {"TMPP": "meshes\\morphs\\s2s\\races\\orc\\mouth_m\\performance"}}
        ids = iter(range(0x01000900, 0x01000a00))
        copies = {}
        recs = H.mouth_records(by, info, "Orc", False, 0x01000850, copies, lambda _edid: next(ids))
        (t1, _h1, m_subs, m_fid), (t2, _h2, p_subs, p_fid) = recs
        self.assertEqual((t1, t2), (b"MRPH", b"HDPT"))
        md, pd = dict(m_subs), dict(p_subs)
        self.assertEqual(H.text_of(md[b"TMPP"]), "Meshes\\morphs\\s2s\\races\\orc\\mouth_m\\performance")
        self.assertEqual(struct.unpack("<II", md[b"MOBC"]), (7, 348))
        self.assertEqual(H.text_of(pd[b"MODL"]), "s2s\\races\\orc\\mouth_m.nif")
        self.assertEqual(struct.unpack("<I", pd[b"MNAM"])[0], m_fid)
        self.assertEqual(struct.unpack("<I", pd[b"RNAM"])[0], 0x01000850)
        self.assertEqual(pd[b"DATA"], b"\x03")
        self.assertEqual(sfplugin.edid(p_subs), "S2S_OrcRace_Mouth_M")
        self.assertEqual(copies, {0x512: p_fid, 0x513: p_fid})


if __name__ == "__main__":
    unittest.main()


class ShapeReportTests(unittest.TestCase):
    def test_textures_per_shape(self):
        """2026-11-11 (owner: the Orc tusks pink in the looks menu, dark in the world): the mouth's shapes and the
        textures each one really uses."""
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import test_skyrim_armor as A
        rows = RM.shape_report(A.skinned_nif_bytes())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Sleeve")
        self.assertEqual(rows[0]["textures"][:2], ["textures\\armor\\iron\\cuirass.dds",
                                                   "textures\\armor\\iron\\cuirass_n.dds"])
        self.assertEqual(rows[0]["triangles"], 2)
        self.assertEqual(rows[0]["uv_min"][1], 0.5)

    def test_dump_textures(self):
        """--dump copies each mouth texture out of the archives (to look at the tusks' colours)."""
        import tempfile
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import test_skyrim_armor as A
        sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
        import hkx_to_af
        import mouth_probe
        from fo4sf import bsa
        files = {"m.nif": A.skinned_nif_bytes(), "textures\\armor\\iron\\cuirass.dds": b"DDS d",
                 "textures\\armor\\iron\\cuirass_n.dds": b"DDS n"}
        saved = (bsa.SkyrimArchives, hkx_to_af.read_any, mouth_probe.SKY_MOUTHS)
        bsa.SkyrimArchives = lambda d: None
        def read(p, sky):
            if p not in files:
                raise SystemExit("not found")
            return files[p]
        hkx_to_af.read_any = read
        mouth_probe.SKY_MOUTHS = {False: {"orc": "m.nif"}}
        try:
            with tempfile.TemporaryDirectory() as d:
                RM.main(["--skyrim-data", d, "--dump", os.path.join(d, "out")])
                with open(os.path.join(d, "out", "cuirass_n.dds"), "rb") as fh:
                    self.assertEqual(fh.read(), b"DDS n")
                self.assertTrue(os.path.isfile(os.path.join(d, "out", "m.nif")))
        finally:
            bsa.SkyrimArchives, hkx_to_af.read_any, mouth_probe.SKY_MOUTHS = saved


class BrightnessAndUvTestTests(unittest.TestCase):
    def test_color_texture_and_uv_pixels(self):
        self.assertEqual(RM.color_texture_of("materials\\s2s\\actors\\character\\mouth\\mouthorc_c67d0a6c.mat"),
                         "textures/s2s/actors/character/mouth/mouthorc_c67d0a6c_color.dds")
        self.assertEqual(RM.color_texture_of("x.mat"), "")
        px = np.frombuffer(RM.uv_test_pixels(8), np.uint8).reshape(8, 8, 4)
        self.assertEqual(px[1, 1, :3].tolist(), [230, 0, 0])       # top-left red
        self.assertEqual(px[1, 6, :3].tolist(), [0, 230, 0])       # top-right green
        self.assertEqual(px[6, 1, :3].tolist(), [0, 0, 230])       # bottom-left blue
        self.assertEqual(px[6, 6, :3].tolist(), [230, 230, 0])     # bottom-right yellow

    def test_write_mouths_brightens_and_writes_uv_test(self):
        """2026-11-11: the Orc teeth drew near black (Skyrim's texture is very dark): the material is converted with
        the colour times MOUTH_ALBEDO_GAIN; --mouth-uv-test overwrites its colour texture with the quarters."""
        import tempfile
        import types
        calls = []

        class Conv:
            neutral = "neutral.mat"

            def _shape_material(self, n, s, albedo_tint=None):
                calls.append(albedo_tint)
                return "materials\\s2s\\actors\\character\\mouth\\mouthorc_x.mat"
        with tempfile.TemporaryDirectory() as out:
            staging = os.path.join(out, "_mouth_staging")
            os.makedirs(os.path.join(staging, "textures"))
            saved = (H.mouth_converter, H.vanilla_teeth, RM.convert_mouth, H.facefit.starfield_head_parts)
            H.mouth_converter = lambda sky, o, *a: (Conv(), staging)
            H.vanilla_teeth = lambda recs, sf, female, ff: (1, b"", {}, 2)
            RM.convert_mouth = lambda *a: ({}, {"vertices": 3, "jaw_vertices": 1, "material": a[9]})
            H.facefit.starfield_head_parts = lambda raw: ([], {})
            import fo4sf.skyrimskin as sk
            import fo4sf.nif as nm
            saved2 = (sk.skinned_shapes, nm.parse)
            sk.skinned_shapes = lambda n: [object()]
            nm.parse = lambda b: None
            ff = types.SimpleNamespace(
                hkx_to_af=types.SimpleNamespace(read_any=lambda p, s: b"", vanilla_file=lambda p, s: (b"", p)),
                SF_HEADS={False: "h", True: "h"})
            made = {False: {"align": (1, np.eye(3), np.zeros(3)), "vertices": np.zeros((3, 3))}}
            try:
                done, rep = H.write_mouths("", out, made, ["OrcRace"], [], object(), ("", "", ""), ff,
                                           uv_test=True)
            finally:
                H.mouth_converter, H.vanilla_teeth, RM.convert_mouth, H.facefit.starfield_head_parts = saved
                sk.skinned_shapes, nm.parse = saved2
            self.assertEqual(calls, [(RM.MOUTH_ALBEDO_GAIN,) * 3])
            p = os.path.join(out, "textures", "s2s", "actors", "character", "mouth", "mouthorc_x_color.dds")
            self.assertTrue(os.path.isfile(p))
            self.assertEqual(rep["OrcRace male"]["uv_test"], "textures/s2s/actors/character/mouth/mouthorc_x_color.dds")


class FacebonesTwinTests(unittest.TestCase):
    def test_twin_skinned_to_teeth_bones(self):
        """2026-11-11 (nif_parts on the owner's game: teeth_facebones.nif is skinned to faceBone_C_TopTeeth /
        BottomTeeth; the player showed no C_Head-skinned Orc mouth): the twin puts the jaw vertices on the bottom
        teeth bone, the rest on the top, with the vanilla twin's binds."""
        bind_b = ((0, 0, 0, 1), (1, 0, 0, 0, 1, 0, 0, 0, 1), (0.0, 0.01, 0.0), 1.0)
        nb = nifmod.serialize(sfnif.build_skinned_nif(b"Teeth_faceBones", [sfnif.SkinnedShape(
            b"Teeth_faceBones:0", b"aaaa\\bbbb", 3, 3, "x.mat", [b"faceBone_C_TopTeeth", b"faceBone_C_BottomTeeth"],
            [IDENT, bind_b])]))
        pts = np.array([[0, 0, 0], [0.01, 0, 0], [0, 0, -0.01], [0.01, 0, -0.01]], float)
        jaw = np.array([False, False, True, True])
        out = RM.facebones_mouth(nb, pts, np.tile([0, -1.0, 0], (4, 1)), [(0, 0), (1, 0), (0, 1), (1, 1)],
                                 np.array([[0, 1, 2], [1, 3, 2]]), jaw, "mouth_m_faceBones", "m.mat")
        self.assertIsNotNone(out)
        mpath, mdata, nif = out
        n = nifmod.parse(nif)
        g = next(sfnif.parse_bsgeometry(b) for i, b in enumerate(n.blocks) if n.type_of(i) == "BSGeometry")
        from fo4sf import headbake
        sk = headbake.geometry_skin(n, g)
        self.assertEqual([b.decode() if isinstance(b, bytes) else b for b in sk["bones"]],
                         ["faceBone_C_TopTeeth", "faceBone_C_BottomTeeth"])
        m = sfmesh.parse(mdata)
        bones = [m.weights[i * m.weights_per_vertex][0] for i in range(4)]
        self.assertEqual(bones, [0, 0, 1, 1])
        plain = nifmod.serialize(sfnif.build_skinned_nif(b"T", [sfnif.SkinnedShape(
            b"T", b"aaaa\\bbbb", 3, 3, "x.mat", [b"C_Head"], [IDENT])]))
        self.assertIsNone(RM.facebones_mouth(plain, pts, np.tile([0, -1.0, 0], (4, 1)), [(0, 0)] * 4,
                                             np.array([[0, 1, 2]]), jaw, "m", "m.mat"))
