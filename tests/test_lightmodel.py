"""fo4sf.lightmodel, the Skyrim lighting fields it reads (XCLL directional ambient / rotation / fade, LGTM DALC, REFR
XLIG) and scripts/interior/light_audit.py, on synthetic data (2026-11-21, owner: "its inconsistently lit")."""
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import lightmodel as LM, skyriminterior  # noqa: E402
from test_fo4land import grup, rec  # noqa: E402
import light_audit  # noqa: E402

UP = (0.0, 0.0, 1.0)


def light(radius=700.0, color=(255, 255, 255), fade=1.0, **kw):
    return {"radius": radius, "color": list(color), "fade": fade, **kw}


class SkyrimPointTest(unittest.TestCase):
    def test_quadratic_window_no_inverse_square(self):
        L = light(radius=700.0, color=(255, 128, 0), fade=1.5)
        half = LM.skyrim_point(L, (0, 0, 350), (0, 0, 0), UP)          # d = r / 2: 1 - 1/4
        self.assertAlmostEqual(half[0], 1.5 * 0.75, places=6)
        self.assertAlmostEqual(half[1], 128 / 255 * 1.5 * 0.75, places=6)
        near = LM.skyrim_point(L, (0, 0, 70), (0, 0, 0), UP)[0]       # d = r / 10
        self.assertAlmostEqual(near / half[0], 0.99 / 0.75, places=6)   # gentle: not 25x as inverse square would be
        self.assertEqual(LM.skyrim_point(L, (0, 0, 700), (0, 0, 0), UP), (0.0, 0.0, 0.0))

    def test_facing_fade_offset_and_off_by_default(self):
        self.assertEqual(LM.skyrim_point(light(), (0, 0, -100), (0, 0, 0), UP), (0.0, 0.0, 0.0))   # light below
        side = LM.skyrim_point(light(), (100, 0, 100), (0, 0, 0), UP)[0]
        top = LM.skyrim_point(light(), (0, 0, 141.42), (0, 0, 0), UP)[0]
        self.assertAlmostEqual(side / top, 2 ** -0.5, places=3)
        self.assertAlmostEqual(LM.skyrim_point(light(fade=1.0, ref_fade_delta=0.5), (0, 0, 350), (0, 0, 0))[0],
                               1.5 * 0.75, places=6)
        self.assertEqual(LM.skyrim_point(light(off_by_default=True), (0, 0, 10), (0, 0, 0)), (0.0, 0.0, 0.0))


class AmbientTest(unittest.TestCase):
    def amb6(self, **over):
        d = {a: [60, 60, 60] for a in LM.AXES}
        d.update(over)
        return d

    def test_uniform_six_colours_are_the_ambient(self):
        a = LM.skyrim_ambient({"directional_ambient": self.amb6()}, UP)
        self.assertAlmostEqual(a[0], 60 / 255, places=6)

    def test_bright_ceiling_lights_upward_faces_more(self):
        lit = {"directional_ambient": self.amb6(**{"z+": [120, 120, 120], "z-": [0, 0, 0]})}
        up = LM.skyrim_ambient(lit, UP)[0]
        down = LM.skyrim_ambient(lit, (0, 0, -1))[0]
        self.assertGreater(up, down)
        self.assertAlmostEqual(up, (60 * 4 + 120) / 6 / 255 + 60 / 255, places=6)

    def test_single_ambient_when_no_six(self):
        self.assertAlmostEqual(LM.skyrim_ambient({"ambient": [51, 51, 51]})[0], 0.2, places=6)

    def test_directional_from_rotation(self):
        overhead = {"directional": [255, 255, 255], "directional_fade": 1.0, "directional_rotation": [0, 90]}
        self.assertAlmostEqual(LM.skyrim_directional(overhead, UP)[0], 1.0, places=6)
        level = dict(overhead, directional_rotation=[0, 0])
        self.assertAlmostEqual(LM.skyrim_directional(level, UP)[0], 0.0, places=6)

    def test_parts_add_up(self):
        lt = {"ambient": [51, 51, 51], "directional": [0, 0, 0]}
        r = LM.skyrim_light_at(lt, [(light(), (0, 0, 350))], (0, 0, 0))
        self.assertAlmostEqual(r["total"][0], 0.2 + 0.75, places=6)


