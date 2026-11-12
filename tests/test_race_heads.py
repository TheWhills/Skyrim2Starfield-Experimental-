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
import unittest.mock

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
        (b"HDPT", h(b"HDPT"), [(b"EDID", Z("Human_Male_Teeth")), (b"MODL", Z("Actors\\Human\\Teeth.nif")),
                               (b"PNAM", I(9)), (b"MNAM", I(0x702))], 0x512),
        (b"MRPH", h(b"MRPH"), [(b"EDID", Z("HumanMaleTeethMorph")),
                               (b"TMPP", tcmp("Meshes\\Morphs\\Human\\Male\\Performance\\Teeth")),
                               (b"MOBC", struct.pack("<I", 21))], 0x702),
        (b"HDPT", h(b"HDPT"), [(b"EDID", Z("Human_Male_Beard_Goatee")), (b"MODL", Z("Actors\\Human\\Goatee.nif")),
                               (b"PNAM", I(4)), (b"RNAM", I(0x24A)), (b"MNAM", I(0x700))], 0x513),
        (b"FLST", h(b"FLST"), [(b"EDID", Z("HeadPartsHumanRace")), (b"LNAM", I(0x347D))], 0x24A),
        (b"FLST", h(b"FLST"), [(b"EDID", Z("OtherList")), (b"LNAM", I(0x347D))], 0x24B),
        (b"RACE", h(b"RACE"), [(b"EDID", Z("HumanRace")),
                               (b"FULL", I(0x5000)), (b"DAT2", struct.pack("<2f", 1.0, 0.98) + bytes(8)),
                               (b"MNAM", b""), (b"NAM0", b""), (b"NNAM", bytes(12)), (b"RPRM", I(0x800)),
                               (b"MPGN", Z("Nose")), (b"MPGM", Z("male_eu_md1_Nose")),
                               (b"MPGN", Z("Eyes")), (b"MPGM", Z("male_eu_md1_Eyes")), (b"FDSI", I(1)),
                               (b"FDSL", I(0x5001)), (b"FDSI", I(4)), (b"FDSL", I(0x5002)),
                               (b"INDX", I(0)), (b"HEAD", I(0x510)), (b"INDX", I(1)), (b"HEAD", I(0x512)),
                               (b"FNAM", b""), (b"NAM0", b""), (b"NNAM", bytes(12)),
                               (b"MPGN", Z("Nose")), (b"MPGM", Z("female_eu_md1_Nose")),
                               (b"FDSI", I(0)), (b"FDSL", I(0x5003)),
                               (b"INDX", I(0)), (b"HEAD", I(0x511))], 0x347D),
        (b"NPC_", h(b"NPC_"), [(b"EDID", Z("Player")), (b"ACBS", bytes(16)), (b"RNAM", I(0x347D)),
                               (b"DNAM", bytes(8)), (b"PNAM", I(0x510)), (b"PNAM", I(0x512))], 0x7),
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


def skyrim_esm(path, heights):
    """A Skyrim.esm with RACE records whose DATA carries (male, female) height at 16 / 20."""
    h = lambda t: struct.pack("<4sIII", t, 0, 0, 0) + bytes(4) + struct.pack("<HH", 44, 0)    # noqa: E731
    recs = [(b"RACE", h(b"RACE"), [(b"EDID", Z(r)), (b"DATA", bytes(16) + struct.pack("<2f", *hh) + bytes(20))],
             0x1300 + i) for i, (r, hh) in enumerate(heights.items())]
    with open(path, "wb") as fh:
        fh.write(sfplugin.build(recs, {"hedr_version": 1.7, "form_version": 44}, masters=()))


def _u(d):
    return struct.unpack("<I", bytes(d)[:4])[0]


def string_table(texts):
    """A Starfield / Skyrim .STRINGS table: count, data size, (id, offset) pairs, zero-terminated strings."""
    data, index = b"", b""
    for sid, t in texts.items():
        index += struct.pack("<II", sid, len(data))
        data += t.encode() + b"\0"
    return struct.pack("<II", len(texts), len(data)) + index + data


