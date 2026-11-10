"""scripts/npc/race_heads.py on synthetic data: region weights (normalised, unmoved vertices filled from neighbours,
seams welded); a race shape split into region keys that add back up to it; the frame check; the morph.dat (vanilla keys
kept, ours added, 128-key limit); the test plugin (MRPH TCMP pointed at our folder, HDPT on it, NPCs with our head part
and BMPN blends, control NPC, optional HumanRace override) from a synthetic Starfield.esm, with race_probe's transfer
stubbed."""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import types
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "npc"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
from fo4sf import sfmorph, sfplugin  # noqa: E402
import race_heads as H  # noqa: E402

I = lambda v: struct.pack("<I", v)                   # noqa: E731
Z = sfplugin.zs


def strip_mesh(n=6):
    """A strip of n x 2 quads (vertices (0..n, 0..2) on a plane facing +z), and its triangles."""
    v = np.array([(x, y, 0.0) for y in range(3) for x in range(n + 1)], float) * 0.01
    w = n + 1
    t = []
    for y in range(2):
        for x in range(n):
            a, b, c, d = y * w + x, y * w + x + 1, (y + 1) * w + x, (y + 1) * w + x + 1
            t += [(a, b, d), (a, d, c)]
    return v, np.array(t, int)


def vanilla_morph(nv, region_cols):
    """A head morph: phenotypes p1, p2 x regions; region R moves the vertices whose x column is in region_cols[R]
    (p2 twice as far); plus Overweight pushing every vertex out (+z, the normal)."""
    keys, deltas = [], {}
    for p in ("male_eu_md1", "male_af_md1"):
        for r, cols in region_cols.items():
            k = f"{p}_{r}"
            keys.append(k)
            f = 1.0 if p.endswith("eu_md1") else 2.0
            deltas[k] = {v: (0.0, 0.0, 0.001 * f) for v in range(nv) if v % 7 in cols}
    keys.append("Overweight")
    deltas["Overweight"] = {v: (0.0, 0.0, 0.002) for v in range(nv)}
    return sfmorph.parse(sfmorph.build(nv, keys, deltas))


class WeightTests(unittest.TestCase):
    def test_weights_split_and_fill(self):
        v, t = strip_mesh()
        nv = len(v)
        m = vanilla_morph(nv, {"Nose": [0, 1, 2], "Eyes": [2, 3]})        # column 2 shared; 4..6 moved by none
        regions, W = H.region_weights(m, t, nv)
        self.assertEqual(regions, ["Eyes", "Nose"])
        self.assertTrue(np.allclose(W.sum(1), 1.0))
        self.assertTrue(np.allclose(W[[x for x in range(nv) if x % 7 == 2]], 0.5))   # shared: half each
        self.assertTrue(np.allclose(W[[x for x in range(nv) if x % 7 == 0], 1], 1.0))  # Nose only
        far = [x for x in range(nv) if x % 7 == 6]
        self.assertTrue(np.allclose(W[far].sum(1), 1.0))                  # filled from the neighbours
        self.assertGreater(W[far, 0].min(), 0.5)                          # next to Eyes (column 3), not Nose
        disp = np.tile([0.0, 0.003, 0.0], (nv, 1)) * np.arange(nv)[:, None]
        keys = H.race_keys("male", "HighElfRace", disp, regions, W)
        self.assertEqual(sorted(keys), ["male_sk_he1_Eyes", "male_sk_he1_Nose"])
        total = np.zeros_like(disp)
        for dd in keys.values():
            for i, d in dd.items():
                total[i] += d
        self.assertLess(np.abs(total - disp).max(), 1e-12)                # the keys add up to the race shape

    def test_weld_and_frame_check(self):
        v, t = strip_mesh()
        W = np.zeros((len(v) + 1, 2))
        W[:-1, 0] = 1.0
        W[-1, 1] = 1.0
        v2 = np.concatenate([v, v[:1]])                                   # vertex 0 split along a seam
        Ww = H.weld_weights(W, v2)
        self.assertTrue(np.allclose(Ww[0], Ww[-1]) and np.allclose(Ww[0], 0.5))
        m = vanilla_morph(len(v), {"Nose": [0]})
        tri = np.asarray(t)[:, [0, 2, 1]]                                 # wound to face +z... or not
        out = H.frame_check(m, v, t)
        self.assertIn(out, (0.0, 1.0))
        self.assertEqual(H.frame_check(m, v, tri), 1.0 - out)             # the winding decides the normal's side
        self.assertIsNone(H.frame_check(m, v, t, key="Missing"))


