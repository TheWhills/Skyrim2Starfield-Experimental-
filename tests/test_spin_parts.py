"""Turning parts of Skyrim models (2026-11-18, owner: Riverwood's mill water wheel should spin): the looping
NiControllerSequence read (skyrimnif.spin_part), the part's own model frame (skyrimconvert.spin_frame / to_spin_frame)
and its reference placed at the pivot (exterior.place spin=True). Synthetic data only."""
import math
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fo4sf import exterior as ex, nif as nifmod, skyrimconvert as sc, skyrimnif  # noqa: E402


class FakeNif:
    def __init__(self, blocks, strings, types):
        self.blocks, self.strings, self.types = blocks, strings, types

    def type_of(self, i):
        return self.types[i]


def xyz_data(x, y, z):
    """NiTransformData with XYZ rotation keys: per axis [(t, v)] linear keys; no translation / scale keys."""
    d = struct.pack("<II", 1, 4)
    for keys in (x, y, z):
        d += struct.pack("<I", len(keys)) + (struct.pack("<I", 1) if keys else b"")
        for t, v in keys:
            d += struct.pack("<2f", t, v)
    return d + struct.pack("<II", 0, 0)


def sequence(node_name_idx, interp, cycle=0, start=0.0, stop=16.667):
    cb = struct.pack("<iiB", interp, -1, 0) + struct.pack("<iiiii", node_name_idx, -1, -1, -1, -1)
    assert len(cb) == 29
    return struct.pack("<iII", 0, 1, 0) + cb + struct.pack("<fiIfff", 1.0, -1, cycle, 1.0, start, stop)


def interpolator(data_ref):
    return bytes(32) + struct.pack("<i", data_ref)


def wheel_nif(y_keys, x_keys=((0, 0.0), (16.667, 0.0)), cycle=0):
    """0 root node, 1 wheel node "Wheel", 2 sequence, 3 interpolator, 4 data."""
    strings = [b"Root", b"Wheel", b"Idle"]
    blocks = [struct.pack("<iI", 0, 0) + bytes(80), struct.pack("<iI", 1, 0) + bytes(80),
              sequence(1, 3, cycle), interpolator(4),
              xyz_data(list(x_keys), list(y_keys), [(0, math.pi / 2), (16.667, math.pi / 2)])]
    return FakeNif(blocks, strings, ["BSFadeNode", "NiNode", "NiControllerSequence", "NiTransformInterpolator",
                                     "NiTransformData"])


TURN = [(0, 0.0), (8.33, -math.pi), (16.667, -2 * math.pi)]


class SpinPartTests(unittest.TestCase):
    def test_reads_the_turning_node(self):
        got = skyrimnif.spin_part(wheel_nif(TURN))
        self.assertEqual((got["node"], got["block"], got["axis"], got["sign"]), ("Wheel", 1, 1, -1))
        self.assertAlmostEqual(got["period"], 16.667, places=3)
        self.assertEqual(skyrimnif.spin_part(wheel_nif([(0, 0.0), (16.667, 2 * math.pi)]))["sign"], 1)

    def test_not_a_spin(self):
        self.assertIsNone(skyrimnif.spin_part(wheel_nif(TURN, cycle=2)))                  # clamped, plays once
        self.assertIsNone(skyrimnif.spin_part(wheel_nif([(0, 0.0), (16.667, 0.5)])))      # a swing, not a turn
        self.assertIsNone(skyrimnif.spin_part(wheel_nif(TURN, x_keys=[(0, 0.3)])))        # tilted inside the turn
        self.assertIsNone(skyrimnif.spin_part(wheel_nif(TURN, x_keys=[(0, 0.0), (16.667, 2 * math.pi)])))  # 2 axes


def rz(a):
    c, s = math.cos(a), math.sin(a)
    return (c, -s, 0, s, c, 0, 0, 0, 1)


def mv(m, v):
    return tuple(sum(m[3 * r + k] * v[k] for k in range(3)) for r in range(3))