class PluginTests(unittest.TestCase):
    def test_formids_stable_across_rebuilds(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, H.LEDGER)
            ids = H.FormIds(path)
            a, b = ids.take("S2S_OrcRace"), ids.take("S2S_AltmerRace")
            self.assertEqual((a, b), (0x01000800, 0x01000801))
            self.assertEqual(ids.take("S2S_OrcRace"), a)
            ids.save()
            again = H.FormIds(path)                    # a rebuild that makes a new record first: no id moves
            self.assertEqual(again.take("S2S_NewThing"), 0x01000802)
            self.assertEqual(again.take("S2S_AltmerRace"), b)
            self.assertEqual(again.new, ["S2S_NewThing"])

    def test_race_conditions(self):
        def ctda(op, val, p1, or_=False):
            return struct.pack("<B3xfHHIIIIi", (op << 5) | int(or_), val, 69, 0, p1, 0, 0, 0, -1)
        subs = [(b"EDID", Z("IsHuman")), (b"CTDA", ctda(0, 1.0, 0x347D)), (b"CTDA", ctda(0, 1.0, 0x55))]
        out, n = H.with_race_conditions(subs, 0x347D, [0x01000900, 0x01000901])
        self.assertEqual(n, 1)
        c = [bytes(d) for s_, d in out if s_ == b"CTDA"]
        self.assertEqual([struct.unpack_from("<I", x, 12)[0] for x in c], [0x347D, 0x01000900, 0x01000901, 0x55])
        self.assertEqual([x[0] & 1 for x in c], [1, 1, 0, 0])                    # one OR group, then AND as before
        neg = [(b"CTDA", ctda(0, 0.0, 0x347D))]                                  # 'not human': and not ours either
        out, n = H.with_race_conditions(neg, 0x347D, [0x01000900])
        self.assertEqual([(x[0] & 1, struct.unpack_from("<I", x, 12)[0]) for _s, x in out],
                         [(0, 0x347D), (0, 0x01000900)])
        out, n = H.with_race_conditions([(b"CTDA", ctda(0, 0.0, 0x347D, or_=True))], 0x347D, [1])
        self.assertEqual(n, 0)                                                    # inside an OR group: left alone
        recs = [(b"CNDF", b"h", subs, 0x77), (b"IDLE", b"h", [(b"CTDA", ctda(0, 1.0, 0x55))], 0x78)]
        self.assertEqual([r[3] for r in H.race_condition_patches(recs, 0x347D, [0x01000900])], [0x77])

    def test_race_names(self):
        self.assertEqual(H.race_names("Orc, Altmer,HighElfRace,woodelf"), ["OrcRace", "HighElfRace", "HighElfRace",
                                                                           "WoodElfRace"])
        self.assertEqual(H.race_names("all"), list(H.CODES))
        with self.assertRaises(SystemExit):
            H.race_names("Khajiit")

    def test_with_heights(self):
        dat2 = struct.pack("<2f", 1.0, 0.98) + b"rest"
        out = H.with_heights([(b"EDID", Z("X")), (b"DAT2", dat2)], (1.045, 1.1))
        hm, hf = struct.unpack_from("<2f", out[1][1], 0)
        self.assertAlmostEqual(hm, 1.045, places=6)
        self.assertAlmostEqual(hf, 0.98 * 1.1, places=6)
        self.assertEqual(out[1][1][8:], b"rest")

    def test_swap_race_heads_per_sex(self):
        subs = [(b"MNAM", b""), (b"HEAD", I(5)), (b"HEAD", I(6)), (b"FNAM", b""), (b"HEAD", I(5)), (b"PNAM", I(5))]
        out = H.swap_race_heads(subs, {False: {5: 50}, True: {5: 51}})
        self.assertEqual([_u(d) for s_, d in out if s_ == b"HEAD"], [50, 6, 51])
        self.assertEqual(H.swap_parts(subs, {5: 9})[-1], (b"PNAM", I(9)))

    def test_face_parts_with_extras(self):
        recs = [(b"FLST", b"", [(b"EDID", Z("HeadPartsHumanRace")), (b"LNAM", I(1))], 0x24A),
                (b"HDPT", b"", [(b"EDID", Z("Brow")), (b"MODL", Z("b.nif")), (b"DATA", b"\x05"), (b"PNAM", I(6)),
                                (b"HNAM", I(0x22)), (b"RNAM", I(0x24A))], 0x21),
                (b"HDPT", b"", [(b"EDID", Z("BrowExtra")), (b"MODL", Z("e.nif")), (b"PNAM", I(0))], 0x22),
                (b"HDPT", b"", [(b"EDID", Z("Hair")), (b"MODL", Z("h.nif")), (b"PNAM", I(3)), (b"RNAM", I(0x24A))],
                 0x23),
                (b"HDPT", b"", [(b"EDID", Z("AlienBrow")), (b"MODL", Z("a.nif")), (b"PNAM", I(6)), (b"RNAM", I(9))],
                 0x24)]
        self.assertEqual(H.face_parts(recs), [(0x21, "Brow", "b.nif", [True], 6), (0x22, "BrowExtra", "e.nif",
                                                                                      [False, True], 0)])
        self.assertEqual(H.twin("S2S\\Races\\Orc\\MaleHead.nif"), "S2S\\Races\\Orc\\MaleHead_facebones.nif")

    def test_delocalize(self):
        tables = {"strings": {7: "Nose"}, "dlstrings": {9: "A race."}}
        subs = [(b"FDSL", I(7)), (b"DESC", I(9)), (b"FDSL", I(8)), (b"EDID", I(7)), (b"FULL", I(0))]
        self.assertEqual(H.delocalize(subs, tables), [(b"FDSL", Z("Nose")), (b"DESC", Z("A race.")), (b"FDSL", Z("")),
                                                      (b"EDID", I(7)), (b"FULL", I(0))])
        self.assertEqual(H.delocalize(subs, {}), subs)

    def test_presets_in_race_preset_lists(self):
        subs = [(b"MNAM", b""), (b"NAM0", b""), (b"NNAM", bytes(12)), (b"RPRM", I(1)), (b"MPGN", Z("Nose")),
                (b"FNAM", b""), (b"NAM0", b""), (b"NNAM", bytes(12)), (b"MPGN", Z("Nose"))]
        out = H.add_presets(subs, {False: [5], True: [6, 7]})
        self.assertEqual(out[3:5], [(b"RPRM", I(1)), (b"RPRM", I(5))])
        self.assertEqual(out[8:11], [(b"NNAM", bytes(12)), (b"RPRF", I(6)), (b"RPRF", I(7))])

    def test_with_races(self):
        subs = [(b"EDID", Z("HeadPartsHumanRace")), (b"LNAM", I(0x347D)), (b"LNAM", I(0x55))]
        out = H.with_races(subs, 0x347D, [0x900, 0x55])
        self.assertEqual(out, subs + [(b"LNAM", I(0x900))])                    # once, after the last entry
        self.assertIsNone(H.with_races([(b"EDID", Z("X")), (b"LNAM", I(0x55))], 0x347D, [0x900]))

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

    def test_new_race_thin_over_human(self):
        """2026-11-09 (owner: "yes" to the Orc race): a RACE copied from HumanRace, armor race and subgraph race
        HumanRace (as MannequinRace), our head part, its own phenotype per sex and only its keys added."""
        human = [(b"EDID", Z("HumanRace")), (b"FULL", I(77)), (b"KWDA", I(5)), (b"ANAM", Z("skel")),
                 (b"MNAM", b""), (b"MPGN", Z("Nose")), (b"MPGM", Z("male_eu_md1_Nose")),
                 (b"FMRI", I(0)), (b"FMRU", Z("male_as_md1")), (b"FMRN", Z("a")),
                 (b"FMRI", I(1)), (b"FMRU", Z("male_eu_md2")), (b"FMRN", Z("b")),
                 (b"FDSI", I(1)), (b"INDX", I(0)), (b"HEAD", I(0x510)),
                 (b"FNAM", b""), (b"MPGN", Z("Nose")), (b"MPGM", Z("female_eu_md1_Nose")),
                 (b"FMRI", I(0)), (b"FMRU", Z("female_eu_md1")), (b"FDSI", I(1)), (b"BSTT", Z("F_Skin")),
                 (b"SAKD", I(9)), (b"SGNM", Z("y.agx")), (b"SAPT", Z("common")), (b"SRAF", I(0)),
                 (b"SAKD", I(8)), (b"SGNM", Z("z.agx")), (b"SRAF", I(0)), (b"PTOP", I(1)),
                 (b"INDX", I(0)), (b"HEAD", I(0x511))]
        mannequin = [(b"EDID", Z("MannequinRace")), (b"KWDA", I(5)), (b"SRAC", I(0x347D)), (b"RNAM", I(0x347D))]
        out, rep = H.new_race((0x347D, human), mannequin, "Orc", {False: 0x900, True: 0x901},
                              {False: {"Nose": ["male_sk_or1_Nose"]}, True: {"Nose": ["female_sk_or1_Nose"]}},
                              {0x510: 1, 0x511: 1})
        sig = [s_ for s_, _d in out]
        d = dict(out)
        self.assertEqual(d[b"EDID"], Z("S2S_OrcRace"))
        self.assertEqual(d[b"FULL"], Z("Orc"))
        self.assertEqual((d[b"RNAM"], d[b"SRAC"]), (I(0x347D), I(0x347D)))
        # where the vanilla thin races carry RNAM: where HumanRace's subgraph entries began (after the skin tones)
        self.assertEqual(sig[sig.index(b"BSTT") + 1:sig.index(b"BSTT") + 4], [b"RNAM", b"SRAC", b"PTOP"])
        self.assertEqual(sig.count(b"RNAM"), 1)
        heads = [struct.unpack("<I", d_)[0] for s_, d_ in out if s_ == b"HEAD"]
        self.assertEqual(heads, [0x900, 0x901])
        mp = [bytes(d_).split(b"\0")[0].decode() for s_, d_ in out if s_ == b"MPGM"]
        self.assertEqual(mp, ["male_eu_md1_Nose", "male_sk_or1_Nose", "female_eu_md1_Nose", "female_sk_or1_Nose"])
        fm = [(struct.unpack("<I", d_)[0] if s_ == b"FMRI" else bytes(d_).split(b"\0")[0].decode())
              for s_, d_ in out if s_ in (b"FMRI", b"FMRU", b"FMRN")]
        self.assertEqual(fm, [0, "male_as_md1", "a", 1, "male_eu_md2", "b", 2, "male_sk_or1", "Orc",
                              0, "female_eu_md1", 1, "female_sk_or1"])           # a copy of the eu_md entry, named
        self.assertLess(sig.index(b"FDSI"), len(sig))
        self.assertEqual(rep["male"]["phenotype_index"], 2)
        self.assertEqual(rep["subgraph_race"], "HumanRace")
        for gone in (b"SAKD", b"SGNM", b"SAPT", b"SRAF"):                          # HumanRace's through SRAC only
            self.assertNotIn(gone, sig)
        self.assertEqual(rep["subgraph_subrecords_dropped"], 7)                      # two entries
        self.assertEqual(human[0], (b"EDID", Z("HumanRace")))                      # HumanRace itself untouched

    def test_end_to_end(self):
        v, t = strip_mesh()
        nv = len(v)
        m = vanilla_morph(nv, {"Nose": [0, 1, 2], "Eyes": [2, 3]})
        data = sfmorph.build(nv, m.keys, m.deltas)
        disp = {r: np.tile([0.0, 0.0, 0.004 * (i + 1)], (nv, 1)) for i, r in enumerate(H.CODES)}
        head = types.SimpleNamespace(vertices=v, triangles=t)
        fake_rp = types.SimpleNamespace(
            SF_MORPH="meshes/morphs/human/{sex}/chargen/{part}/morph.dat",
            race_transfer=lambda sky, sf, female, smooth, ff, **kw: (head, None, None, None, disp,
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
                                             "--races", "HighElfRace,OrcRace", "--race-head", "--new-races",
                                             "Orc", "--player-race", "Orc", "--race-shape", "blend"]), 0)
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
                self.assertEqual(len(rep["npcs"]), 8)            # control + 2 races, x 2; + the Orc race's NPCs
                orc = by["S2S_OrcRace"]
                self.assertEqual(dict(orc[1])[b"RNAM"], struct.pack("<I", 0x347D))
                onpc = dict(by["S2SRace_OrcRace_male"][1])
                self.assertEqual(struct.unpack("<I", onpc[b"RNAM"])[0], orc[2])
                self.assertIn("player.setrace xx", rep["new_races"]["OrcRace"]["setrace"])
                # race presets (RPRM / RPRF): the race's own NPCs after each sex's vanilla ones; the face dials
                # (FDSI / FDSL) untouched (2026-11-10: the first version added its presets there as dials)
                pre = [(s_, struct.unpack("<I", d_)[0]) for s_, d_ in orc[1] if s_ in (b"RPRM", b"RPRF")]
                om, of = by["S2SRace_OrcRace_male"][2], by["S2SRace_OrcRace_female"][2]
                self.assertEqual(pre, [(b"RPRM", 0x800), (b"RPRM", om), (b"RPRF", of)])
                sig_o = [s_ for s_, _d in orc[1]]
                self.assertEqual(sig_o.index(b"RPRF"), sig_o.index(b"NNAM", sig_o.index(b"FNAM")) + 1)
                self.assertEqual(sig_o.count(b"FDSI"), 3)
                # 2026-11-10 (owner: looks menu crash on facial hair): the head parts' valid-race list holds our
                # race too; since the races roadmap (A) every list holding HumanRace does
                fl = {r[3]: r[2] for r in sfplugin.records(os.path.join(out, H.PLUGIN), [b"FLST"])}
                self.assertEqual(sorted(fl), [0x24A, 0x24B])
                self.assertEqual([struct.unpack("<I", d_)[0] for s_, d_ in fl[0x24A] if s_ == b"LNAM"],
                                 [0x347D, orc[2]])
                self.assertEqual(rep["head_part_race_lists"], ["HeadPartsHumanRace 0000024A", "OtherList 0000024B"])
                # the player patch: the Player record (00000007) of the new race with our head part
                pp = sfplugin.records(os.path.join(out, "S2SOrcPlayer.esm"), [b"NPC_"])
                self.assertEqual([r[3] for r in pp], [0x7])
                pd = pp[0][2]
                self.assertEqual(struct.unpack("<I", dict(pd)[b"RNAM"])[0], orc[2])
                heads_ = [struct.unpack("<I", d_)[0] for s_, d_ in pd if s_ == b"PNAM"]
                self.assertIn(int(rep["head_parts"]["male"]["HDPT"], 16), heads_)
                self.assertNotIn(0x510, heads_)
                with open(os.path.join(out, "S2SOrcPlayer.esm"), "rb") as fh:
                    tes4 = fh.read(4096)
                self.assertIn(b"MAST\x0e\x00Starfield.esm\x00", tes4)                  # masters in order
                self.assertLess(tes4.index(b"Starfield.esm"), tes4.index(H.PLUGIN.encode()))
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

    def test_end_to_end_baked(self):
        """2026-11-10 (owner: "Why arent we adding the changes we made to this race"; the player of S2S_OrcRace kept
        a human face): the default --race-shape baked writes the race's shape into a head NIF + meshes of its own,
        the race uses that head part with HumanRace's chargen lists unchanged (no phenotype, no extra morph-group
        entries), its NPCs carry no race blends, and the player patch takes the race's head."""
        from fo4sf import nif as nifmod, sfmesh, sfnif
        from fo4sf.convert_static import mesh_file_path
        v, t = strip_mesh()
        nv = len(v)
        m = vanilla_morph(nv, {"Nose": [0, 1, 2], "Eyes": [2, 3]})
        data = sfmorph.build(nv, m.keys, m.deltas)
        disp = {r: np.tile([0.0, 0.0, 0.004 * (i + 1)], (nv, 1)) for i, r in enumerate(H.CODES)}
        head = types.SimpleNamespace(vertices=v, triangles=t)
        scale, raw = sfmesh.encode_positions([tuple(p) for p in v], margin=0.02)
        mesh = sfmesh.SfMesh(triangles=[tuple(x) for x in t], scale=scale, positions=raw, uv1=[(0, 0)] * nv,
                             normals=[sfmesh.encode_packed(0, 0, 1)] * nv, lods=[])
        sfmesh.build_meshlets(mesh)
        mesh_bytes = sfmesh.serialize(mesh)
        d_, f_ = mesh_file_path(mesh_bytes)
        shape = sfnif.SkinnedShape(b"Head", f"{d_}\\{f_}".encode(), len(t) * 3, nv, "x.mat", [b"C_Head"],
                                   [((0, 0, 0, 1), (1, 0, 0, 0, 1, 0, 0, 0, 1), (0, 0, 0), 1.0)])
        nif_bytes = nifmod.serialize(sfnif.build_skinned_nif(b"Head", [shape]))

        def vanilla(p, _d):
            low = p.replace("\\", "/").lower()
            if low.endswith(".nif"):
                return nif_bytes, low
            if low.endswith(".mesh"):
                return mesh_bytes, low
            return data, low
        fake_rp = types.SimpleNamespace(
            SF_MORPH="meshes/morphs/human/{sex}/chargen/{part}/morph.dat",
            race_transfer=lambda sky, sf, female, smooth, ff, **kw: (head, None, None, (1.0, np.eye(3), np.zeros(3)),
                                                               dict(disp),
                                                               {"transfer": "surface", "alignment": {"rms_m": 0.008}}))
        import face_fit
        saved = (sys.modules.get("race_probe"), face_fit.hkx_to_af.vanilla_file, H.bsa_archives)
        sys.modules["race_probe"] = fake_rp
        face_fit.hkx_to_af.vanilla_file = vanilla
        H.bsa_archives = lambda d: object()                 # a Skyrim source: the Orc mouth is converted
        import race_mouths
        saved_cm = race_mouths.convert_mouth
        calls = []

        def fake_mouth(read_sky, read_sf, sky_path, align, head_pts, head_skin, t_nif, t_morphs, base, material,
                       teeth_fb_nif=None):
            calls.append((sky_path, base, sorted(t_morphs)))
            return ({base + ".nif": b"nif"}, {"vertices": 348, "jaw_vertices": 120, "vanilla_vertices": 21,
                                              "model": base[len("meshes/"):].replace("/", "\\") + ".nif",
                                              "morph_folders": {"TMPP": "meshes\\morphs\\x\\performance"}})
        race_mouths.convert_mouth = fake_mouth
        try:
            with tempfile.TemporaryDirectory() as d:
                sf = os.path.join(d, "sf")
                os.makedirs(os.path.join(sf, "Data"))
                starfield_esm(os.path.join(sf, "Data", "Starfield.esm"))
                os.makedirs(os.path.join(sf, "Data", "Strings"))
                with open(os.path.join(sf, "Data", "Strings", "starfield_en.strings"), "wb") as fh:
                    fh.write(string_table({0x5000: "Human", 0x5001: "Forehead", 0x5002: "Ears", 0x5003: "Nose"}))
                out = os.path.join(d, "out")
                skyrim_esm(os.path.join(d, "Skyrim.esm"), {"ImperialRace": (1.0, 1.0), "OrcRace": (1.045, 1.045),
                                                            "WoodElfRace": (0.98, 1.0)})
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(H.main(["--skyrim-data", d, "--starfield", sf, "--out", out, "--races",
                                             "HighElfRace,OrcRace", "--new-races", "Orc,Bosmer", "--player-race",
                                             "Orc",
                                             "--symmetry", "none"]), 0)
                with open(os.path.join(out, "race_heads.json")) as fh:
                    rep = json.load(fh)
                nif_path = os.path.join(out, "meshes", "s2s", "races", "orc", "malehead.nif")
                self.assertTrue(os.path.isfile(nif_path))
                # 2026-11-10 (owner: shape pads locked): the _facebones twin the player is drawn from, and the facial
                # bone regions file under the race's name
                self.assertTrue(os.path.isfile(os.path.join(out, "meshes", "s2s", "races", "orc",
                                                            "malehead_facebones.nif")))
                self.assertTrue(rep["baked_heads"]["OrcRace"]["male"]["facebones_twin"])
                self.assertTrue(os.path.isfile(os.path.join(out, *face_fit.SF_REGIONS[True].replace(
                    "humanrace", "s2s_orcrace").split("/"))))
                self.assertTrue(os.path.isfile(os.path.join(out, "meshes", "s2s", "races", "orc", "parts",
                                                            "human_male_beard_goatee_m_facebones.nif")))
                with open(nif_path, "rb") as fh:
                    n = nifmod.parse(fh.read())
                g = next(sfnif.parse_bsgeometry(b) for i, b in enumerate(n.blocks) if n.type_of(i) == "BSGeometry")
                gpath = os.path.join(out, "geometries", *g.meshes[0].path.decode().split("\\")) + ".mesh"
                with open(gpath, "rb") as fh:
                    baked = sfmesh.parse(fh.read())
                z = np.array([sfmesh.decode_position(p, baked.scale)[2] for p in baked.positions])
                orc_i = list(H.CODES).index("OrcRace")
                self.assertLess(np.abs(z - 0.004 * (orc_i + 1)).max(), 1e-5)             # the Orc shape, baked
                self.assertEqual(rep["baked_heads"]["OrcRace"]["male"]["model"], "S2S\\Races\\Orc\\MaleHead.nif")
                recs = sfplugin.records(os.path.join(out, H.PLUGIN), [b"HDPT", b"NPC_", b"RACE"])
                by = {sfplugin.edid(s): (t_, s, fid) for t_, _h, s, fid in recs}
                oh = by["S2S_OrcRace_male_Head"]
                self.assertEqual(H.text_of(dict(oh[1])[b"MODL"]), "S2S\\Races\\Orc\\MaleHead.nif")
                self.assertEqual(dict(oh[1])[b"MNAM"], I(0x700))                     # the vanilla morph record
                orc = by["S2S_OrcRace"][1]
                # the face dial labels as text (2026-11-10: copied string ids showed as "U", "Z")
                self.assertEqual([bytes(d_) for s_, d_ in orc if s_ == b"FDSL"], [Z("Forehead"), Z("Ears"), Z("Nose")])
                self.assertEqual(rep["localized_strings"], {"strings": 4})
                mp = [bytes(d_).split(b"\0")[0].decode() for s_, d_ in orc if s_ == b"MPGM"]
                self.assertEqual(mp, ["male_eu_md1_Nose", "male_eu_md1_Eyes", "female_eu_md1_Nose"])  # as HumanRace's
                self.assertFalse([d_ for s_, d_ in orc if s_ == b"FMRU" and b"_sk_" in bytes(d_)])  # no phenotype
                heads_ = [struct.unpack("<I", d_)[0] for s_, d_ in orc if s_ == b"HEAD"]
                self.assertIn(oh[2], heads_)
                self.assertEqual(rep["new_races"]["OrcRace"]["shape"], "baked into its head model")
                # 2026-11-10: baked races need not be in --races (Bosmer was not); heights from Skyrim
                self.assertIn("form_id", rep["new_races"]["WoodElfRace"])
                hm, hf = struct.unpack_from("<2f", dict(orc)[b"DAT2"], 0)
                self.assertAlmostEqual(hm, 1.045, places=5)
                self.assertAlmostEqual(hf, 0.98 * 1.045, places=5)
                self.assertEqual(rep["new_races"]["WoodElfRace"]["height_factor"], {"male": 0.98, "female": 1.0})
                on = by["S2SRace_OrcRace_male"][1]
                self.assertNotIn(b"BMPN", [s_ for s_, _d in on])
                self.assertIn(struct.pack("<I", oh[2]), [d_ for s_, d_ in on if s_ == b"PNAM"])
                # 2026-11-10 (owner's Orc NPCs showed a human head): the copied test NPC kept its own (blend) head
                # part ahead of the race's; only the race's Face part may remain
                face_ids = {fid for _t, _h, s_, fid in recs if _t == b"HDPT" and dict(s_).get(b"PNAM") == I(1)}
                face_ids |= {by[e][2] for e in by if e.startswith("S2S_SkyrimRaces_")}
                self.assertEqual([_u(d_) for s_, d_ in on if s_ == b"PNAM" and _u(d_) in face_ids], [oh[2]])
                # the face parts: a baked copy per sex on the race's own list; the vanilla one for humans only
                recs2 = sfplugin.records(os.path.join(out, H.PLUGIN), [b"HDPT", b"FLST"])
                by2 = {sfplugin.edid(s_): (s_, fid) for _t, _h, s_, fid in recs2}
                self.assertIn("S2S_OrcRace_Human_Male_Beard_Goatee_M", by2, json.dumps(rep.get("baked_heads"))[:3000])
                bm = dict(by2["S2S_OrcRace_Human_Male_Beard_Goatee_M"][0])
                self.assertIn("S2S_OrcRace_Human_Male_Beard_Goatee_F", by2)
                self.assertEqual(H.text_of(bm[b"MODL"]), "S2S\\Races\\Orc\\Parts\\Human_Male_Beard_Goatee_M.nif")
                self.assertEqual(_u(bm[b"RNAM"]), by2["S2S_HeadPartsOrcRace"][1])
                self.assertNotIn(b"DATA", bm)
                self.assertEqual([_u(d_) for s_, d_ in by2["S2S_HeadPartsOrcRace"][0] if s_ == b"LNAM"],
                                 [by["S2S_OrcRace"][2]])
                van = dict(by2["Human_Male_Beard_Goatee"][0])                       # override of 0x513
                self.assertEqual(by2["Human_Male_Beard_Goatee"][1], 0x513)
                self.assertEqual(_u(van[b"RNAM"]), by2["S2S_HeadPartsHumanOnly"][1])
                self.assertEqual([_u(d_) for s_, d_ in by2["S2S_HeadPartsHumanOnly"][0] if s_ == b"LNAM"], [0x347D])
                self.assertTrue(os.path.isfile(os.path.join(out, "meshes", "s2s", "races", "orc", "parts",
                                                            "human_male_beard_goatee_m.nif")))
                self.assertEqual(rep["new_races"]["OrcRace"]["face_parts"], {"male": 2, "female": 1}, rep["mouths"])
                pp = sfplugin.records(os.path.join(out, "S2SOrcPlayer.esm"), [b"NPC_"])
                pheads = [struct.unpack("<I", d_)[0] & 0xFFFFFF for s_, d_ in pp[0][2] if s_ == b"PNAM"]
                self.assertIn(oh[2] & 0xFFFFFF, pheads)
                # the Orc mouth (race_mouths, here faked): its own teeth part + morph record on the race's list,
                # in the race's defaults and on the player instead of the vanilla teeth
                self.assertEqual([c[1] for c in calls], ["meshes/s2s/races/orc/mouth_m"])
                self.assertIn("no HDPT Human_Female_Teeth", rep["mouths"]["OrcRace female"]["error"])
                self.assertEqual(calls[0][2], ["TMPP"])
                recs3 = sfplugin.records(os.path.join(out, H.PLUGIN), [b"HDPT", b"MRPH", b"RACE"])
                by3 = {sfplugin.edid(s_): (s_, fid) for _t, _h, s_, fid in recs3}
                mouth = dict(by3["S2S_OrcRace_Mouth_M"][0])
                self.assertEqual(H.text_of(mouth[b"MODL"]), "s2s\\races\\orc\\mouth_m.nif")
                self.assertEqual(_u(mouth[b"MNAM"]), by3["S2S_OrcRace_Mouth_M_Morph"][1])
                mm = dict(by3["S2S_OrcRace_Mouth_M_Morph"][0])
                self.assertEqual(H.text_of(mm[b"TMPP"]), "Meshes\\morphs\\x\\performance")
                self.assertEqual(_u(mm[b"MOBC"]), 348)
                rheads = [_u(d_) for s_, d_ in by3["S2S_OrcRace"][0] if s_ == b"HEAD"]
                self.assertIn(by3["S2S_OrcRace_Mouth_M"][1], rheads)
                self.assertNotIn(0x512, rheads)
                self.assertIn(by3["S2S_OrcRace_Mouth_M"][1] & 0xFFFFFF, [struct.unpack("<I", d_)[0] & 0xFFFFFF
                                                                          for s_, d_ in pp[0][2] if s_ == b"PNAM"])
                self.assertEqual(rep["mouths"]["OrcRace male"]["vertices"], 348)
                # the FormID ledger: kept in --out, the race's id in it (a rebuild reuses it)
                with open(os.path.join(out, H.LEDGER)) as fh:
                    led = json.load(fh)["ids"]
                self.assertEqual(int(led["S2S_OrcRace"], 16), by["S2S_OrcRace"][2] & 0xFFFFFF)
                self.assertIn("S2S_OrcRace", rep["formids"]["new"])
        finally:
            if saved[0] is None:
                sys.modules.pop("race_probe", None)
            else:
                sys.modules["race_probe"] = saved[0]
            face_fit.hkx_to_af.vanilla_file, H.bsa_archives = saved[1], saved[2]
            race_mouths.convert_mouth = saved_cm

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