def starfield_esm(path):
    h = lambda t: struct.pack("<4sIII", t, 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)   # noqa: E731
    tcmp = lambda p: struct.pack("<H", len(p) + 1) + p.encode() + b"\0"                        # noqa: E731
    recs = [
        (b"MRPH", h(b"MRPH"), [(b"EDID", Z("HumanMaleHeadMorph")), (b"TCMP", tcmp("Meshes\\Morphs\\Human\\Male\\"
                                                                                 "Chargen\\Head")),
                               (b"MOBC", bytes(4))], 0x700),
        (b"MRPH", h(b"MRPH"), [(b"EDID", Z("HumanFemaleHeadMorph")),
                               (b"TCMP", tcmp("Meshes\\Morphs\\Human\\Female\\Chargen\\Head"))], 0x701),
        (b"HDPT", h(b"HDPT"), [(b"EDID", Z("Human_Male_Head")), (b"MODL", Z("Actors\\Human\\MaleHead.nif")),
                               (b"DATA", b"\x01"), (b"PNAM", I(1)), (b"MNAM", I(0x700))], 0x510),
        (b"HDPT", h(b"HDPT"), [(b"EDID", Z("Human_Female_Head")), (b"MODL", Z("Actors\\Human\\FemaleHead.nif")),
                               (b"DATA", b"\x01"), (b"PNAM", I(1)), (b"MNAM", I(0x701))], 0x511),
        (b"HDPT", h(b"HDPT"), [(b"EDID", Z("Human_Male_Teeth")), (b"PNAM", I(9))], 0x512),
        (b"RACE", h(b"RACE"), [(b"EDID", Z("HumanRace")),
                               (b"MNAM", b""), (b"MPGN", Z("Nose")), (b"MPGM", Z("male_eu_md1_Nose")),
                               (b"MPGN", Z("Eyes")), (b"MPGM", Z("male_eu_md1_Eyes")), (b"FDSI", I(1)),
                               (b"INDX", I(0)), (b"HEAD", I(0x510)), (b"INDX", I(1)), (b"HEAD", I(0x512)),
                               (b"FNAM", b""), (b"MPGN", Z("Nose")), (b"MPGM", Z("female_eu_md1_Nose")),
                               (b"INDX", I(0)), (b"HEAD", I(0x511))], 0x347D),
        (b"NPC_", h(b"NPC_"), [(b"EDID", Z("PlainM")), (b"ACBS", bytes(16)), (b"RNAM", I(0x347D)),
                               (b"VTCK", I(1)), (b"DNAM", bytes(8)), (b"PNAM", I(0x510)), (b"PNAM", I(0x512)),
                               (b"FMSI", I(3)), (b"FMRS", struct.pack("<f", 0.5)), (b"FMRI", I(12)),
                               (b"FMRG", Z("Nose")), (b"FMRS", struct.pack("<f", 0.2)),
                               (b"BMPN", Z("male_eu_md1_Nose")), (b"BMPV", struct.pack("<f", 0.2)),
                               (b"DOFT", I(0x900)), (b"ATTX", b"\0"), (b"HCOL", Z("Brown"))], 0x800),
        (b"NPC_", h(b"NPC_"), [(b"EDID", Z("PlainF")), (b"ACBS", I(1) + bytes(12)), (b"RNAM", I(0x347D)),
                               (b"VTCK", I(1)), (b"DNAM", bytes(8)), (b"FMSI", I(3)),
                               (b"FMRS", struct.pack("<f", 0.5)), (b"ATTX", b"\0")], 0x801),
        (b"OTFT", h(b"OTFT"), [(b"EDID", Z("SomeOutfit"))], 0x900)]
    with open(path, "wb") as fh:
        fh.write(sfplugin.build(recs, {"hedr_version": 0.96, "form_version": 555}, masters=()))


