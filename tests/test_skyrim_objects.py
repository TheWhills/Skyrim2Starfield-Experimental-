"""Synthetic-fixture tests for Skyrim objects on the Tamriel overlay: BSA archives, Skyrim SE meshes and collision,
the converter, the reference export and the whole export -> select -> convert -> stage -> check path. No game data."""
import contextlib
import io
import json
import math
import os
import sys
import tempfile
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "terrain"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import bsa, nif, sfmesh, sfnif, skyrimconvert, skyrimnif, skyrimrefs, textures  # noqa: E402
import skyrim_fixtures as F  # noqa: E402
from test_skyrimland import hills  # noqa: E402

H = skyrimnif.HAVOK_SCALE


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class BsaTests(unittest.TestCase):
    def test_round_trip_versions_and_flags(self):
        files = {"meshes\\a\\b.nif": b"x" * 1000, "Meshes/a/c.NIF": b"hello", "textures\\t.dds": bytes(range(256))}
        with tempfile.TemporaryDirectory() as tmp:
            for version, compress, embed in ((105, True, False), (105, False, True), (104, True, True)):
                p = os.path.join(tmp, f"v{version}{compress}{embed}.bsa")
                with open(p, "wb") as f:
                    f.write(bsa.build(files, version=version, compress=compress, embed_names=embed))
                a = bsa.Bsa(p)
                self.assertEqual(sorted(a.names), ["meshes\\a\\b.nif", "meshes\\a\\c.nif", "textures\\t.dds"])
                self.assertEqual(a.read("MESHES/A/B.nif"), b"x" * 1000)
                self.assertEqual(a.read("meshes\\a\\c.nif"), b"hello")
                self.assertEqual(a.read(a.find("textures\\t.dds")), bytes(range(256)))
                self.assertIsNone(a.find("meshes\\nope.nif"))

    def test_skyrim_archives_order_and_loose_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "Skyrim - Meshes0.bsa"), "wb") as f:
                f.write(bsa.build({"meshes\\x.nif": b"base", "meshes\\y.nif": b"y"}))
            with open(os.path.join(tmp, "Update.bsa"), "wb") as f:
                f.write(bsa.build({"meshes\\x.nif": b"update"}))
            os.makedirs(os.path.join(tmp, "textures"))
            with open(os.path.join(tmp, "textures", "loose.dds"), "wb") as f:
                f.write(b"loose")
            s = bsa.SkyrimArchives(tmp)
            self.assertEqual(s.mesh("x.nif"), b"update")              # later archive wins
            self.assertEqual(s.mesh("meshes\\y.nif"), b"y")
            self.assertEqual(s.texture("loose.dds"), b"loose")        # loose files win
            self.assertIsNone(s.material("anything.bgsm"))
            self.assertEqual(s.mesh_names("x"), ["meshes\\x.nif"])

    def test_rejects_other_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "f.bsa")
            with open(p, "wb") as f:
                f.write(b"BTDX" + bytes(40))
            with self.assertRaises(bsa.BsaError):
                bsa.Bsa(p)