class SpinFrameTests(unittest.TestCase):
    def test_axis_goes_to_y(self):
        for axis in range(3):
            q = sc.spin_frame(axis, sc.VANILLA_SPIN_SIGN)
            e = [0, 0, 0]
            e[axis] = 1
            self.assertEqual(tuple(round(v, 9) for v in mv(q, e)), (0, 1, 0), axis)
            self.assertAlmostEqual(sum(q[0:3][k] * (q[4] * q[8] - q[5] * q[7]) for k in range(1)) +
                                   q[1] * (q[5] * q[6] - q[3] * q[8]) + q[2] * (q[3] * q[7] - q[4] * q[6]), 1.0)

    def test_other_direction_turns_y_round(self):
        q = sc.spin_frame(1, -sc.VANILLA_SPIN_SIGN)
        self.assertEqual(tuple(round(v, 9) for v in mv(q, (0, 1, 0))), (0, -1, 0))
        self.assertEqual(tuple(round(v, 9) for v in mv(q, (0, 0, 1))), (0, 0, 1))        # still upright

    def test_shapes_into_the_node_frame_and_back(self):
        node_t, node_r = (459.2, 0.0, -160.2), rz(math.pi / 2)        # the mill wheel's node
        shape = nifmod.Fo4Shape(b"SawWaterWheel03:19", (108.0, -128.0, -256.0), rz(math.pi / 2), 1.0, -1, -1, -1,
                                [], [], [], [], [], [], False)
        q = sc.spin_frame(1, sc.VANILLA_SPIN_SIGN)
        moved, = sc.to_spin_frame([shape], node_t, node_r, 1.0, q)
        frame = sc._m3(node_r, sc._t3(q))
        v = (3.0, -5.0, 7.0)
        world = tuple(a + b for a, b in zip(mv(shape.rotation, v), shape.translation))
        again = tuple(a + b for a, b in zip(mv(frame, tuple(x + y for x, y in zip(mv(moved.rotation, v),
                                                                                 moved.translation))), node_t))
        for a, b in zip(world, again):
            self.assertAlmostEqual(a, b, places=6)


class AnimatedNodeTests(unittest.TestCase):
    """The turning part's model is laid out like Starfield's AK_Fan_Yard_03_Blade.nif: root -> NiNode "Rotate_Y01"
    (NiStringExtraData sgoKeep) -> the shapes. Without that node the wheel stood still in game (2026-11-18)."""

    def test_layout(self):
        from fo4sf import sfnif
        shape = sfnif.StaticShape(b"Wheel:0", b"0123456789abcdef0123\\0123456789abcdef0123", 3, 3,
                                  "Materials\\x.mat", (0, 0, 0, 1), (0, 0, 0, 1, 1, 1))
        f = nifmod.parse(nifmod.serialize(sfnif.build_static_nif(b"Mill_spin", [shape, shape],
                                                                    animated_node=sc.SPIN_NODE)))
        def node(i):
            b = f.blocks[i]
            name, ne = struct.unpack_from("<iI", b, 0)
            extra = struct.unpack_from(f"<{ne}i", b, 8)
            p = 8 + 4 * ne + 8 + 52 + 4
            nk, = struct.unpack_from("<I", b, p)
            return f.strings[name], extra, struct.unpack_from(f"<{nk}i", b, p + 4)
        root_name, root_extra, root_kids = node(0)
        self.assertEqual((root_name, f.type_of(root_extra[0])), (b"Mill_spin", "BSXFlags"))
        self.assertEqual(len(root_kids), 1)
        name, extra, kids = node(root_kids[0])
        self.assertEqual(name, b"Rotate_Y01")
        self.assertEqual(f.type_of(extra[0]), "NiStringExtraData")
        self.assertEqual([f.type_of(k) for k in kids], ["BSGeometry", "BSGeometry"])
        self.assertEqual(f.footer, struct.pack("<II", 1, 0))
        plain = nifmod.parse(nifmod.serialize(sfnif.build_static_nif(b"Mill", [shape])))
        self.assertNotIn(b"Rotate_Y01", plain.strings)                  # other models unchanged