class StarfieldHypothesisTest(unittest.TestCase):
    def test_inverse_square_with_window(self):
        a = LM.starfield_point(4000, 8.0, (0, 0, 70), (0, 0, 0))       # 1 m
        b = LM.starfield_point(4000, 8.0, (0, 0, 140), (0, 0, 0))      # 2 m
        self.assertAlmostEqual(a, 4000 / (4 * 3.141592653589793) * (1 - (1 / 8) ** 4) ** 2, places=3)
        self.assertAlmostEqual(a / b, 4 * (1 - (1 / 8) ** 4) ** 2 / (1 - (2 / 8) ** 4) ** 2, places=6)
        self.assertEqual(LM.starfield_point(4000, 8.0, (0, 0, 8 * 70), (0, 0, 0)), 0.0)


XCLL_ROT = (45, 60)


def xcll_full(ambient=(30, 30, 30), inherits=0):
    d = bytes(ambient) + b"\0" + bytes([200, 150, 100, 0]) + bytes(4) + struct.pack("<2f", 0.0, 1.0)
    d += struct.pack("<ii", *XCLL_ROT) + struct.pack("<3f", 0.8, 0.0, 1.0)
    d += b"".join(bytes([10 * (i + 1)] * 3) + b"\0" for i in range(6)) + bytes(4) + struct.pack("<f", 1.0)
    d += bytes(4) + struct.pack("<3fI", 0.0, 1500.0, 3000.0, inherits)
    assert len(d) == 92
    return (b"XCLL", d)


LIGH_B, WALL_B, CELL_A, CELL_B, TPL = 0x110, 0x100, 0x2000, 0x2100, 0x5000


def plugin():
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.71, 0, 0x800))])
    stat = grup(b"STAT", 0, [rec(b"STAT", WALL_B, [(b"EDID", b"Wall\0"), (b"MODL", b"Wall.nif\0")])])
    tdata = struct.pack("<iI4BI6fIf", -1, 512, 255, 160, 80, 0, 0, 1.0, 90.0, 0.0, 0.2, 0.3, 0.1, 0, 0.0)
    ligh = grup(b"LIGH", 0, [rec(b"LIGH", LIGH_B, [(b"EDID", b"Candle\0"), (b"DATA", tdata),
                                                   (b"FNAM", struct.pack("<f", 1.0))])])
    tdat = bytes([5, 6, 7, 0]) + bytes([1, 2, 3, 0]) + bytes(12) + struct.pack("<ii", 10, 20) + struct.pack("<f", 0.5)
    dalc = b"".join(bytes([100 + i] * 3) + b"\0" for i in range(6))
    lgtm = grup(b"LGTM", 0, [rec(b"LGTM", TPL, [(b"EDID", b"Tpl\0"), (b"DATA", tdat + bytes(40)), (b"DALC", dalc)])])

    def refr(fid, base, pos, extra=()):
        return rec(b"REFR", fid, [(b"NAME", struct.pack("<I", base)), (b"DATA", struct.pack("<6f", *pos, 0, 0, 0)),
                                  *extra])

    def cell(fid, edid, children, extra):
        c = rec(b"CELL", fid, [(b"EDID", edid.encode() + b"\0"), (b"DATA", b"\x01\x00"), *extra])
        return [c, grup(fid, 6, [grup(fid, 9, children)])]
    a = cell(CELL_A, "OwnLight", [refr(0x2001, WALL_B, (0, 0, 0)),
                                  refr(0x2002, LIGH_B, (0, 0, 100), [(b"XLIG", struct.pack("<4f", 0, 0.4, 0, 0))])],
             [xcll_full()])
    b = cell(CELL_B, "TemplateLight", [refr(0x2101, WALL_B, (0, 0, 0))],
             [xcll_full(inherits=0x1 | 0x20), (b"LTMP", struct.pack("<I", TPL))])
    cells = grup(b"CELL", 0, [grup(0, 2, [grup(0, 3, a + b)])])
    return tes4 + stat + ligh + lgtm + cells


class SkyrimFieldsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.esm = os.path.join(self.tmp.name, "Skyrim.esm")
        with open(self.esm, "wb") as f:
            f.write(plugin())

    def tearDown(self):
        self.tmp.cleanup()

    def test_xcll_directional_ambient_rotation_fade(self):
        lt = skyriminterior.export_interior(self.esm, "OwnLight")["lighting"]
        self.assertEqual(lt["directional_rotation"], list(XCLL_ROT))
        self.assertAlmostEqual(lt["directional_fade"], 0.8, places=5)
        self.assertEqual(lt["directional_ambient"]["x+"], [10, 10, 10])
        self.assertEqual(lt["directional_ambient"]["z-"], [60, 60, 60])

    def test_inherited_from_template_dalc(self):
        lt = skyriminterior.export_interior(self.esm, "TemplateLight")["lighting"]
        self.assertEqual(lt["ambient"], [5, 6, 7])
        self.assertEqual(lt["directional_ambient"]["x+"], [100, 100, 100])
        self.assertEqual(lt["directional_rotation"], [10, 20])
        self.assertEqual(lt["directional"], [200, 150, 100])                # not inherited (0x2 not set)
        self.assertAlmostEqual(lt["directional_fade"], 0.8, places=5)       # nor this (0x40)
        self.assertIn("directional_ambient", lt["from_template"])

    def test_xlig_fade_offset_recorded(self):
        exp = skyriminterior.export_interior(self.esm, "OwnLight")
        L = next(r["light"] for r in exp["refs"] if r["type"] == "Light")
        self.assertAlmostEqual(L["ref_fade_delta"], 0.4, places=5)

    def test_audit_runs_on_the_plugin(self):
        out = os.path.join(self.tmp.name, "audit.json")
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            light_audit.main(["--skyrim", self.esm, "--cell", "OwnLight", "--cell", "TemplateLight", "--out", out])
        self.assertIn("OwnLight", buf.getvalue())
        import json
        with open(out, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual([c["cell"] for c in data["cells"]], ["OwnLight", "TemplateLight"])
        own = data["cells"][0]
        self.assertEqual((own["skyrim"]["lights"], own["ours"]["placed"]), (1, 1))
        self.assertGreater(own["skyrim_light"]["share_points"], 0)


class PlacedLightsTest(unittest.TestCase):
    def ref(self, pos, radius=512.0, fade=1.0, fk="A"):
        return {"type": "Light", "pos": list(pos), "formkey": fk, "base_editor_id": "L" + fk,
                "light": light(radius=radius, fade=fade)}

    def test_merge_and_lumens_follow_pluginspike(self):
        s = dict(light_audit.DEFAULTS)
        refs = [self.ref((0, 0, 0), fk="A"), self.ref((50, 0, 0), fk="B"),            # 0.7 m away: merged
                self.ref((700, 0, 0), radius=4 * 560.0, fk="C"), self.ref((1400, 0, 0), radius=140.0, fk="D")]
        placed, merged = light_audit.placed_lights(refs, s)
        self.assertEqual([r["formkey"] for r, _r, _l in placed], ["A", "C", "D"])
        self.assertEqual([(m["formkey"], i["formkey"]) for m, i in merged], [("B", "A")])
        lm = {r["formkey"]: (rad, lumens) for r, rad, lumens in placed}
        self.assertEqual(lm["A"], (512 / 70, 8000.0))                   # power 2 x template 4000
        self.assertEqual(lm["C"], (32.0, 64000.0))                      # (32 / 8)^2 x 2 = 32 -> capped at 16x
        self.assertEqual(lm["D"][1], 8000.0)                            # a 2 m candle light: never below 2x

    def test_room_far_from_lights_reads_darker_than_skyrim(self):
        # one big Skyrim light (radius 20 m), an object under it (4 m) and one 15 m away. Ours falls off faster, but
        # only by about half a stop: Skyrim's gamma-space light, linearised (^2.2), drops nearly as fast as an inverse
        # square (near 0.96 -> 0.90 linear, far 0.125 -> 0.014). Worked by hand: near / far = 96 (ours) vs 63 (Skyrim)
        exp = {"cell": "Hall", "lighting": {"ambient": [0, 0, 0]},
               "refs": [{"type": "Light", "pos": [0, 0, 300], "formkey": "L", "base_editor_id": "Fill",
                         "light": light(radius=1400.0)},
                        {"type": "Static", "pos": [0, 0, 0], "model": "a.nif", "formkey": "N", "base_editor_id": "A"},
                        {"type": "Static", "pos": [1000, 0, 0], "model": "a.nif", "formkey": "F",
                         "base_editor_id": "B"}]}
        c = light_audit.audit_cell(exp, dict(light_audit.DEFAULTS))
        self.assertEqual(c["points"], 2)
        self.assertAlmostEqual(c["ours_vs_skyrim"]["spread_stops"], 0.47, delta=0.15)


if __name__ == "__main__":
    unittest.main()