class NifTests(unittest.TestCase):
    def test_bstrishape_vertices_uvs_and_world_transform(self):
        n = F.SseNif()
        root = n.reserve("BSFadeNode")
        sh = n.trishape(b"S", [(1, 2, 3), (4, 5, 6), (7, 8, 10)], [(0.5, 0.25), (1, 0), (0, 1)], [(0, 1, 2)],
                        t=(10, 0, 0))
        n.node(root, b"Root", [sh], t=(0, 100, 0))
        s, = skyrimnif.trishapes(nif.parse(n.bytes()))
        self.assertEqual(s.positions, [(1, 2, 3), (4, 5, 6), (7, 8, 10)])
        self.assertEqual(s.uvs[0], (0.5, 0.25))
        self.assertEqual(s.triangles, [(0, 1, 2)])
        self.assertEqual(s.translation, (10.0, 100.0, 0.0))            # shape under root: composed
        self.assertAlmostEqual(s.normals[0][2], 1.0, places=2)

    def test_nitrishape_with_and_without_material_crc_and_lod_shape(self):
        for crc in (False, True):
            n = F.SseNif()
            root = n.reserve("BSFadeNode")
            sh = n.nitrishape(b"N", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0), (1, 0), (0, 1)], [(0, 1, 2)], crc=crc)
            lod = n.trishape(b"L", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0)] * 3, [(0, 1, 2)], lod=True)
            n.node(root, b"Root", [sh, lod])
            got = skyrimnif.trishapes(nif.parse(n.bytes()))
            self.assertEqual([len(s.triangles) for s in got], [1, 1])
            self.assertEqual(got[0].uvs[1], (1.0, 0.0))

    def test_double_sided_flag_and_back_faces(self):
        n = F.SseNif()
        root = n.reserve("BSFadeNode")
        v, uv = [(0, 0, 0), (100, 0, 0), (0, 100, 0)], [(0, 0), (1, 0), (0, 1)]
        two = n.trishape(b"Leaf", v, uv, [(0, 1, 2)], shader=n.lighting("a.dds", "a_n.dds", double_sided=True))
        one = n.trishape(b"Bark", v, uv, [(0, 1, 2)], shader=n.lighting("b.dds", "b_n.dds"))
        n.node(root, b"Root", [two, one])
        src = nif.parse(n.bytes())
        leaf, bark = skyrimnif.trishapes(src)
        self.assertTrue(skyrimnif.double_sided(src, leaf.shader_ref))
        self.assertFalse(skyrimnif.double_sided(src, bark.shader_ref))
        self.assertFalse(skyrimnif.double_sided(src, -1))
        d = skyrimconvert.with_back_faces(leaf)
        self.assertEqual(d.positions, leaf.positions * 2)
        self.assertEqual(d.uvs, leaf.uvs * 2)
        self.assertEqual(d.triangles, [(0, 1, 2), (3, 5, 4)])                 # mirrored copy: reversed winding

        def face_normal(s, t):
            a, b, c = (s.positions[i] for i in t)
            u, w = [b[k] - a[k] for k in range(3)], [c[k] - a[k] for k in range(3)]
            return (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
        front, back = face_normal(d, d.triangles[0]), face_normal(d, d.triangles[1])
        self.assertGreater(front[2], 0)
        self.assertLess(back[2], 0)                                            # faces the other way
        for i in range(3):                                                     # vertex normals follow their face
            self.assertGreater(d.normals[i][2], 0.9)
            self.assertLess(d.normals[3 + i][2], -0.9)
        from fo4sf import convert_static
        m = convert_static.shape_to_mesh(d, 1 / 70)
        self.assertEqual((len(m.positions), len(m.triangles)), (6, 2))
        big = skyrimconvert.dataclasses.replace(leaf, positions=[(0, 0, 0)] * 40000)
        self.assertIsNone(skyrimconvert.with_back_faces(big))                 # 80,000 vertices: no u16 room

    def test_collision_shapes_decode_to_their_geometry(self):
        rock = nif.parse(F.rock_nif())
        pts, tris = skyrimnif.collision_triangles(rock)
        self.assertEqual(len(tris), 128)
        self.assertAlmostEqual(max(p[2] for p in pts), 360.0, delta=0.2)    # dome top, game units
        tree = nif.parse(F.tree_nif())
        pts, _ = skyrimnif.collision_triangles(tree)
        self.assertAlmostEqual(min(p[2] for p in pts), (0.5 - 0.3 + 0.2) * H, places=3)   # rigid body T offset
        self.assertAlmostEqual(max(p[2] for p in pts), (10.0 + 0.3 + 0.2) * H, places=3)
        house = nif.parse(F.building_nif())
        pts, tris = skyrimnif.collision_triangles(house)
        self.assertEqual(len(tris), 24)                                     # transformed box + convex hull
        self.assertAlmostEqual(min(p[2] for p in pts), -10.0, places=3)
        self.assertAlmostEqual(max(p[0] for p in pts), 700.0, places=3)
        self.assertEqual(skyrimnif.collision_triangles(nif.parse(F.fern_nif())), ([], []))

    def test_cms_strips_lists_big_triangles_and_transform(self):
        n = F.SseNif()
        root = n.reserve("BSFadeNode")
        q = [(0, 0, 0), (1000, 0, 0), (0, 1000, 0), (1000, 1000, 0), (0, 0, 1000)]
        shape = n.cms([((1.0, 2.0, 3.0), q, [[0, 1, 2, 3]], [0, 1, 4])], big_verts=[(9, 9, 9), (8, 9, 9), (9, 8, 9)],
                      big_tris=[(0, 1, 2)], transforms=((0.0, 0.0, 0.5), (0, 0, 0, 1)))
        n.node(root, b"Root", [], coll=n.collision(root, shape), t=(100, 0, 0))
        rep = {}
        pts, tris = skyrimnif.collision_triangles(nif.parse(n.bytes()), rep)
        self.assertEqual(len(tris), 4)                                      # big tri + 2 strip + 1 list
        self.assertEqual(tris[0], (0, 1, 2))
        self.assertEqual(tris[1], (3, 4, 5))
        self.assertEqual(tris[2], (4, 6, 5))                                # odd strip triangle: winding flipped
        self.assertEqual(tris[3], (3, 4, 7))
        p = pts[3]                                                          # chunk vertex 0: chunk origin + transform
        self.assertAlmostEqual(p[0], 100 + 1.0 * H, places=3)
        self.assertAlmostEqual(p[2], (3.0 + 0.5) * H, places=3)
        self.assertAlmostEqual(pts[4][0] - pts[3][0], 1.0 * H, places=3)   # 1000 steps of 0.001
        self.assertEqual(rep["skyrim_bodies"], 1)

    def test_rigid_body_transform_offsets_t_bodies_only(self):
        """Translation at 52, rotation at 68 (tes4skyrim's 250-byte layout), applied on bhkRigidBodyT only. An identity
        body laid out as vanilla stores it (rotation 0 0 0 1 followed by a zero linear velocity) must stay unrotated:
        read four bytes late, its floats are (0, 0, 1, 0), a valid 180 degree turn. A PLAIN bhkRigidBody's stored
        transform is ignored: on the owner's Skyrim SE, applying it put 284 of 285 vanilla models' collision off the
        visible mesh (baskets 768 units away, the Orc door's body repeating its node's position: doubled)."""
        def body_points(shifted=False, **kw):
            n = F.SseNif()
            root = n.reserve("BSFadeNode")
            shape = n.box((1.0, 0.5, 0.25))
            if shifted:                                                 # asymmetric: a 180 degree flip would show
                shape = n.transform(shape, (3.0, 0.0, 0.0))
            n.node(root, b"Root", [], coll=n.collision(root, shape, **kw))
            return skyrimnif.collision_triangles(nif.parse(n.bytes()))[0]
        ident = body_points(shifted=True, rigid_t=((0.0, 0.0, 0.0), (0, 0, 0, 1)))
        self.assertAlmostEqual(min(p[0] for p in ident), 2.0 * H, places=3)
        self.assertAlmostEqual(max(p[0] for p in ident), 4.0 * H, places=3)
        s = math.sqrt(0.5)                                              # 90 degrees about Z, moved 2 units up
        pts = body_points(rigid_t=((0.0, 0.0, 2.0), (0, 0, s, s)))      # bhkRigidBodyT: applied
        self.assertAlmostEqual(max(p[0] for p in pts), 0.5 * H, places=3)         # x and y swapped by the turn
        self.assertAlmostEqual(max(p[1] for p in pts), 1.0 * H, places=3)
        self.assertAlmostEqual(min(p[2] for p in pts), (2.0 - 0.25) * H, places=3)
        plain = body_points(rigid_t=((0.0, 0.0, 2.0), (0, 0, s, s)), plain_transform=True)   # plain body: ignored
        self.assertAlmostEqual(max(p[0] for p in plain), 1.0 * H, places=3)
        self.assertAlmostEqual(min(p[2] for p in plain), -0.25 * H, places=3)

    def test_body_transform_modes(self):
        """The survey's alternative rules: the tree's rigid body T carries translation (0, 0, 0.2) havok units."""
        tree = nif.parse(F.tree_nif())
        zmax = {m: max(p[2] for p in skyrimnif.collision_triangles(tree, None, body_transform=m)[0])
                for m in skyrimnif.BODY_TRANSFORM_MODES}
        self.assertAlmostEqual(zmax["all"] - zmax["none"], 0.2 * H, places=3)
        self.assertAlmostEqual(zmax["t_only"], zmax["all"], places=6)     # a T body: applied under t_only too
        self.assertEqual(skyrimnif.BODY_TRANSFORM_DEFAULT, "t_only")
        rep = {}
        skyrimnif.collision_triangles(tree, rep)
        b, = rep["body_list"]
        self.assertEqual((b["class"], b["translation"], b["rotated"]), ("bhkRigidBodyT", [0.0, 0.0, round(0.2 * H, 1)], False))

    def test_non_unit_body_rotation_is_reported_and_ignored(self):
        n = F.SseNif()
        root = n.reserve("BSFadeNode")
        n.node(root, b"Root", [], coll=n.collision(root, n.box((1.0, 1.0, 1.0)), rigid_t=((5.0, 0, 0), (0, 0, 3, 0))))
        rep = {}
        pts, _ = skyrimnif.collision_triangles(nif.parse(n.bytes()), rep)
        self.assertAlmostEqual(max(p[0] for p in pts), 1.0 * H, places=3)          # identity used, translation too
        self.assertIn("not a unit quaternion", rep["unsupported"][0])

    def test_unsupported_shape_is_reported_not_guessed(self):
        n = F.SseNif()
        root = n.reserve("BSFadeNode")
        odd = n.add("bhkMultiSphereShape", bytes(40))
        n.node(root, b"Root", [], coll=n.collision(root, odd))
        rep = {}
        self.assertEqual(skyrimnif.collision_triangles(nif.parse(n.bytes()), rep), ([], []))
        self.assertEqual(rep["unsupported"], ["bhkMultiSphereShape"])


class BoxTemplateTests(unittest.TestCase):
    def test_template_from_starfield_archives_or_file(self):
        import types
        import make_skyrim_objects as so
        with tempfile.TemporaryDirectory() as tmp:
            nif_path = F.collision_template_nif(os.path.join(tmp, "box.nif"))
            with open(nif_path, "rb") as f:
                raw = f.read()
            sfdata = os.path.join(tmp, "Starfield", "Data")
            os.makedirs(sfdata)
            F.starfield_meshes_ba2(os.path.join(sfdata, "Starfield - Meshes01.ba2"), {so.BOX_TEMPLATE_NIF: raw})
            a = types.SimpleNamespace(collision_template="", starfield_data=sfdata)
            self.assertEqual(so.box_template_nif(a), raw)
            a = types.SimpleNamespace(collision_template=nif_path, starfield_data="")
            self.assertEqual(so.box_template_nif(a), raw)
            empty = os.path.join(tmp, "empty")
            os.makedirs(empty)
            with self.assertRaises(SystemExit):
                so.box_template_nif(types.SimpleNamespace(collision_template="", starfield_data=empty))


class ColumnBoxTests(unittest.TestCase):
    def test_dome_is_covered_from_above_within_budget(self):
        v, _, t = F.grid_mesh(30, 30, 20.0, lambda x, y: max(0.0, 100 - (x - 10) ** 2 - (y - 10) ** 2) ** 0.5 * 0.5)
        rep = {}
        boxes = skyrimconvert.column_boxes(v, t, max_boxes=128, report=rep)
        self.assertLessEqual(len(boxes), 128)
        self.assertEqual(rep["boxes"], len(boxes))
        cell = rep["column_cell_m"]
        for x, y, z in v:                                                    # every surface point inside a box
            hit = [(c, h) for c, h in boxes if abs(x - c[0]) <= h[0] + 1e-6 and abs(y - c[1]) <= h[1] + 1e-6
                   and c[2] - h[2] - 1e-6 <= z <= c[2] + h[2] + 1e-6]
            self.assertTrue(hit, (x, y, z))
            if math.hypot(x - 10, y - 10) < 4.0:                             # gentle top: walkable height kept
                top = max(c[2] + h[2] for c, h in hit)
                self.assertLess(top - z, 0.5 * cell + 0.3)
        self.assertAlmostEqual(min(c[2] - h[2] for c, h in boxes), 0.0, places=6)   # solid down to the base

    def test_coarsens_to_fit(self):
        v, _, t = F.grid_mesh(60, 60, 60.0, lambda x, y: 3 * math.sin(x / 3) + 2 * math.cos(y / 4))
        rep = {}
        boxes = skyrimconvert.column_boxes(v, t, max_boxes=64, report=rep)
        self.assertLessEqual(len(boxes), 64)
        self.assertGreater(rep["column_cell_m"], 0.5)
        # nothing dropped: every column of the surface lies inside some box's footprint
        for x, y, _z in v:
            self.assertTrue(any(abs(x - c[0]) <= h[0] + 1e-6 and abs(y - c[1]) <= h[1] + 1e-6 for c, h in boxes))

    def test_budget_scales_with_footprint(self):
        self.assertEqual(skyrimconvert.column_budget([(0, 0, 0), (10, 10, 0)]), 128)
        self.assertEqual(skyrimconvert.column_budget([(0, 0, 0), (60, 60, 0)]), 225)
        self.assertEqual(skyrimconvert.column_budget([(0, 0, 0), (400, 400, 0)]), 512)


@contextlib.contextmanager
def starfield_inputs(tmp):
    yield {"content_resources": F.content_resources(os.path.join(tmp, "ContentResources.zip")),
           "collision_template": F.collision_template_nif(os.path.join(tmp, "box.nif"))}


class ConverterTests(unittest.TestCase):
    def test_models_materials_and_collision(self):
        from fo4sf import convert_static
        with tempfile.TemporaryDirectory() as tmp, starfield_inputs(tmp) as sf, \
                mock.patch.object(textures, "texconv", lambda *a, **k: None):
            data = F.skyrim_data(os.path.join(tmp, "Data"))
            with open(sf["collision_template"], "rb") as f:
                template = convert_static.collision_template_from_nif(f.read())
            conv = skyrimconvert.SkyrimConverter(bsa.SkyrimArchives(data), os.path.join(tmp, "out"), "texconv",
                                                 sf["content_resources"], template)
            res = {k: conv.convert_nif(k) for k in F.MODELS}
            for k, r in res.items():
                self.assertTrue(r["ok"], (k, r.get("reason")))
            rock = res["meshes\\landscape\\rocks\\rockcliff01.nif"]
            self.assertEqual(rock["collision_report"]["method"], "columns")
            self.assertTrue(rock["collision_report"]["collision_overlaps_render"])
            house = res["meshes\\architecture\\whiterun\\wrhouse01.nif"]
            self.assertEqual(house["collision_report"]["method"], "surfaces+voxels")
            self.assertEqual(house["skipped_effect_shapes"], 1)                   # the glow shape
            self.assertEqual(res["meshes\\landscape\\plants\\fern01.nif"]["collision_report"]["source"], "skyrim-none")
            tree = res["meshes\\landscape\\trees\\treepine01.nif"]
            self.assertEqual(tree["fallback_materials"], 0)
            leaves = load(os.path.join(tmp, "out", *tree["materials"][1].split("\\")))
            opaque = load(os.path.join(tmp, "out", *tree["materials"][0].split("\\")))
            self.assertIn("opacity", json.dumps(leaves).lower())                  # cutout: opacity texture
            self.assertNotIn("_opacity.dds", json.dumps(opaque).lower())
            # double-sided leaves get back faces; the trunk and every other model stay one-sided
            self.assertEqual((tree["double_sided_shapes"], tree["double_sided_too_big"]), (1, 0))
            self.assertEqual(sum(r["double_sided_shapes"] for r in res.values()), 1)
            tn = nif.parse(open(os.path.join(tmp, "out", "meshes", "skyrim", "landscape", "trees",
                                             "treepine01.nif"), "rb").read())
            tris = sorted(sfnif.parse_bsgeometry(tn.blocks[i]).meshes[0].indices_size // 3
                          for i in range(len(tn.blocks)) if tn.type_of(i) == "BSGeometry")
            self.assertEqual(tris, [2, 3])                                       # leaves 1 -> 2, trunk 3
            # the written rock NIF: one BSGeometry, collision bodies, mesh positions = Skyrim units / 70
            out = nif.parse(open(os.path.join(tmp, "out", "meshes", "skyrim", "landscape", "rocks",
                                              "rockcliff01.nif"), "rb").read())
            types = [out.type_of(i) for i in range(len(out.blocks))]
            self.assertEqual(types.count("BSGeometry"), 1)
            self.assertEqual(types.count("bhkPhysicsSystem"), rock["collision_report"]["boxes"])
            g = sfnif.parse_bsgeometry(out.blocks[types.index("BSGeometry")])
            mp = os.path.join(tmp, "out", "geometries", *g.meshes[0].path.decode().split("\\")) + ".mesh"
            m = sfmesh.parse(open(mp, "rb").read())
            zs = [sfmesh.decode_position(p, m.scale)[2] for p in m.positions]
            self.assertAlmostEqual(max(zs), 360.0 / 70.0, delta=0.01)

    def test_missing_mesh_is_a_recorded_failure(self):
        with tempfile.TemporaryDirectory() as tmp, starfield_inputs(tmp) as sf, \
                mock.patch.object(textures, "texconv", lambda *a, **k: None):
            data = F.skyrim_data(os.path.join(tmp, "Data"))
            conv = skyrimconvert.SkyrimConverter(bsa.SkyrimArchives(data), os.path.join(tmp, "out"), "t",
                                                 sf["content_resources"], None)
            r = conv.convert_nif("meshes\\clutter\\doesnotexist.nif")
            self.assertFalse(r["ok"])
            self.assertIn("FileNotFoundError", r["reason"])


# ---------------------------------------------------------------------------------------------------------- export
EXTENT = (-6, 5, -4, 4)


def ref_at(fid, base, x, y, rot=(0.0, 0.0, 0.0), scale=1.0, flags=0, xesp=None, sig=b"REFR"):
    return (sig, fid, base, (x, y, hills(x, y)), rot, scale, flags, xesp)


def world_refs():
    cells = {}

    def put(r):
        x, y = r[3][0], r[3][1]
        cells.setdefault((int(math.floor(x / 4096)), int(math.floor(y / 4096))), []).append(r)
    put(ref_at(0x2001, 0x0A01, 1000.0, 1500.0))                               # rock
    put(ref_at(0x2002, 0x0A01, -9000.0, 6000.0, rot=(0, 0, 1.2), scale=1.5))  # rock, rotated and scaled
    put(ref_at(0x2003, 0x0A02, 3000.0, -2000.0))                              # tree
    put(ref_at(0x2004, 0x0A03, -2000.0, -5000.0, flags=0x800))                # house, initially disabled
    put(ref_at(0x2005, 0x0A04, 500.0, 500.0, xesp=(0x2004, 1)))               # fern with enable parent
    put(ref_at(0x2006, 0x0A05, 100.0, 100.0))                                 # marker: skipped
    put(ref_at(0x2007, 0x0A06, 200.0, 200.0))                                 # light: skipped
    put(ref_at(0x2008, 0x0A07, 300.0, 300.0))                                 # fog effect: skipped
    put(ref_at(0x2009, 0x0A08, 400.0, 400.0))                                 # missing mesh: conversion failed
    put(ref_at(0x200A, 0x0A09, 600.0, 600.0, sig=b"ACHR"))                    # guard: deferred
    put(ref_at(0x200B, 0x0A01, 700.0, 700.0, flags=0x20))                     # deleted: gone
    persistent = [ref_at(0x200C, 0x0A02, 8000.0, 3000.0, flags=0x400)]       # persistent tree
    return cells, persistent


def write_esm(path):
    cells, persistent = world_refs()
    with open(path, "wb") as f:
        f.write(F.build_esm(cells, hills, EXTENT, persistent_refs=persistent))
    return path


class ExportTests(unittest.TestCase):
    def test_export_schema_and_classes(self):
        with tempfile.TemporaryDirectory() as tmp:
            exp = skyrimrefs.export_world(write_esm(os.path.join(tmp, "Skyrim.esm")))
            by = {r["formkey"]: r for r in exp["refs"]}
            self.assertEqual(len(exp["refs"]), 10)                         # 12 placed - deleted - actor
            self.assertEqual([d["formkey"] for d in exp["deferred_refs"]], ["00200A:Skyrim.esm"])
            rock = by["002002:Skyrim.esm"]
            self.assertEqual((rock["type"], rock["base_editor_id"], rock["model"], rock["scale"]),
                             ("Static", "RockCliff01", "Landscape\\Rocks\\RockCliff01.nif", 1.5))
            self.assertAlmostEqual(rock["rot"][2], 1.2, places=5)
            self.assertEqual(rock["exterior_cell"], [-3, 1])
            self.assertEqual(by["002003:Skyrim.esm"]["type"], "Tree")
            self.assertEqual(by["002004:Skyrim.esm"]["disabled"], 0x800)
            self.assertEqual(by["002005:Skyrim.esm"]["enable_parent"], {"reference": "002004:Skyrim.esm", "flags": 1})
            p = by["00200C:Skyrim.esm"]
            self.assertTrue(p["persistent"])
            self.assertEqual(p["exterior_cell"], [1, 0])                     # from its position
            only = skyrimrefs.export_world(os.path.join(tmp, "Skyrim.esm"), cells=(0, 0, 0, 0))
            self.assertEqual(sorted(r["formkey"][:6] for r in only["refs"]),
                             ["002001", "002005", "002006", "002007", "002008", "002009"])


# ---------------------------------------------------------------------------------------------------------- pipeline
class PipelineTests(unittest.TestCase):
    def test_export_select_convert_stage_check(self):
        import make_cw_overlays as cw
        import make_skyrim_objects as so
        import make_skyrim_overlay as sk
        with tempfile.TemporaryDirectory() as tmp, starfield_inputs(tmp) as sf, \
                mock.patch.object(textures, "texconv", lambda *a, **k: None), \
                mock.patch.object(cw, "ltex_source", return_value=([0x001235C2], bytes([0, 0, 0, 0, 0, 0, 0, 1]))), \
                contextlib.redirect_stdout(io.StringIO()) as log:
            esm = write_esm(os.path.join(tmp, "Skyrim.esm"))
            data = F.skyrim_data(os.path.join(tmp, "Data"))
            terrain, work, out = (os.path.join(tmp, d) for d in ("terrain", "work", "out"))
            sk.main(["build", "--skyrim", esm, "--sf-data", tmp, "--out", terrain, "--mask-writer", "builtin",
                     "--arrival", ""])
            so.main(["export", "--skyrim", esm, "--work", work])
            so.main(["select", "--work", work, "--terrain", terrain])
            texconv = os.path.join(tmp, "texconv.exe")                       # stand-in (texconv is patched)
            with open(texconv, "wb") as f:
                f.write(b"MZ")
            conv_args = ["convert", "--work", work, "--skyrim-data", data, "--content-resources",
                         sf["content_resources"], "--texconv", texconv, "--collision-template",
                         sf["collision_template"], "--resume"]
            so.main(conv_args)
            first = load(os.path.join(work, "convert", "manifest.json"))
            so.main(conv_args)                                                   # resumed: every model reused
            second = load(os.path.join(work, "convert", "manifest.json"))
            so.main(["stage", "--work", work, "--terrain", terrain, "--out", out])
            ok, rep = so.check(out)
            skipped = load(os.path.join(out, "skipped.json"))["counts"]
            obj = load(os.path.join(out, "objects.json"))
            prm = load(os.path.join(out, "overlays_params.json"))
            has_btd = os.path.isfile(os.path.join(out, "Data", "Terrain", "SKY_Tamriel.btd"))
        self.assertTrue(ok, [c for c in rep["checks"] if not c[1]])
        self.assertEqual((first["stats"]["assets"], first["stats"]["reused"]), (4, 0))
        self.assertEqual((second["stats"]["assets"], second["stats"]["reused"]), (4, 4))
        self.assertEqual([i["editor_id"] for i in first["items"]], [i["editor_id"] for i in second["items"]])
        sel = rep
        self.assertEqual(sel["refs"], 6)            # 2 rocks, 2 trees, house, fern (marker / light / fog / missing out)
        self.assertEqual(sel["bases"], 4)
        self.assertEqual(sel["initially_disabled"], 1)
        self.assertEqual(sel["collision_refs"], {"skyrim-columns": 4, "skyrim-surfaces+voxels": 1, "skyrim-none": 1})
        self.assertLess(abs(sel["frame"]["median_m"]), 0.05)            # origins on the terrain: frames agree
        self.assertEqual(sel["frame"]["within_3m"], 6)
        self.assertEqual(skipped, {"conversion_failed": 1, "deferred": 1, "editor_marker": 1, "effect": 1,
                                   "type_not_translated": 1})
        self.assertEqual(prm["objects"], "objects.json")
        self.assertEqual(obj["world"], "SKY_Tamriel")
        self.assertTrue(all(b["edid"].startswith("SKY_") for b in obj["bases"]))
        rock = next(r for r in obj["refs"] if r["src"] == "002002:Skyrim.esm")
        self.assertEqual(rock["pos"][:2], [round(-9000 / 70, 5), round(6000 / 70, 5)])
        self.assertTrue(has_btd)
        self.assertIn("next: dotnet run", log.getvalue())


if __name__ == "__main__":
    unittest.main()


class ReadBasesTests(unittest.TestCase):
    def test_armor_world_model_is_mod2_not_its_armature_formids(self):
        """Real SE: ARMO's MODL holds armature FormIDs; reading them as a path gave 75 garbage model names."""
        import struct as st
        from fo4sf import fo4land
        from test_fo4land import grup, rec
        armo = rec(b"ARMO", 0x200, [(b"EDID", b"ArmorIronCuirass\0"), (b"MOD2", b"Armor\\Iron\\CuirassGND.nif\0"),
                                    (b"MODL", st.pack("<I", 0x100))])
        stat = rec(b"STAT", 0x300, [(b"EDID", b"Rock\0"), (b"MODL", b"Landscape\\Rock.nif\0")])
        bad = rec(b"STAT", 0x301, [(b"EDID", b"Odd\0"), (b"MODL", st.pack("<I", 0x0D0A0B02))])
        data = rec(b"TES4", 0, [(b"HEDR", st.pack("<fII", 1.71, 0, 0x800))]) + grup(b"ARMO", 0, [armo]) \
            + grup(b"STAT", 0, [stat, bad])
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "Skyrim.esm")
            with open(p, "wb") as f:
                f.write(data)
            with fo4land.Plugin(p) as pl:
                bases = skyrimrefs.read_bases(pl)
        self.assertEqual(bases[0x200], ("Armor", "ArmorIronCuirass", "Armor\\Iron\\CuirassGND.nif"))
        self.assertEqual(bases[0x300][2], "Landscape\\Rock.nif")
        self.assertEqual(bases[0x301][2], "")
