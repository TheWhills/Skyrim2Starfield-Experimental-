"""fo4sf.smpconfig and scripts/armor/smp_survey.py on synthetic HDT-SMP configs and NIFs (no game or mod files)."""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
from fo4sf import nif as nifmod  # noqa: E402
from fo4sf import smpconfig as C  # noqa: E402
import smp_survey as V  # noqa: E402

HAIR = b"""<?xml version="1.0" encoding="UTF-8"?>
<system>
  <bone name="Tail 1"/>
  <bone name="NPC Head [Head]"/>
  <bone-default>
    <mass>0,3</mass>
    <inertia x="10" y="10" z="10"/>
    <angularDamping>0.4</angularDamping>
  </bone-default>
  <bone-default name="heavy" extends="">
    <mass>2</mass>
  </bone-default>
  <bone name="Tail 2"/>
  <bone name="Tail 3" template="heavy"/>
  <bone name="Tail 2"><mass>9</mass></bone>
  <generic-constraint-default>
    <angularLowerLimit x="-0.2" y="-0.1" z="0"/>
    <angularUpperLimit x="0.2" y="0.1" z="0.3"/>
    <angularStiffness x="50" y="50" z="50"/>
  </generic-constraint-default>
  <constraint-group>
    <generic-constraint bodyA="Tail 2" bodyB="Tail 1"></generic-constraint>
    <generic-constraint bodyA="Tail 3" bodyB ="Tail 2"><angularStiffness x="5" y="5" z="5"/></generic-constraint>
    <generic-constraint bodyA="Tail 4" bodyB="Tail 3"/>
  </constraint-group>
  <per-vertex-shape name="HairMesh">
    <margin>0</margin><shared>internal</shared><tag>hair</tag>
    <can-collide-with-tag>VirtualHead</can-collide-with-tag>
  </per-vertex-shape>
  <per-triangle-shape name="VirtualHead">
    <margin>0,02</margin><prenetration>0.01</prenetration><tag>VirtualHead</tag>
    <weight-threshold bone="NPC Head [Head]">0,4</weight-threshold>
  </per-triangle-shape>
</system>"""

NET = b"""<system>
  <bone-default><mass>1</mass></bone-default>
  <generic-constraint bodyA="A" bodyB="B"/><generic-constraint bodyA="B" bodyB="C"/>
  <generic-constraint bodyA="C" bodyB="A"/>
  <stiffspring-constraint bodyA="Loose" bodyB="Loose2"/>
  <bone name="Free"/>
  <bone name="Shaped"><shape type="capsule"><radius>1</radius><height>2</height></shape></bone>
  <pattern name="x"/>
</system>"""


class ParseTests(unittest.TestCase):
    def test_defaults_templates_and_order(self):
        cfg = C.parse(HAIR)
        b = cfg["bones"]
        self.assertFalse(b["Tail 1"]["dynamic"])                       # declared before any mass default
        self.assertFalse(b["NPC Head [Head]"]["dynamic"])
        self.assertAlmostEqual(b["Tail 2"]["mass"], 0.3)               # comma decimal; second declaration ignored
        self.assertEqual(b["Tail 2"]["inertia"], (10.0, 10.0, 10.0))
        self.assertEqual(b["Tail 3"]["mass"], 2.0)                     # named template extends the "" default
        self.assertAlmostEqual(b["Tail 3"]["angularDamping"], 0.4)
        self.assertTrue(b["Tail 4"]["dynamic"])                        # created by a constraint with the default
        self.assertFalse(b["Tail 4"]["declared"])
        self.assertTrue(any("declared twice" in w for w in cfg["warnings"]))
        c = cfg["constraints"]
        self.assertEqual([(x["a"], x["b"]) for x in c], [("Tail 2", "Tail 1"), ("Tail 3", "Tail 2"),
                                                         ("Tail 4", "Tail 3")])
        self.assertEqual(c[0]["angularStiffness"], (50.0, 50.0, 50.0))
        self.assertEqual(c[1]["angularStiffness"], (5.0, 5.0, 5.0))    # per-constraint override
        self.assertEqual(c[0]["angularUpperLimit"], (0.2, 0.1, 0.3))
        s = cfg["shapes"]
        self.assertEqual(s[0]["can-collide-with-tag"], ["VirtualHead"])
        self.assertAlmostEqual(s[1]["penetration"], 0.01)              # deprecated spelling read as penetration
        self.assertAlmostEqual(s[1]["weight-threshold"]["NPC Head [Head]"], 0.4)

    def test_chains_and_needs(self):
        cfg = C.parse(HAIR)
        g = C.chains(cfg)
        self.assertEqual(len(g), 1)
        self.assertEqual((g[0]["dynamic"], g[0]["anchors"], g[0]["depth"], g[0]["loops"]), (3, ["Tail 1"], 3, 0))
        self.assertEqual(C.needs(cfg), ["bone_chains", "per_vertex_shape", "per_triangle_shape"])
        s = C.summary(cfg)
        self.assertEqual((s["bones"], s["dynamic"], s["kinematic"]), (5, 3, 2))
        self.assertEqual(s["angular_stiffness_x"], [5.0, 50.0])

    def test_net_free_bodies_and_other_features(self):
        cfg = C.parse(NET)
        g = {tuple(sorted(x["anchors"])): x for x in C.chains(cfg)}
        tri = [x for x in C.chains(cfg) if x["bones"] == 3][0]
        self.assertEqual(tri["loops"], 1)
        self.assertEqual(tri["unanchored"], ["A", "B", "C"])           # nothing kinematic holds the net
        self.assertTrue(g)
        n = C.needs(cfg)
        for k in ("bone_chains", "bone_net", "free_bodies", "stiffspring", "bone_shapes", "patterns"):
            self.assertIn(k, n)

    def test_errors(self):
        with self.assertRaises(C.SmpError):
            C.parse(b"<notxml")
        with self.assertRaises(C.SmpError):
            C.parse(b"<config/>")

    def test_paths_and_mesh_check(self):
        self.assertEqual(C.data_relative("Data\\Meshes/KS\\X.xml"), "meshes\\ks\\x.xml")
        self.assertEqual(C.data_relative("\\SKSE\\Plugins\\a.xml"), "skse\\plugins\\a.xml")
        cfg = C.parse(HAIR)
        chk = C.check_mesh(cfg, ["HairMesh"], ["Tail 2", "Tail 3", "NPC Head [Head]"], {"NPC Head [Head]"})
        self.assertEqual(chk["shapes_missing"], ["VirtualHead"])
        self.assertEqual(chk["extra_bones"], ["Tail 2", "Tail 3"])
        self.assertEqual(chk["bones_missing"], ["Tail 1", "Tail 4"])