class PlaceSpinTests(unittest.TestCase):
    def manifest(self):
        frame = sc._m3(rz(math.pi / 2), sc._t3(sc.spin_frame(1, 1)))
        return {"items": [{"editor_id": "FO4Port_mill", "model": "skyrim\\mill.nif", "source": "meshes\\mill.nif",
                           "spin": {"model": "skyrim\\mill_spin.nif", "pivot_m": [6.56, 0.0, -2.29], "frame": list(frame),
                                    "scale": 1.0, "bounds": [[-1, -1, -1], [1, 1, 1]], "template": "12F12F",
                                    "period_s": 16.667}}]}

    def ref(self, fk, pos, rot):
        return {"formkey": fk, "type": "Static", "base_editor_id": "B", "model": "mill.nif", "pos": list(pos),
                "rot": list(rot), "scale": 1.0, "disabled": 0, "persistent": False, "enable_parent": None,
                "exterior_cell": [0, 0]}

    def test_ref_angles_inverts_ref_matrix(self):
        for rot in ((0.1, -0.4, 2.0), (0, 0, -math.pi / 2), (1.2, 0.3, -2.9)):
            got = ex.ref_angles(ex.ref_matrix(rot))
            for a, b in zip(ex.ref_matrix(got), ex.ref_matrix(rot)):
                self.assertAlmostEqual(a, b, places=9)

    def test_part_placed_at_the_pivot(self):
        sel = {"refs": [self.ref("A", (700, 700, 0), (0, 0, math.pi / 2)), self.ref("B", (0, 0, 0), (0, 0, 0))]}
        bases, placed, skipped = ex.place(sel, self.manifest(), -14, 14, "SKY_", spin=True)
        self.assertEqual([b["edid"] for b in bases], ["SKY_mill", "SKY_mill_Spin"])
        self.assertEqual(bases[1]["model"], "skyrim\\mill_spin.nif")
        self.assertEqual([(p["src"], p.get("spin_of")) for p in placed],
                         [("A", None), ("A#spin", "A"), ("B", None), ("B#spin", "B")])
        a, aspin = placed[0], placed[1]
        # pivot (6.56, 0, -2.29) turned by the clockwise quarter heading -> (0, -6.56, -2.29), from (10, 10, 0)
        for got, want in zip(aspin["pos"], (10.0, 10.0 - 6.56, -2.29)):
            self.assertAlmostEqual(got, want, places=4)
        # the part's +Y (its turning axis) in the world: frame then the reference
        m = ex.ref_matrix(aspin["rot"])
        want = mv(ex.ref_matrix(a["rot"]), mv(tuple(self.manifest()["items"][0]["spin"]["frame"]), (0, 1, 0)))
        for x, y in zip(mv(m, (0, 1, 0)), want):
            self.assertAlmostEqual(x, y, places=6)
        self.assertEqual(skipped, [])

    def test_spin_speed(self):
        """2026-11-18 (owner): the copied fan spin turned the wheel about 4 times Skyrim's 16.7 s per turn."""
        self.assertAlmostEqual(ex.spin_speed(16.667), 0.252, places=3)          # about vanilla _Slow's 0.25
        self.assertEqual(ex.spin_speed(ex.ROTATE_Y01_TURN_S), 1.0)
        self.assertEqual(ex.spin_speed(1e6), 0.01)

    def test_off_by_default(self):
        bases, placed, _ = ex.place({"refs": [self.ref("A", (0, 0, 0), (0, 0, 0))]}, self.manifest(), -14, 14, "SKY_")
        self.assertEqual((len(bases), len(placed)), (1, 1))



sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
import spin_parts  # noqa: E402