class PluginTests(unittest.TestCase):
    def test_override_groups_and_head(self):
        subs = [(b"EDID", Z("HumanRace")), (b"MNAM", b""), (b"MPGN", Z("Nose")), (b"MPGM", Z("a")),
                (b"MPGN", Z("Eyes")), (b"MPGM", Z("b")), (b"MPGM", Z("c")), (b"INDX", I(0)), (b"HEAD", I(5)),
                (b"FNAM", b""), (b"MPGN", Z("Nose")), (b"HEAD", I(6))]
        out, n = H.race_override(subs, 99, {"Nose": ["x"], "Eyes": ["y", "z"]}, {5: 1, 6: 1}, False)
        names = [(s, bytes(d).split(b"\0")[0].decode() if s != b"HEAD" else struct.unpack("<I", d)[0])
                 for s, d in out if s in (b"MPGN", b"MPGM", b"HEAD")]
        self.assertEqual(names, [(b"MPGN", "Nose"), (b"MPGM", "a"), (b"MPGM", "x"), (b"MPGN", "Eyes"),
                                 (b"MPGM", "b"), (b"MPGM", "c"), (b"MPGM", "y"), (b"MPGM", "z"), (b"HEAD", 99),
                                 (b"MPGN", "Nose"), (b"HEAD", 6)])       # the female section untouched
        self.assertEqual(n, {"head_parts_replaced": 1, "morph_group_entries_added": 3})

    def test_end_to_end(self):
        v, t = strip_mesh()
        nv = len(v)
        m = vanilla_morph(nv, {"Nose": [0, 1, 2], "Eyes": [2, 3]})
        data = sfmorph.build(nv, m.keys, m.deltas)
        disp = {r: np.tile([0.0, 0.0, 0.004 * (i + 1)], (nv, 1)) for i, r in enumerate(H.CODES)}
        head = types.SimpleNamespace(vertices=v, triangles=t)
        fake_rp = types.SimpleNamespace(
            SF_MORPH="meshes/morphs/human/{sex}/chargen/{part}/morph.dat",
            race_transfer=lambda sky, sf, female, smooth, ff: (head, None, None, None, disp,
                                                               {"transfer": "surface", "alignment": {"rms_m": 0.008}}))
        import face_fit
        saved = (sys.modules.get("race_probe"), face_fit.hkx_to_af.vanilla_file, H.bsa_archives)
        sys.modules["race_probe"] = fake_rp
        face_fit.hkx_to_af.vanilla_file = lambda p, d: (data, p)
        H.bsa_archives = lambda d: None
        try:
            with tempfile.TemporaryDirectory() as d:
                sf = os.path.join(d, "sf")
                os.makedirs(os.path.join(sf, "Data"))
                starfield_esm(os.path.join(sf, "Data", "Starfield.esm"))
                out = os.path.join(d, "out")
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(H.main(["--skyrim-data", d, "--starfield", sf, "--out", out,
                                             "--races", "HighElfRace,OrcRace", "--race-head"]), 0)
                with open(os.path.join(out, "race_heads.json")) as fh:
                    rep = json.load(fh)
                mfile = os.path.join(out, "meshes", "morphs", "s2s", "races", "male", "chargen", "head", "morph.dat")
                with open(mfile, "rb") as fh:
                    mm = sfmorph.parse(fh.read())
                self.assertEqual(mm.keys[:len(m.keys)], m.keys)                       # vanilla keys first, kept
                self.assertIn("male_sk_he1_Nose", mm.keys)
                self.assertIn("male_sk_or1_Eyes", mm.keys)
                self.assertEqual(len(mm.keys), len(m.keys) + 4)
                self.assertEqual(rep["sexes"]["male"]["frame_check_overweight_outward"] in (0.0, 1.0), True)
                self.assertLess(rep["sexes"]["male"]["races"]["OrcRace"]["split_error_max_m"], 1e-3)  # half floats
                recs = sfplugin.records(os.path.join(out, H.PLUGIN), [b"MRPH", b"HDPT", b"NPC_", b"RACE", b"OTFT"])
                by = {sfplugin.edid(s): (t, s, fid) for t, _h, s, fid in recs}
                tc = dict(by["S2S_SkyrimRaces_male_HeadMorph"][1])[b"TCMP"]
                self.assertEqual(H.text_of(tc), "Meshes\\Morphs\\S2S\\Races\\Male\\Chargen\\Head")
                self.assertEqual(struct.unpack("<H", tc[:2])[0], len(H.text_of(tc)) + 1)   # length prefix kept
                head_m = by["S2S_SkyrimRaces_male_Head"]
                self.assertEqual(struct.unpack("<I", dict(head_m[1])[b"MNAM"])[0],
                                 by["S2S_SkyrimRaces_male_HeadMorph"][2])
                alt = by["S2SRace_Altmer_male"][1]
                pn = [struct.unpack("<I", d)[0] for s, d in alt if s == b"PNAM"]
                self.assertEqual(pn, [0x512, head_m[2]])                                # vanilla face part out
                blends = [bytes(d).split(b"\0")[0].decode() for s, d in alt if s == b"BMPN"]
                self.assertEqual(blends, ["male_sk_he1_Eyes", "male_sk_he1_Nose"])
                sigs = [s for s, _d in alt]
                for gone in (b"FMSI", b"FMRI", b"FMRG"):
                    self.assertNotIn(gone, sigs)
                self.assertLess(sigs.index(b"BMPN"), sigs.index(b"ATTX"))
                ctl = by["S2SRace_Control_male"][1]
                self.assertNotIn(b"BMPN", [s for s, _d in ctl])
                self.assertIn(struct.pack("<I", head_m[2]), [d for s, d in ctl if s == b"PNAM"])
                self.assertIn("S2SRace_Orc_female", by)
                race = by["HumanRace"]
                self.assertEqual(race[2], 0x347D)
                mp = [bytes(d).split(b"\0")[0].decode() for s, d in race[1] if s == b"MPGM"]
                self.assertIn("male_sk_he1_Nose", mp)
                self.assertIn("female_sk_or1_Nose", mp)
                self.assertEqual(rep["race_override"]["male"]["head_parts_replaced"], 1)
                self.assertEqual(len(rep["npcs"]), 6)                                   # control + 2 races, x 2
                # a morph whose Overweight points into the head (another frame): nothing written without --force
                head.triangles = t[:, [0, 2, 1]]
                out2 = os.path.join(d, "out2")
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                    H.main(["--skyrim-data", d, "--starfield", sf, "--out", out2, "--races", "OrcRace"])
                self.assertFalse(os.path.exists(os.path.join(out2, H.PLUGIN)))
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(H.main(["--skyrim-data", d, "--starfield", sf, "--out", out2, "--races",
                                             "OrcRace", "--force"]), 0)
        finally:
            if saved[0] is None:
                sys.modules.pop("race_probe", None)
            else:
                sys.modules["race_probe"] = saved[0]
            face_fit.hkx_to_af.vanilla_file, H.bsa_archives = saved[1], saved[2]

    def test_new_keys_carry_no_change_words(self):
        """2026-11-09: our race keys' records take the vanilla head's colour word and zero normal / tangent deltas."""
        m = sfmorph.Morph(3, 2, ["V"], {"V": {0: (0, 0, 0), 1: (0, 0, 0)}},
                          {"V": {0: (0x1234, 1, 2), 1: (0x1234, 3, 4)}})
        self.assertEqual(H.neutral_extra(m), (0x1234, 0x5FF7FDFF, 0x5FF7FDFF))
        self.assertEqual(H.neutral_extra(sfmorph.Morph(3, 1, [], {}, {})), sfmorph.NEUTRAL_EXTRA)

    def test_without_hair(self):
        """2026-11-09 (owner: the males' hair hid the ears): hair and facial hair parts dropped, the rest kept."""
        types_ = {1: 1, 2: 3, 3: 4, 4: 6}
        subs = [(b"PNAM", struct.pack("<I", f)) for f in (1, 2, 3, 4)] + [(b"EDID", b"x\0")]
        self.assertEqual([struct.unpack("<I", d)[0] for s_, d in H.without_hair(subs, types_) if s_ == b"PNAM"], [1, 4])

    def test_symmetric_race_shape_any_frame(self):
        """2026-11-09 (owner: one ear better than the other): the race shape is made mirror-symmetric across the head's
        own lateral axis, which in a Starfield head .mesh (C_Head's frame) need not be X."""
        from fo4sf import facefit
        rng = np.random.default_rng(1)
        half = rng.uniform([0.01, -0.1, 0.0], [0.08, 0.1, 0.2], (200, 3))       # x across, then put across on z
        both = np.vstack([half, half * [-1, 1, 1]])[:, [1, 2, 0]]
        self.assertEqual(facefit.lateral_axis(both), 2)
        field = np.zeros_like(both)
        field[:200, 2] = 0.01                                                  # one ear out, the other unmoved
        sym = facefit.symmetrize(field, both, 2)
        self.assertTrue(np.allclose(sym[:200, 2], 0.005))
        self.assertTrue(np.allclose(sym[200:, 2], -0.005))                     # mirrored: outward on the other side
        strong = facefit.symmetrize(field, both, 2, "stronger")              # the side with the point, both sides
        self.assertTrue(np.allclose(strong[:200, 2], 0.01))
        self.assertTrue(np.allclose(strong[200:, 2], -0.01))

    def test_short_hair(self):
        """2026-11-09 (owner: the race-default hair came back and hid the ears): the closest-cropped vanilla hair."""
        def hd(e, flags):
            return [(b"EDID", e.encode() + b"\0"), (b"DATA", bytes([flags]))]
        hdpts = {1: hd("Human_Hair_Male_Buzzcut", 0x2), 2: hd("Human_Hair_Female_Bald", 0x4),
                 3: hd("Human_Hair_Long", 0x2), 4: hd("Human_Hair_Male_Bald", 0x2), 5: hd("Beard_Buzz", 0x2)}
        types_ = {1: 3, 2: 3, 3: 3, 4: 3, 5: 4}
        self.assertEqual(H.short_hair(hdpts, types_, False), (4, "Human_Hair_Male_Bald"))
        self.assertEqual(H.short_hair(hdpts, types_, True), (2, "Human_Hair_Female_Bald"))
        self.assertIsNone(H.short_hair({3: hdpts[3]}, types_, False))

    def test_baked_faces_from_the_template(self):
        """2026-11-09 (owner: race NPCs dark red, nose / lips light; control plain): each test NPC gets its template's
        pre-built face textures under its own FormID, as face_fit's NPCs do."""
        import face_fit
        from unittest import mock
        npcs = [{"edid": "S2SRace_Orc_male", "form_id": "01000805", "template_form_id": "00030764"},
                {"edid": "S2SRace_Control_male", "form_id": "01000804", "template_form_id": "00099999"}]
        calls = []

        def write(index, tpl, fid, data, out, plugin):
            calls.append((tpl, fid, plugin))
            return [f"{fid & 0xFFFFFF:08x}_color.dds"]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(face_fit, "baked_face_index", lambda names: {0x30764: {"color": ("a", "b")}}), \
                mock.patch.object(face_fit, "write_baked_face", write):
            done = H.bake_faces(npcs, d, d)
        self.assertEqual(done, {"S2SRace_Orc_male": 1, "S2SRace_Control_male": 0})   # no baked face: none
        self.assertEqual(calls, [(0x30764, 0x01000805, H.PLUGIN)])
        self.assertEqual(npcs[0]["baked_face_textures"], ["00000805_color.dds"])

    def test_key_limit(self):
        with tempfile.TemporaryDirectory():
            self.assertEqual(H.MAX_KEYS, 128)
            with self.assertRaises(SystemExit):
                H.main(["--skyrim-data", "x", "--starfield", "y", "--out", "z", "--races", "MoonRace"])


if __name__ == "__main__":
    unittest.main()
