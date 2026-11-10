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
        recs = H.mouth_records(by, info, "Orc", False, 0x01000850, copies, lambda: next(ids))
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
