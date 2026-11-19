"""child_faces: Skyrim's children on Starfield's child head (races roadmap I2, 2026-11-12)."""
import json
import os
import struct
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))

import numpy as np  # noqa: E402

import child_faces as C  # noqa: E402
from fo4sf import sfplugin  # noqa: E402

Z = lambda t: t.encode() + b"\0"                                 # noqa: E731
I = lambda v: struct.pack("<I", v)                               # noqa: E731


def npc(fid, edid, female, race, extra=()):
    subs = [(b"EDID", Z(edid)), (b"ACBS", I(1 if female else 0) + bytes(12)), (b"RNAM", I(race))] + list(extra)
    return (b"NPC_", b"", subs, fid)


class ChildFaceTests(unittest.TestCase):
    def test_tone_and_paths(self):
        self.assertEqual([C.child_tone(s) for s in (0, 3, 4, 6, 8, 12)], [0, 1, 1, 2, 2, 2])
        self.assertIsNone(C.child_tone(None))
        self.assertEqual(C.child_model_path("Dorthe"), "S2S\\Children\\DortheHead.nif")
        self.assertEqual(C.twin("meshes/a/b.nif"), "meshes/a/b_facebones.nif")

    def test_pick_child_template_by_face_skin(self):
        """2026-11-19 (owner: Frodnar's face read African): with an ethnicity, a template whose face skin names it
        first, then one naming none, then the rest; plain before scripted within each."""
        child = 0x34FB1
        V = (b"VTCK", I(1))
        D = lambda tex: [(b"TNAM", Z("Dermaesthetic")), (b"QNAM", Z(tex)), (b"INTV", I(64))]     # noqa: E731
        recs = [npc(1, "AChildAfrican", False, child, [V] + D("African_Child_Male_01")),
                npc(2, "BChildPlain", False, child, [V]),
                npc(3, "CChildEuroScript", False, child, [V, (b"VMAD", b"x")] + D("European_Child_Male_02")),
                npc(4, "DChildEuro", False, child, [V] + D("European_Child_Male_03"))]
        self.assertEqual(C.pick_child_template(recs, child, False, ethnicity="european")[3], 4)
        self.assertEqual(C.pick_child_template(recs[:3], child, False, ethnicity="european")[3], 3)
        self.assertEqual(C.pick_child_template(recs[:2], child, False, ethnicity="european")[3], 2)
        self.assertEqual(C.pick_child_template(recs[:1], child, False, ethnicity="european")[3], 1)
        self.assertEqual(C.pick_child_template(recs, child, False, ethnicity="african")[3], 1)
        self.assertIsNone(C.pick_child_template(recs, child, True, ethnicity="european"))
        self.assertEqual(C.face_ethnicity(recs[3][2]), ("european", "European_Child_Male_03"))
        self.assertEqual(C.face_ethnicity(recs[1][2]), (None, None))
        self.assertEqual(C.child_ethnicity("NordRaceChild"), "european")
        self.assertEqual(C.child_ethnicity("RedguardRaceChild"), "african")
        self.assertEqual(C.child_ethnicity(""), "european")
        self.assertEqual([t[0] for t in C.child_templates(recs, child, False)],
                         ["AChildAfrican", "BChildPlain", "CChildEuroScript", "DChildEuro"])

    def test_pick_child_template(self):
        child = 0x2AABCD
        recs = [npc(1, "Kid_Templated", True, child, [(b"TPLT", I(5)), (b"VTCK", I(1))]),
                npc(2, "Kid_Scripted", True, child, [(b"VTCK", I(1)), (b"VMAD", b"x")]),
                npc(3, "Kid_Plain", True, child, [(b"VTCK", I(1))]),
                npc(4, "Adult", True, 0x347D, [(b"VTCK", I(1))]),
                npc(5, "Boy", False, child, [(b"VTCK", I(1))])]
        self.assertEqual(C.pick_child_template(recs, child, True)[3], 3)
        self.assertEqual(C.pick_child_template(recs, child, False)[3], 5)
        self.assertEqual(C.pick_child_template(recs[:2], child, True)[3], 2)         # scripted if nothing plain
        self.assertIsNone(C.pick_child_template(recs[3:4], child, True))

    def test_child_npc_subs(self):
        types_ = {0x243A74: 1, 0x37C65E: 3}
        tpl = [(b"EDID", Z("Kid_Plain")), (b"FULL", Z("Kid")), (b"RNAM", I(0x2AABCD)), (b"PNAM", I(0x243A74)),
               (b"PNAM", I(0x37C65E)), (b"STON", b"\x00"), (b"HCOL", Z("Brown"))]
        out = C.child_npc_subs(tpl, "Dorthe", "Dorthe", 0x1000801, types_, race_fid=0x0300090A, ston=2)
        d = dict(out)
        self.assertEqual(d[b"EDID"], Z("S2SFace_Dorthe"))
        self.assertEqual(d[b"RNAM"], I(0x0300090A))
        self.assertEqual([struct.unpack("<I", x)[0] for s, x in out if s == b"PNAM"], [0x1000801, 0x37C65E])
        self.assertEqual(d[b"STON"], b"\x02")
        # no Face part on the template: ours added after its parts; race kept without race_fid
        out2 = C.child_npc_subs(tpl[:3] + tpl[4:], "Frodnar", "Frodnar", 0x1000802, types_)
        self.assertEqual([struct.unpack("<I", x)[0] for s, x in out2 if s == b"PNAM"], [0x37C65E, 0x1000802])
        self.assertEqual(dict(out2)[b"RNAM"], I(0x2AABCD))

    def test_child_head_part(self):
        van = [(b"EDID", Z("Human_Child_Head_Girl")), (b"MODL", Z("Actors\\Child\\Mesh\\Child_Head_Girl.nif")),
               (b"PNAM", I(1)), (b"RNAM", I(0x1550F)), (b"MNAM", I(0x243A9A))]
        out = dict(C.child_head_part(van, "Dorthe", C.child_model_path("Dorthe")))
        self.assertEqual(out[b"EDID"], Z("S2S_ChildHead_Dorthe"))
        self.assertEqual(out[b"MODL"], Z("S2S\\Children\\DortheHead.nif"))
        self.assertEqual((out[b"RNAM"], out[b"MNAM"]), (I(0x1550F), I(0x243A9A)))       # list and morph kept

    def test_child_disp(self):
        """The child's own features (FaceGen minus the child head) through the alignment's scale / rotation."""
        base = np.array([[0.0, 0, 0], [1, 0, 0], [0, 1, 0]])
        fg = base + np.array([[0, 0, 0.5], [0, 0, 0], [0, 0, 0]])
        R = np.eye(3)

        class Corr:
            def transfer(self, field, smooth):
                return field              # identity correspondence
        ctx = {"base": base, "al": (0.01, R, np.zeros(3), 0.0), "corr": Corr(),
               "head": types.SimpleNamespace(vertices=base)}
        d = C.child_disp(ctx, fg, smooth=0, symmetry=False)
        self.assertTrue(np.allclose(d[0], [0, 0, 0.005]))
        with self.assertRaises(ValueError):
            C.child_disp(ctx, fg[:2], smooth=0, symmetry=False)

    def test_converted_child_races(self):
        import face_fit
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "race_heads.json"), "w") as fh:
                json.dump({"child_races": {"NordRaceChild": {"edid": "S2S_NordChildRace", "form_id": "0100090A"}}},
                          fh)
            self.assertEqual(face_fit.converted_child_races(os.path.join(d, "S2SRaceTest.esm")),
                             {"NordRaceChild": 0x90A})
            self.assertEqual(face_fit.converted_child_races(os.path.join(d, "none", "x.esm")), {})