class SkinToneTests(unittest.TestCase):
    """2026-11-11 (owner: test the Orc's skin tone before building every race)."""

    def test_face_tone(self):
        """2026-11-12: the Orc NPCs' baked faces stayed human, then came out lighter than the body; their colour
        texture now gets the median colour of the race's own face tone texture."""
        from fo4sf import skintone
        face = np.full((4, 4, 4), 255, np.uint8)
        face[..., :3] = (198, 176, 168)
        face[0, 0, :3] = (150, 120, 110)
        conv = H.face_tone((89, 113, 92))
        out = skintone.decode_dds(conv(skintone.raw_dds(face)))
        self.assertEqual(out[1, 1, :3].tolist(), [89, 113, 92])      # median -> the target
        self.assertLess(int(out[0, 0, 1]), 113)                       # detail kept
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "textures", "s2s", "races", "orc", "face")
            os.makedirs(p)
            with open(os.path.join(p, "female_sk4_color.dds"), "wb") as fh:
                fh.write(skintone.raw_dds(face))
            got = H.face_targets({"textures/s2s/races/orc/face/female_sk4_color.dds": [1, 2, 3],
                                  "textures/s2s/races/orc/body/male_sk4_color.dds": [1, 2, 3]}, d, kind="face")
        self.assertEqual(got, {True: (198, 176, 168)})

    def test_human_faces(self):
        h = bytes(24)
        recs = [(b"FLST", h, [(b"EDID", Z(H.HUMAN_PART_LIST)), (b"LNAM", I(0x347D))], 0x24A024),
                (b"HDPT", h, [(b"EDID", Z("HumanMaleHead")), (b"PNAM", I(1)), (b"RNAM", I(0x24A024))], 0x10),
                (b"HDPT", h, [(b"EDID", Z("Brows")), (b"PNAM", I(3)), (b"RNAM", I(0x24A024))], 0x11),
                (b"HDPT", h, [(b"EDID", Z("OtherHead")), (b"PNAM", I(1)), (b"RNAM", I(0x999))], 0x12)]
        self.assertEqual(H.human_faces(recs), {0x10})

    def test_bake_faces_tones_race_npcs_only(self):
        import face_fit
        calls = []

        def fake_write(index, tpl, fid, data, out, plugin, colour=None):
            calls.append((fid, colour))
            return ["x_color.dds"]
        npcs = [{"template_form_id": "10", "form_id": "1000894", "edid": "a", "race": "OrcRace", "sex": "male",
                 "race_record": "S2S_OrcRace"},
                {"template_form_id": "10", "form_id": "1000804", "edid": "b", "race": "OrcRace", "sex": "female"}]
        with tempfile.TemporaryDirectory() as d, \
                unittest.mock.patch.object(face_fit, "baked_face_index", lambda names: {0x10: {}}), \
                unittest.mock.patch.object(face_fit, "write_baked_face", fake_write):
            H.bake_faces(npcs, d, d, {"OrcRace": lambda female: ("tone", female)})
        self.assertEqual(calls, [(0x1000894, ("tone", False)), (0x1000804, None)])
        self.assertTrue(npcs[0]["baked_face_tone"])
        calls.clear()
        with tempfile.TemporaryDirectory() as d, \
                unittest.mock.patch.object(face_fit, "baked_face_index", lambda names: {0x10: {}}), \
                unittest.mock.patch.object(face_fit, "write_baked_face", fake_write):
            done = H.bake_faces(npcs, d, d, {"OrcRace": lambda female: ("tone", female)}, ("OrcRace",))
        self.assertEqual(calls, [(0x1000804, None)])                  # the race NPC gets none (runtime face)
        self.assertEqual(done["a"], 0)

    def test_player_patch_both_heads(self):
        """2026-11-12: Body Type 2 gave the player a human female head; the patch lists both sexes' race heads."""
        acbs = struct.pack("<I", 0) + bytes(20)
        subs = [(b"EDID", Z("Player")), (b"ACBS", acbs), (b"RNAM", I(0x347D)), (b"PNAM", I(0x10)), (b"PNAM", I(0x20))]
        out = H.player_patch(subs, 0x1000811, {False: 0x100080F, True: 0x1000810}, {0x10: 1, 0x20: 3})
        p = [_u(d) for x, d in out if x == b"PNAM"]
        self.assertEqual(sorted(p), [0x20, 0x100080F, 0x1000810])
        self.assertEqual(_u(dict(out)[b"RNAM"]), 0x1000811)

    def test_with_ston(self):
        self.assertEqual(H.with_ston([(b"EDID", b"x\0"), (b"STON", b"\x02"), (b"HCOL", b"h\0")], 13)[1], (b"STON", b"\x0d"))
        self.assertEqual(H.with_ston([(b"EDID", b"x\0"), (b"HCOL", b"h\0")], 9),
                         [(b"EDID", b"x\0"), (b"STON", b"\x09"), (b"HCOL", b"h\0")])

    def test_write_skin_tones(self):
        from fo4sf import skintone
        light = np.full((4, 4, 4), 200, np.uint8)
        dark = np.full((4, 4, 4), 60, np.uint8)
        files = {"v/b0.dds": skintone.raw_dds(dark), "v/b1.dds": skintone.raw_dds(light),
                 "v/f0.dds": skintone.raw_dds(light)}
        jobs = {"textures/s2s/races/orc/body/male_sk0_color.dds": ("v/b0.dds", "body", False, 0),
                "textures/s2s/races/orc/body/male_sk1_color.dds": ("v/b1.dds", "body", False, 1),
                "textures/s2s/races/orc/face/female_sk0_color.dds": ("v/f0.dds", "face", True, 0)}
        ramps = {False: [(89, 113, 92), (41, 47, 36)], True: [(94, 138, 124)]}
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()), \
                unittest.mock.patch.object(H, "find_texconv", lambda tc="": ""):
            done = H.write_skin_tones(jobs, ramps, files.__getitem__, d)
            sk0 = skintone.decode_dds(open(os.path.join(d, "textures", "s2s", "races", "orc", "body",
                                                        "male_sk0_color.dds"), "rb").read())
        # slot 0 = the lightest vanilla texture with the lightest Orc colour (tones run light to dark)
        self.assertEqual(done["textures/s2s/races/orc/body/male_sk0_color.dds"], [89, 113, 92])
        self.assertEqual(done["textures/s2s/races/orc/body/male_sk1_color.dds"], [41, 47, 36])
        self.assertEqual(done["textures/s2s/races/orc/face/female_sk0_color.dds"], [94, 138, 124])
        self.assertEqual(sk0[0, 0, :3].tolist(), [89, 113, 92])
        self.assertFalse(os.path.exists(os.path.join(d, "_skin_tone_staging")))

    def test_relative_and_test_modes(self):
        from fo4sf import skintone
        light = np.full((4, 4, 4), 200, np.uint8)
        files = {"v/b0.dds": skintone.raw_dds(light), "v/b1.dds": skintone.raw_dds(light[:, :, :] // 2 + 1)}
        jobs = {"t/body/male_sk0_color.dds": ("v/b0.dds", "body", False, 0),
                "t/body/male_sk1_color.dds": ("v/b1.dds", "body", False, 1)}
        ramps, human = {False: [(89, 113, 92), (41, 47, 36)]}, {False: [(89, 113, 92), (82, 61, 48)]}

        def run(**kw):
            with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()), \
                    unittest.mock.patch.object(H, "find_texconv", lambda tc="": ""):
                H.write_skin_tones(jobs, ramps, files.__getitem__, d, **kw)
                return [skintone.decode_dds(open(os.path.join(d, "t", "body", f"male_sk{k}_color.dds"), "rb").read())
                        for k in (0, 1)]
        rel = run(human=human)
        self.assertEqual(rel[0][0, 0, :3].tolist(), [200, 200, 200])      # race == human colour: lightest kept
        self.assertGreater(int(rel[1][0, 0, 1]), int(rel[1][0, 0, 0]))   # Orc vs dark human: greener
        test = run(human=human, test=True)
        self.assertEqual([t[0, 0, :3].tolist() for t in test], [[0, 255, 0], [255, 255, 255]])


if __name__ == "__main__":
    unittest.main()


class ChargenOptionListTests(unittest.TestCase):
    def test_copies_added_to_chargen_lists(self):
        """2026-11-11: the looks menu gave the Orc player human teeth even on a new game; its parts come from
        HeadPartsChargenOptionsMale / Female, which now carry every race copy of their entries."""
        h = bytes(24)
        recs = [(b"FLST", h, [(b"EDID", Z("HeadPartsChargenOptionsMale")), (b"LNAM", I(0x10)), (b"LNAM", I(0x11))],
                 0x3D9AF),
                (b"FLST", h, [(b"EDID", Z("HeadPartsChargenOptionsFemale")), (b"LNAM", I(0x20))], 0x3D9B0),
                (b"FLST", h, [(b"EDID", Z("Other")), (b"LNAM", I(0x10))], 0x99)]
        copies = {"OrcRace": {False: {0x10: 0x1000872, 0x11: 0x1000813}, True: {0x20: 0x1000874}},
                  "HighElfRace": {False: {0x10: 0x1000900}}}
        out = H.chargen_option_lists(recs, copies)
        got = {sfplugin.edid(s): [_u(d) for x, d in s if x == b"LNAM"] for _t, _h, s, _f in out}
        self.assertEqual(got, {"HeadPartsChargenOptionsMale": [0x10, 0x11, 0x1000872, 0x1000900, 0x1000813],
                               "HeadPartsChargenOptionsFemale": [0x20, 0x1000874]})
        self.assertEqual({f for _t, _h, _s, f in out}, {0x3D9AF, 0x3D9B0})    # overrides, same FormIDs


class PresetCopyTests(unittest.TestCase):
    def test_presets_become_race_copies(self):
        """2026-11-11: a new game's Orc player kept the first chargen preset's human teeth; the race's presets are now
        copies on the race with its head and part copies."""
        h = bytes(24)
        npcs = {0x50560: (h, [(b"EDID", Z("ChargenPresetMale02")), (b"RNAM", I(0x347D)),
                              (b"PNAM", I(0x24A022)), (b"PNAM", I(0x24A03D)), (b"PNAM", I(0x13EB51))]),
                0x50566: (h, [(b"EDID", Z("ChargenPresetFemale01")), (b"RNAM", I(0x347D)), (b"PNAM", I(0x12201))])}
        rsubs = [(b"MNAM", b""), (b"RPRM", I(0x50560)), (b"RPRM", I(0x999)), (b"FNAM", b""), (b"RPRF", I(0x50566))]
        part_types = {0x24A022: 1, 0x12201: 1, 0x24A03D: 9, 0x13EB51: 3}
        n = iter(range(0x1000900, 0x1000a00))
        out, recs = H.race_preset_copies(rsubs, npcs, "Orc", 0x1000811, {False: 0x100080F, True: 0x1000810},
                                         part_types, {False: {0x24A03D: 0x1000872}}, lambda e: next(n))
        self.assertEqual([_u(d) for s, d in out if s in (b"RPRM", b"RPRF")], [0x1000900, 0x999, 0x1000901])
        male = dict((sfplugin.edid(s), s) for _t, _h, s, _f in recs)["S2S_OrcRace_ChargenPresetMale02"]
        self.assertEqual(_u(dict(male)[b"RNAM"]), 0x1000811)
        self.assertEqual(sorted(_u(d) for s, d in male if s == b"PNAM"), [0x13EB51, 0x100080F, 0x1000872])

    def test_baked_head_presets_lose_blends(self):
        """2026-11-12: presets' human morph blends turned our baked Orc head back into a human face."""
        h = bytes(24)
        npcs = {0x50566: (h, [(b"EDID", Z("ChargenPresetFemale01")), (b"RNAM", I(0x347D)), (b"PNAM", I(0x12201)),
                              (b"BMPN", Z("female_eu_md1_Mouth")), (b"BMPV", I(0)), (b"FMSI", I(3))])}
        rsubs = [(b"FNAM", b""), (b"RPRF", I(0x50566))]
        n = iter(range(0x1000900, 0x1000a00))
        for drop, want in ((False, 1), (True, 0)):
            _out, recs = H.race_preset_copies(rsubs, npcs, "Orc", 0x1000811, {True: 0x1000810}, {0x12201: 1}, {},
                                              lambda e: next(n), drop_blends=drop)
            s = recs[0][2]
            self.assertEqual(sum(1 for x, _d in s if x == b"BMPN"), want)
            self.assertEqual(sum(1 for x, _d in s if x == b"BMPV"), want)
            self.assertIn(b"FMSI", [x for x, _d in s])                  # face dials kept


class ExtraPartTests(unittest.TestCase):
    def test_with_extra_part(self):
        """--mouth-on-head: the race head carries the mouth as an extra part, after its type and other extras."""
        subs = [(b"EDID", Z("H")), (b"PNAM", I(1)), (b"HNAM", I(5)), (b"RNAM", I(9))]
        out = H.with_extra_part(subs, 0x1000872)
        self.assertEqual([s for s, _d in out], [b"EDID", b"PNAM", b"HNAM", b"HNAM", b"RNAM"])
        self.assertEqual(_u(out[3][1]), 0x1000872)
        self.assertEqual([s for s, _d in H.with_extra_part(subs[:2], 7)], [b"EDID", b"PNAM", b"HNAM"])


class MouthTypeTests(unittest.TestCase):
    def test_mouth_type_override(self):
        """--mouth-type: the race mouth part with another HDPT type (the player's teeth colour may swap a Teeth
        part's material)."""
        h = bytes(24)
        by = {0x24A03D: (h, [(b"EDID", Z("Human_Male_Teeth")), (b"MODL", Z("Teeth.nif")), (b"DATA", b"\x03"),
                             (b"PNAM", I(9)), (b"RNAM", I(0x24A024))])}
        info = {"part_fid": 0x24A03D, "mrph_fid": 0x999, "model": "s2s\\mouth_m.nif", "morph_folders": {}}
        n = iter(range(0x1000900, 0x1000a00))
        for t, want in ((None, 9), (0, 0)):
            out = H.mouth_records(by, info, "Orc", False, 0x1000812, {}, lambda e: next(n), t)
            hd = next(s for sig, _h, s, _f in out if sig == b"HDPT")
            self.assertEqual(_u(dict(hd)[b"PNAM"]), want)