def _node(name_idx, children=(), extras=()):
    return (struct.pack("<iI", name_idx, len(extras)) + b"".join(struct.pack("<i", e) for e in extras)
            + struct.pack("<iI", -1, 14) + struct.pack("<9f3ff", 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1)
            + struct.pack("<i", -1) + struct.pack("<I", len(children))
            + b"".join(struct.pack("<i", c) for c in children) + struct.pack("<I", 0))


def synthetic_nif(xml_path: bytes) -> bytes:
    """Root -> NPC Head [Head] -> Tail 1, with an HDT NiStringExtraData on the root (no geometry)."""
    n = nifmod.NifFile(user_version=12, bs_version=100, max_filepath=b"")
    strings = [b"Scene Root", b"NPC Head [Head]", b"Tail 1", C.PHYSICS_EXTRA, xml_path]
    for s in strings:
        n.string_index(s)
    n.add_block("NiNode", _node(0, children=[2], extras=[1]))
    n.add_block("NiStringExtraData", struct.pack("<II", 3, 4))
    n.add_block("NiNode", _node(1, children=[3]))
    n.add_block("NiNode", _node(2))
    n.footer = struct.pack("<Ii", 1, 0)
    return nifmod.serialize(n)


class NifAndSurveyTests(unittest.TestCase):
    def test_physics_path_from_nif(self):
        n = nifmod.parse(synthetic_nif(b"Data\\meshes\\hair\\tail.xml"))
        self.assertEqual(C.nif_physics_paths(n), ["Data\\meshes\\hair\\tail.xml"])

    def test_survey_links_mesh_to_config(self):
        with tempfile.TemporaryDirectory() as d:
            mod = os.path.join(d, "00 Core")
            os.makedirs(os.path.join(mod, "Meshes", "Hair", "XML"))
            with open(os.path.join(mod, "Meshes", "Hair", "XML", "Tail.xml"), "wb") as fh:
                fh.write(HAIR)
            with open(os.path.join(mod, "Meshes", "Hair", "Tail.nif"), "wb") as fh:
                fh.write(synthetic_nif(b"Data\\meshes\\hair\\xml\\tail.xml"))
            with open(os.path.join(mod, "Meshes", "Hair", "Orphan.nif"), "wb") as fh:
                fh.write(synthetic_nif(b"meshes\\hair\\xml\\missing.xml"))
            out = os.path.join(d, "out")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(V.main(["--root", d, "--out", out]), 0)
            with open(os.path.join(out, "smp_survey.json"), encoding="utf-8") as fh:
                r = json.load(fh)
        self.assertEqual(r["roots"], [mod])
        self.assertEqual((r["configs"], r["meshes_with_physics"]), (1, 2))
        self.assertEqual(r["missing_configs"], {"meshes\\hair\\xml\\missing.xml": 1})
        self.assertEqual(r["chain_anchors"], {"NPC Head [Head] -> C_Head": 1})    # Tail 1 hangs off the head
        self.assertEqual(r["shapes_named_but_missing"], {"HairMesh": 1, "VirtualHead": 1})
        self.assertEqual(r["needs"], {"bone_chains": 1, "per_vertex_shape": 1, "per_triangle_shape": 1})

    def test_skeleton_from_bsa_when_not_loose(self):
        try:
            from fo4sf import bsa
            import lz4.frame  # noqa: F401  (bsa.build needs it)
        except ImportError:
            self.skipTest("lz4 not installed")
        with tempfile.TemporaryDirectory() as d:
            data = os.path.join(d, "Data")
            os.makedirs(data)
            with open(os.path.join(data, "Skyrim - Meshes0.bsa"), "wb") as fh:
                fh.write(bsa.build({V.SKELETON: synthetic_nif(b"x.xml")}, compress=False))
            missing = os.path.join(data, "meshes", "actors", "character", "character assets", "skeleton.nif")
            want = {"Scene Root", "NPC Head [Head]", "Tail 1"}
            self.assertEqual(V.load_skeleton(missing, []), want)          # the path's own Data folder
            self.assertEqual(V.load_skeleton(None, [data]), want)          # default path under a --root
            self.assertIsNone(V.load_skeleton(None, [d]))                  # nothing there


if __name__ == "__main__":
    unittest.main()