class BaseHeadTests(unittest.TestCase):
    """2026-11-19: a child's base head is its race's Face head part (RS Children Overhaul's races: its own child head,
    996 vertices, verified on the mod files), not always vanilla's ChildHead.nif."""

    def race(self, male, female):
        def u(v):
            return struct.pack("<I", v)
        return ([(b"EDID", b"NordRaceChild\0"), (b"NAM0", b""), (b"MNAM", b"")] + [(b"HEAD", u(p)) for p in male]
                + [(b"FNAM", b"")] + [(b"HEAD", u(p)) for p in female])

    def test_race_face_part(self):
        parts = {0x0100183F: {"type": 1, "model": "actors\\character\\ranaline\\character assets\\childhead.nif"},
                 0x01001845: {"type": 2, "model": "Actors\\Character\\Character Assets\\EyesFemale.nif"}}
        subs = self.race([0x01001845, 0x0100183F], [0x0100183F])
        self.assertEqual(C.base_head_path(subs, parts, True),
                         "meshes\\actors\\character\\ranaline\\character assets\\childhead.nif")
        self.assertEqual(C.base_head_path(self.race([], []), parts, False), C.SKY_CHILD_HEAD)

    def test_facegen_through_the_base_matrix(self):
        """2026-11-19: Realistic RS Children's FaceGen heads have a near-identity skin transform, RS's child head the
        head bone's (120 units up): the FaceGen points go through the BASE head's matrix (local points agree)."""
        local = np.array([[0.0, 1.0, 2.0], [3.0, -1.0, 0.5]])
        ff = types.SimpleNamespace(skyrim_head=lambda data, model=False: None if model else local.copy())
        m = np.eye(4)
        m[2, 3] = 120.0
        got = C.facegen_points({"base_matrix": m}, ff, b"x")
        np.testing.assert_allclose(got, local + [0, 0, 120.0])
        np.testing.assert_allclose(C.facegen_points({"base_matrix": None}, ff, b"x"), local)


if __name__ == "__main__":
    unittest.main()