class SpinPartsScriptTests(unittest.TestCase):
    """scripts/terrain/spin_parts.py: the parts of an installed exterior for FO4Port.esm (PluginSpike SPIN_PARTS)."""

    def objects(self):
        return {"edid_prefix": "SKY_", "bases": [{"edid": "SKY_Mill", "model": "skyrim\\mill.nif", "source": "meshes\\mill.nif"},
                                                  {"edid": "SKY_Rock", "model": "skyrim\\rock.nif", "source": "meshes\\rock.nif"}],
                "refs": [{"src": "A", "base": 0, "pos": [10.0, 10.0, 0.0], "rot": [0, 0, math.pi / 2], "scale": 1.0,
                          "disabled": False},
                         {"src": "B", "base": 1, "pos": [0, 0, 0], "rot": [0, 0, 0], "scale": 1.0, "disabled": False},
                         {"src": "C", "base": 0, "pos": [900.0, 0, 0], "rot": [0, 0, 0], "scale": 2.0, "disabled": True}]}

    def test_plan(self):
        man = PlaceSpinTests().manifest()
        man["items"][0]["source"] = "meshes\\mill.nif"
        p = spin_parts.plan(self.objects(), man)
        self.assertEqual([b["edid"] for b in p["bases"]], ["S2SSpin_Mill"])
        self.assertEqual((p["bases"][0]["template"], p["bases"][0]["speed_from"]), ("304C45", "34F53D"))
        self.assertEqual(p["bases"][0]["speed"], ex.spin_speed(16.667))
        self.assertEqual([(r["src"], r["of"], r["disabled"]) for r in p["refs"]], [("A#spin", "A", False), ("C#spin", "C", True)])
        want = ex.spin_pose([10.0, 10.0, 0.0], [0, 0, math.pi / 2], 1.0, man["items"][0]["spin"])
        self.assertEqual((p["refs"][0]["pos"], p["refs"][0]["rot"]), (want[0], want[1]))
        self.assertEqual(p["refs"][1]["scale"], 2.0)
        self.assertEqual(len(spin_parts.plan(self.objects(), man, around=(0, 0, 100))["refs"]), 1)

    def test_nothing_when_staged_with_parts(self):
        o = self.objects()
        o["bases"].append({"edid": "SKY_Mill_Spin", "model": "x", "anim_template": "12F12F"})
        man = PlaceSpinTests().manifest()
        man["items"][0]["source"] = "meshes\\mill.nif"
        p = spin_parts.plan(o, man)
        self.assertEqual((p["refs"], p["already_staged"]), ([], 1))

    def test_split_only_where_placed(self):
        """Interiors / weapons (convert_batch.py etc.) place no turning parts: there the part stays in the model."""
        src = open(os.path.join(ROOT, "src", "fo4sf", "skyrimconvert.py"), encoding="utf-8").read()
        self.assertIn("self.split_spin = False", src)
        self.assertIn("skyrimnif.spin_part(src) if self.split_spin", src)
        objs = open(os.path.join(ROOT, "scripts", "terrain", "make_skyrim_objects.py"), encoding="utf-8").read()
        self.assertIn("conv.split_spin = True", objs)
        for other in ("convert_batch.py", os.path.join("armor", "weapon_test_pack.py")):
            self.assertNotIn("split_spin", open(os.path.join(ROOT, "scripts", other), encoding="utf-8").read())

    def test_plugin_and_owner_script_read_it(self):
        cs = open(os.path.join(ROOT, "dotnet", "PluginSpike", "Program.cs"), encoding="utf-8").read()
        self.assertIn('GetEnvironmentVariable("SPIN_PARTS")', cs)
        ps = open(os.path.join(ROOT, "tools", "owner", "riverwood_doors.ps1"), encoding="utf-8").read()
        self.assertIn("spin_parts.py", ps)
        self.assertIn("$env:SPIN_PARTS", ps)
        to = open(os.path.join(ROOT, "dotnet", "TerrainOverlays", "Program.cs"), encoding="utf-8").read()
        self.assertIn('TryGetProperty("anim_template"', to)
        for src in (cs, to):                       # the speed: the Properties entry of the vanilla _Slow helper
            self.assertIn('GetProperty("Properties")', src)
            self.assertIn("Activators.FirstOrDefault", src)


if __name__ == "__main__":
    unittest.main()
