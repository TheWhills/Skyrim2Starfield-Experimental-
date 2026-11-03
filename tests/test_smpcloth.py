"""Havok tagfile writer (fo4sf.hktagwrite), bone-chain cloth builder (fo4sf.smpcloth), Skyrim SMP hair conversion
(fo4sf.skyrimhair) and scripts/armor/hair_pack.py helpers, on synthetic data only (no game or mod files).

The checks against real files (byte-identical rewrites of the OC Ponytail / Pigtails cloth, equal values for Eris
Hairstyles, the bone-deformer frame and skin layouts reproduced on their rigs) are recorded in
docs/armor/animation-port.md "SMP hair -> Starfield cloth"."""
import math
import os
import struct
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
from fo4sf import hktagfile, hktagwrite, nif, sfcloth, sfnif, sfmesh, skyrimhair, smpcloth  # noqa: E402
import skyrim_fixtures as F  # noqa: E402
from test_sfcloth import cloth_tagfile  # noqa: E402


def same(a, b):
    if isinstance(a, dict):
        return isinstance(b, dict) and set(a) == set(b) and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b


class WriterTests(unittest.TestCase):
    def test_rewrite_decodes_to_the_same_values(self):
        blob = cloth_tagfile()
        tf = hktagfile.Tagfile(blob)
        out = hktagwrite.write(blob, tf.item_value(1))
        self.assertTrue(same(hktagfile.Tagfile(out).root(), tf.root()))
        self.assertEqual(hktagfile.Tagfile(out).sdk, "20190200")

    def test_layout_rules(self):
        blob = cloth_tagfile()
        root = hktagfile.Tagfile(blob).item_value(1)
        root["namedVariants"][1]["variant"]["bones"][3]["name"] = "Tail_1"     # an equal string: one item
        out = hktagwrite.write(blob, root)
        tf = hktagfile.Tagfile(out)
        d = tf.data_start
        chars = [bytes(out[d + it.offset:d + it.offset + it.count]) for it in tf.items if
                 tf.types[it.type].name == "char"]
        self.assertEqual(len(chars), len(set(chars)))                          # no string stored twice
        self.assertEqual(tf.items[1].offset, 0)
        self.assertEqual(tf.items[1].flags, 0x10)                              # the root: one object
        for it in tf.items[1:]:
            t = tf.types[it.type]
            align = (t.align & 0xFF or 1) if t.size else 2                     # typedefs (no layout): even offsets
            self.assertEqual(it.offset % align, 0, tf.type_name(it.type))
        patched = sum(len(o) for _t, o in tf.patches)
        refs = sum(1 for o in tf.patches for off in o[1] if struct.unpack_from("<Q", out, d + off)[0])
        self.assertEqual(patched, refs)                                        # only non-null references patched
        self.assertEqual(hktagfile.Tagfile(out).root()["hkaSkeleton"]["bones"][3]["name"], "Tail_1")

    def test_unknown_type_is_refused(self):
        blob = cloth_tagfile()
        root = hktagfile.Tagfile(blob).item_value(1)
        root["namedVariants"][0]["variant"]["$class"] = "hclNotInTheTemplate"
        with self.assertRaises(hktagfile.TagfileError):
            hktagwrite.write(blob, root)


class MathTests(unittest.TestCase):
    def test_triangle_frame_is_the_measured_convention(self):
        v = [np.array(p, float) for p in ((0.0, 0.0, 1.0), (0.03, 0.0, 1.0), (0.0, 0.02, 0.99))]
        f = smpcloth.triangle_frame(*v)
        c = sum(v) / 3
        np.testing.assert_allclose(f[:3, 3], c)
        np.testing.assert_allclose(f[:3, 0], v[0] - c)
        np.testing.assert_allclose(f[:3, 1], v[1] - c)
        np.testing.assert_allclose(f[:3, 2], np.cross(v[1] - v[0], v[2] - v[0]) / 3)

    def test_packed_vectors(self):
        n = np.array([0.28, 0.045, -0.959])
        vals = smpcloth.pack_vector3(n)
        self.assertEqual(vals[3], 0x3000)
        np.testing.assert_allclose(smpcloth.unpack_vector3(vals), n, atol=1e-4)
        self.assertEqual(list(smpcloth.unpack_vector3([9172, 1471, -31424, 12288]).round(4)),
                         [0.2799, 0.0449, -0.959])                            # a value from a game hair
        for p in ((0.1, -1.7, 0.5), (1e-3, 0, 0), (-12.0, 3.0, 0.25)):
            back = smpcloth.unpack_vector3(smpcloth.pack_position(p))
            np.testing.assert_allclose(back, p, atol=max(abs(x) for x in p) * 1e-4)

    def test_quaternions(self):
        for q in ((0, 0, 0, 1), (0.0048, 0.7071, 0.7071, 0.0048), (0.5, -0.5, 0.5, 0.5)):
            q = np.array(q) / np.linalg.norm(q)
            back = smpcloth.matrix_quat(smpcloth.quat_matrix(q))
            self.assertTrue(np.allclose(back, q, atol=1e-6) or np.allclose(back, -q, atol=1e-6))

    def test_bitfield(self):
        bf = smpcloth.bitfield([0, 34, 40], 70)
        self.assertEqual(bf["storage"]["numBits"], 70)
        self.assertEqual(bf["storage"]["words"], [1, 4 | (1 << 8), 0])


def chain(names, host="C_Head", start=(0.05, -0.08, 1.65), step=(0.0, -0.01, -0.06), mass=0.2, limit=0.4):
    out, parent = [], host
    for k, nm in enumerate(names):
        m = np.eye(4)
        m[:3, 3] = np.array(start) + k * np.array(step)
        out.append(smpcloth.ChainBone(nm, parent, m, mass, limit))
        parent = nm
    return out


class RigTests(unittest.TestCase):
    def test_chain(self):
        bones = chain(["B1", "B2", "B3"])
        rig = smpcloth.build_rig(bones, {"B1": "C_Head"}, smpcloth.Settings(balance=False))
        self.assertEqual((len(rig.positions), len(rig.fixed), len(rig.triangles)), (8, 2, 6))
        self.assertEqual([b for b, _t in rig.driven], ["B1", "B2", "B3"])
        fixed = set(rig.fixed)
        self.assertFalse(any(i in fixed and j in fixed for i, j in rig.links))
        for name, t in rig.driven:                                             # the bone sits on its triangle
            b = next(x for x in bones if x.name == name)
            self.assertAlmostEqual(float(np.linalg.norm(rig.positions[rig.triangles[t][0]] - b.world[:3, 3])), 0.0)
            v = rig.positions[list(rig.triangles[t])]
            self.assertGreater(np.linalg.norm(np.cross(v[1] - v[0], v[2] - v[0])), 1e-6)
        reach = [d for p, d in sorted(rig.ranges)][::2]
        self.assertEqual(reach, sorted(reach))                                 # lower joints may move further
        self.assertEqual(rig.masses[rig.fixed[0]], 0.0)
        self.assertTrue(all(h == "C_Head" for h in rig.host))

    def test_ribbon_side_is_across_the_body_on_every_bone(self):
        bones = chain(["C1", "C2", "C3"], step=(0.0, 0.03, -0.06))
        flip = np.diag([-1.0, -1.0, 1.0])                                      # own axes turned half a turn
        bones[1].world[:3, :3] = flip
        rig = smpcloth.build_rig(bones, {"C1": "C_Head"}, smpcloth.Settings(balance=False))
        sides = []
        for name, t in rig.driven:
            a0, b0, a1 = rig.triangles[t]
            sides.append(rig.positions[b0] - rig.positions[a0])
            along = rig.positions[a1] - rig.positions[a0]
            self.assertAlmostEqual(float(sides[-1] @ along), 0.0, places=9)      # perpendicular to the segment
        for v in sides:
            self.assertGreater(v[0], 0.0)                                       # +X on every joint: no built-in twist
        sideways = chain(["S1", "S2"], step=(0.06, 0.0, -0.005))
        rig = smpcloth.build_rig(sideways, {"S1": "C_Head"}, smpcloth.Settings(balance=False))
        a0, b0, _a1 = rig.triangles[rig.driven[0][1]]
        self.assertGreater(abs((rig.positions[b0] - rig.positions[a0])[1]), 0.9 * smpcloth.Settings.width)

    def test_mass_scale(self):
        bones = chain(["M1", "M2"])
        a = smpcloth.build_rig(bones, {"M1": "C_Head"}, smpcloth.Settings(balance=False))
        b = smpcloth.build_rig(bones, {"M1": "C_Head"}, smpcloth.Settings(mass_scale=3.0, balance=False))
        np.testing.assert_allclose(b.masses, [3.0 * m for m in a.masses])
        self.assertEqual({b.masses[i] for i in b.fixed}, {0.0})

    def test_soft_diagonal_brace_against_twist(self):
        bones = chain(["B1", "B2", "B3"])
        rig = smpcloth.build_rig(bones, {"B1": "C_Head"}, smpcloth.Settings(balance=False))
        tri = dict(rig.driven)
        braces = set()
        for name in ("B1", "B2", "B3"):                                       # (A0, B0, A1), (B0, B1, A1)
            a0, b0, a1 = rig.triangles[tri[name]]
            b1 = rig.triangles[tri[name] + 1][1]
            braces.add(tuple(sorted((a0, b1))))
        self.assertTrue(braces <= set(rig.links))
        self.assertEqual({rig.soft[b] for b in braces}, {0.3})
        inv = [0.0 if i in set(rig.fixed) else 1.0 for i in range(len(rig.positions))]
        rest = lambda i, j: float(np.linalg.norm(rig.positions[i] - rig.positions[j]))
        batches, singles = smpcloth._std_links(rig.links, inv, rest, rig.soft)
        got = {}
        for b in batches:
            for k in range(len(b["particlesA"])):
                got[tuple(sorted((b["particlesA"][k], b["particlesB"][k])))] = b["stiffnessesA"][k] - b["stiffnessesB"][k]
        for x in singles:
            got[tuple(sorted((x["particleA"], x["particleB"])))] = x["stiffnessA"] - x["stiffnessB"]
        for l, k in got.items():
            self.assertAlmostEqual(k, 0.3 if l in braces else 1.0)               # weights scaled by the softness
        stiff = smpcloth.build_rig(bones, {"B1": "C_Head"}, smpcloth.Settings(twist=0.0, balance=False))
        self.assertEqual(len(rig.links) - len(stiff.links), 3)

    def test_neighbouring_chains_are_tied_into_a_sheet(self):
        left = chain(["L1", "L2", "L3"], start=(0.03, -0.08, 1.65))
        right = chain(["R1", "R2", "R3"], start=(-0.03, -0.08, 1.65))
        far = chain(["F1", "F2"], start=(0.0, 0.30, 1.65))                   # 38 cm away: left alone
        bones = left + right + far
        hosts = {"L1": "C_Head", "R1": "C_Head", "F1": "C_Head"}
        rig = smpcloth.build_rig(bones, hosts, smpcloth.Settings(balance=False))
        self.assertEqual(rig.report["lateral_links"], 6)                     # 3 free joints x (A-A, B-B)
        a_of = {name: rig.triangles[t][0] for name, t in rig.driven}
        linked = {tuple(sorted(l)) for l in rig.links}
        self.assertIn(tuple(sorted((a_of["L2"], a_of["R2"]))), linked)       # joint to joint at the same depth
        self.assertFalse(any(i in {a_of["F2"]} or j in {a_of["F2"]} for i, j in linked
                             if {i, j} & {a_of["L2"], a_of["R2"]}))
        loose = smpcloth.build_rig(bones, hosts, smpcloth.Settings(lateral=0.0, balance=False))
        self.assertEqual(loose.report["lateral_links"], 0)
        self.assertEqual(len(rig.links) - len(loose.links), 6)

    def test_balanced_rig_mirrors_the_side_row(self):
        bones = chain(["B1", "B2", "B3"])
        one = smpcloth.build_rig(bones, {"B1": "C_Head"}, smpcloth.Settings(balance=False))
        rig = smpcloth.build_rig(bones, {"B1": "C_Head"}, smpcloth.Settings())
        self.assertEqual((len(rig.positions), len(rig.fixed)), (12, 3))       # A, B and C per joint
        self.assertEqual([b for b, _t in rig.driven], ["B1", "B2", "B3"])
        for (_n, t1), (_m, t2) in zip(one.driven, rig.driven):               # the bones' triangles as before
            np.testing.assert_allclose(one.positions[list(one.triangles[t1])], rig.positions[list(rig.triangles[t2])])
        m = np.array(rig.masses)
        for name, t in rig.driven:
            a0, b0, a1 = rig.triangles[t]
            c0 = next(c for c, x, y in rig.triangles if (x, y) == (a1, a0))
            np.testing.assert_allclose(rig.positions[c0] - rig.positions[a0],
                                       -(rig.positions[b0] - rig.positions[a0]))   # C mirrors B about the joint
            self.assertEqual(m[b0], m[c0])                                   # so the section's weight sits on A:
            centre = (m[a0] * rig.positions[a0] + m[b0] * rig.positions[b0] + m[c0] * rig.positions[c0])
            if m[a0] + m[b0] + m[c0] > 0:                                    # gravity does not turn the lock
                np.testing.assert_allclose(centre / (m[a0] + m[b0] + m[c0]), rig.positions[a0], atol=1e-12)
            b1 = rig.triangles[t + 1][1]
            c1 = next(y for x, y, z in rig.triangles if x == c0 and z == a1 and y != a1)
            self.assertIn(tuple(sorted((b1, c1))), set(rig.links))           # the section holds its width
        self.assertGreater(len(rig.links), len(one.links))

    def test_branch_shares_or_links_its_joint(self):
        bones = chain(["T1", "T2"])
        m = bones[1].world.copy()
        m[:3, 3] += (0.02, 0.0, 0.0)                                           # starts off T1's end: own joint
        bones.append(smpcloth.ChainBone("T2b", "T1", m))
        rig = smpcloth.build_rig(bones, {"T1": "C_Head"}, smpcloth.Settings())
        self.assertEqual(len(rig.driven), 3)
        self.assertEqual(len(rig.positions), 15)                              # T1 2 joints, T2 1, T2b 2 of its own (x A, B, C)
        a0 = rig.triangles[dict(rig.driven)["T2b"]][0]
        t1_origin, t1_end = rig.triangles[dict(rig.driven)["T1"]][0], rig.triangles[dict(rig.driven)["T1"]][2]
        linked = {tuple(sorted(l)) for l in rig.links}
        self.assertIn(tuple(sorted((t1_origin, a0))), linked)                 # held by both joints of its parent
        self.assertIn(tuple(sorted((t1_end, a0))), linked)

    def test_standard_link_batches(self):
        links = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (0, 6)]
        inv = [0.0, 5.0, 5.0, 5.0, 5.0, 5.0, 10.0]
        batches, singles = smpcloth._std_links(links, inv, lambda i, j: 0.1)
        for b in batches:
            self.assertEqual(len(set(b["particlesA"] + b["particlesB"])), 8)
            for a_, b_, sa, sb in zip(b["particlesA"], b["particlesB"], b["stiffnessesA"], b["stiffnessesB"]):
                self.assertAlmostEqual(sa, inv[a_] / (inv[a_] + inv[b_]))
                self.assertAlmostEqual(sb, -inv[b_] / (inv[a_] + inv[b_]))
        got = {tuple(sorted(x)) for b in batches for x in zip(b["particlesA"], b["particlesB"])}
        got |= {tuple(sorted((s["particleA"], s["particleB"]))) for s in singles}
        self.assertEqual(got, {tuple(sorted(l)) for l in links})


def tracker(n):
    z = smpcloth.bitfield([], n)
    return {"read": z, "readBeforeWrite": z, "written": z}


def template_root(object_space=False, with_range=True):
    """A cloth template as hktagfile decodes it: skeleton [Root, C_Chest, C_Head, Old_1 (driven)], one chest capsule,
    the four operators and two states."""
    def pose(t, q=(0, 0, 0, 1)):
        return {"translation": [*t, 0.0], "rotation": list(q), "scale": [1.0, 1.0, 1.0, 0.0]}
    q90 = (0.0, -math.sqrt(0.5), 0.0, math.sqrt(0.5))                         # bone x axis = model z, as C_Head
    sk = {"name": "T", "parentIndices": [-1, 0, 1, 2],
          "bones": [{"name": n, "lockTranslation": False} for n in ("Root", "C_Chest", "C_Head", "Old_1")],
          "referencePose": [pose((0, 0, 0)), pose((0, -0.017, 1.23), q90), pose((0.4, 0.015, 0), (0, 0, 0, 1)),
                            pose((0.05, 0, 0.05))], "$class": "hkaSkeleton"}
    sets = [{"$class": "hclStandardLinkConstraintSetMx"}, {"$class": "hclStretchLinkConstraintSetMx"}]
    if with_range:
        sets.append({"$class": "hclLocalRangeConstraintSet"})
    sim = {"name": "Sim", "staticConstraintSets": sets,
           "perInstanceCollidables": [{"name": "collision_capsule_C_Chest", "shape": {
               "$class": "hclCapsuleShape", "start": [-0.13, 0.05, 0.18, 0], "end": [0.13, 0.05, 0.18, 0],
               "radius": 0.085}, "$class": "hclCollidable"}],
           "collidableTransformMap": {"transformSetIndex": 0, "transformIndices": [1],
                                      "offsets": [smpcloth.mat4_values(np.eye(4))]},
           "transferMotionData": {"transformIndex": 2}, "virtualCollisionPointsData": {"blocks": [], "numVCPoints": 0,
                                                                                         "numLandscapeVCPoints": 0},
           "$class": "hclSimClothData"}
    skin_cls = "hclObjectSpaceSkinPNOperator" if object_space else "hclBoneSpaceSkinPNOperator"
    ops = [{"$class": skin_cls, "name": "Skin"}, {"$class": "hclMoveParticlesOperator", "name": "Move"},
           {"$class": "hclSimulateOperator", "name": "Sim", "simulateOpConfigs": [{"name": "Default"}]},
           {"$class": "hclSimpleMeshBoneDeformOperator", "name": "Deform",
            "triangleBonePairs": [{"boneOffset": 3 * 64, "triangleOffset": 0}]}]
    if object_space:
        ops.append({"$class": "hclGatherAllVerticesOperator", "name": "Gather"})
    cd = {"name": "T", "simClothDatas": [sim],
          "bufferDefinitions": [{"bufferName": "Scratch", "$class": "hclScratchBufferDefinition"},
                                {"bufferName": "Sim", "$class": "hclBufferDefinition"}],
          "transformSetDefinitions": [{"name": "T", "numTransforms": 4}], "operators": ops,
          "clothStateDatas": [{"name": n, "dependencyGraph": {}} for n in ("Simulate", "Animate")],
          "$class": "hclClothData"}
    return {"hclClothData": cd, "hkaSkeleton": sk}


class BuildTests(unittest.TestCase):
    def build(self, **kw):
        root = template_root(**kw)
        world = smpcloth.skeleton_world(smpcloth.human_skeleton(root))
        head = world[2]
        bones = chain(["S2S_A1", "S2S_A2"], start=tuple(head[:3, 3] + (0.06, -0.05, -0.02)))
        bones += chain(["S2S_B1"], start=tuple(head[:3, 3] + (-0.06, -0.05, -0.02)))
        cap = smpcloth.Capsule("S2S_head", "C_Head", np.array([0, 0.013, 0.067]), np.array([0, 0.033, 0.067]), 0.06)
        out, rig = smpcloth.build_cloth(root, bones, {"S2S_A1": "C_Head", "S2S_B1": "C_Head"}, [cap])
        return root, out, rig

    def test_bone_space(self):
        _t, out, rig = self.build()
        chk = smpcloth.verify_root(out)
        self.assertLess(chk["bone_from_triangle"], 1e-9)
        self.assertLess(chk["pinned_from_skin"], 1e-9)
        self.assertLess(chk["link_rest"], 1e-9)
        self.assertEqual(chk["batches_sharing_particles"], 0)
        names = [b["name"] for b in out["hkaSkeleton"]["bones"]]
        self.assertEqual(names, ["Root", "C_Chest", "C_Head", "S2S_A1", "S2S_A2", "S2S_B1"])   # Old_1 dropped
        self.assertEqual(out["hkaSkeleton"]["parentIndices"][3:], [2, 3, 2])
        cd = out["hclClothData"]
        sim = cd["simClothDatas"][0]
        self.assertEqual([c["name"] for c in sim["perInstanceCollidables"]], ["collision_capsule_C_Chest", "S2S_head"])
        self.assertEqual(sim["collidableTransformMap"]["transformIndices"], [1, 2])
        off = np.array(sim["collidableTransformMap"]["offsets"][1]).reshape(4, 4).T
        np.testing.assert_allclose(off[:3, :3], smpcloth.skeleton_world(out["hkaSkeleton"])[2][:3, :3].T, atol=1e-6)
        fixed = set(sim["fixedParticles"])
        self.assertEqual({sim["staticCollisionMasks"][i] for i in fixed}, {0})
        self.assertEqual({m for i, m in enumerate(sim["staticCollisionMasks"]) if i not in fixed}, {3})
        self.assertEqual([c["$class"] for c in sim["staticConstraintSets"]],
                         ["hclStandardLinkConstraintSetMx", "hclStretchLinkConstraintSetMx",
                          "hclLocalRangeConstraintSet"])
        self.assertEqual(cd["operators"][2]["simulateOpConfigs"][0]["constraintExecution"], [2, 0, 1, -1])
        self.assertEqual(cd["transformSetDefinitions"][0]["numTransforms"], 6)
        written = cd["operators"][3]["usedTransformSets"][0]["transformSetUsage"]["perComponentTransformTrackers"][0]
        self.assertEqual(written["written"]["storage"]["words"], [(1 << 3) | (1 << 4) | (1 << 5)])
        skin_read = cd["operators"][0]["usedTransformSets"][0]["transformSetUsage"]["perComponentTransformTrackers"]
        self.assertEqual(skin_read[0]["read"]["storage"]["words"], [1 << 2])
        sim_read = cd["operators"][2]["usedTransformSets"][0]["transformSetUsage"]["perComponentTransformTrackers"]
        self.assertEqual(sim_read[1]["read"]["storage"]["words"], [(1 << 1) | (1 << 2)])
        self.assertEqual(sim["transferMotionData"]["transformIndex"], 2)
        self.assertAlmostEqual(sim["simulationInfo"]["globalDampingPerSecond"], 0.97)   # no template value: default
        self.assertEqual({p["radius"] for p in sim["particleDatas"]}, {0.02})
        self.assertEqual(len(rig.driven), 3)

    def test_damping_from_the_template_unless_given(self):
        root = template_root()
        root["hclClothData"]["simClothDatas"][0]["simulationInfo"] = {"gravity": [0, 0, -9.81, 0],
                                                                      "globalDampingPerSecond": 0.8}
        bones = chain(["S2S_A1"], start=(0.06, -0.05, 1.8))
        out, _rig = smpcloth.build_cloth(root, bones, {"S2S_A1": "C_Head"}, [])
        self.assertAlmostEqual(out["hclClothData"]["simClothDatas"][0]["simulationInfo"]["globalDampingPerSecond"], 0.8)
        out, _rig = smpcloth.build_cloth(root, bones, {"S2S_A1": "C_Head"}, [], smpcloth.Settings(damping=0.5))
        self.assertAlmostEqual(out["hclClothData"]["simClothDatas"][0]["simulationInfo"]["globalDampingPerSecond"], 0.5)
        out, _rig = smpcloth.build_cloth(root, bones, {"S2S_A1": "C_Head"}, [], keep_template_colliders=False)
        self.assertEqual(out["hclClothData"]["simClothDatas"][0]["perInstanceCollidables"], [])

    def test_object_space_template_without_range(self):
        _t, out, _rig = self.build(object_space=True, with_range=False)
        cd = out["hclClothData"]
        self.assertEqual(len(cd["operators"]), 4)                              # the gather dropped
        self.assertIn("objectSpaceDeformer", cd["operators"][0])
        chk = smpcloth.verify_root(out)
        self.assertLess(chk["pinned_from_skin"], 1e-4)                         # packed positions
        self.assertLess(chk["bone_from_triangle"], 1e-9)
        sets = cd["simClothDatas"][0]["staticConstraintSets"]
        self.assertEqual(len(sets), 2)
        self.assertEqual(cd["operators"][2]["simulateOpConfigs"][0]["constraintExecution"], [0, 1, -1])

    def test_errors(self):
        root = template_root()
        with self.assertRaises(smpcloth.ClothBuildError):
            smpcloth.build_cloth(root, chain(["C_Head"]), {"C_Head": "C_Head"}, [])
        with self.assertRaises(smpcloth.ClothBuildError):
            smpcloth.build_cloth(root, chain(["X1"], host="Nope"), {}, [])

    def test_template_score(self):
        self.assertEqual(smpcloth.template_score(template_root()), 3)
        self.assertEqual(smpcloth.template_score(template_root(with_range=False)), 1)


# ------------------------------------------------------------------------------------------------ Skyrim hair
SKY_BONES = [b"NPC Head [Head]", b"Hair 1", b"Hair 2", b"Hair 3"]
SMP_XML = b"""<?xml version="1.0"?><system>
<bone name="Hair 1"/><bone name="NPC Head [Head]"/>
<bone-default><mass>0,25</mass><linearDamping>0.6</linearDamping></bone-default>
<bone name="Hair 2"/><bone name="Hair 3"/>
<generic-constraint-default><angularLowerLimit x="-0.3" y="-0.3" z="-0.3"/>
<angularUpperLimit x="0.3" y="0.3" z="0.3"/></generic-constraint-default>
<generic-constraint bodyA="Hair 2" bodyB="Hair 1"/><generic-constraint bodyA="Hair 3" bodyB="Hair 2"/>
</system>"""
# a strand: head at z=120 (units); Hair 1 at (0,-5,120) under the head, Hair 2 6 units below, Hair 3 6 more
VERTS = [(0, -6, 121), (1, -6, 116), (0, -6, 110), (1, -6, 104), (0, -6, 100)]
WEIGHTS = [[(0, 1.0)], [(1, 1.0)], [(2, 1.0)], [(3, 0.5), (2, 0.5)], [(3, 1.0)]]


def hair_nif_bytes(config=None):
    n = F.SseNif()
    root = n.reserve("NiNode")
    head, h1, h2, h3 = (n.reserve("NiNode") for _ in range(4))
    n.node(h3, SKY_BONES[3], [], t=(0, 0, -6))
    n.node(h2, SKY_BONES[2], [h3], t=(0, 0, -6))
    n.node(h1, SKY_BONES[1], [h2], t=(0, -5, 0))
    n.node(head, SKY_BONES[0], [h1], t=(0, 0, 120))
    shader = n.lighting("textures\\hair\\h.dds", "textures\\hair\\h_n.dds", double_sided=True)
    world = {0: (0, 0, 120), 1: (0, -5, 120), 2: (0, -5, 114), 3: (0, -5, 108)}
    sd = struct.pack("<9f3ff", 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1.0) + struct.pack("<IB", 4, 1)
    for b in range(4):
        x, y, z = world[b]
        sd += struct.pack("<9f3ff", 1, 0, 0, 0, 1, 0, 0, 0, 1, -x, -y, -z, 1.0) + struct.pack("<4f", 0, 0, 0, 50)
        lst = [(v, w) for v, ws in enumerate(WEIGHTS) for bb, w in ws if bb == b]
        sd += struct.pack("<H", len(lst)) + b"".join(struct.pack("<Hf", v, w) for v, w in lst)
    data = n.add("NiSkinData", sd)
    desc = 10 | (4 << 8) | (5 << 16) | (6 << 20) | (7 << 28) | (0x5B << 44)
    vb = b""
    for v, (x, y, z) in enumerate(VERTS):
        local = WEIGHTS[v] + [(0, 0.0)] * (4 - len(WEIGHTS[v]))
        vb += struct.pack("<3ff", x, y, z, 0.0) + struct.pack("<2e", v / 5, 0.5) + bytes([127, 127, 255, 0]) \
            + bytes([255, 127, 127, 0]) + struct.pack("<4e", *[w for _, w in local]) + bytes(i for i, _ in local)
    sp = struct.pack("<IIIQ", 1, len(vb), 40, desc) + vb
    sp += struct.pack("<5H", 5, 3, 4, 0, 4) + struct.pack("<4H", 0, 1, 2, 3)
    sp += b"\x01" + struct.pack("<5H", *range(5)) + b"\x01" + bytes(16 * 5)
    sp += b"\x01" + struct.pack("<9H", 0, 1, 2, 1, 2, 3, 2, 3, 4) + b"\x01" + bytes(20)
    sp += b"\x00\x01" + struct.pack("<Q", desc) + struct.pack("<9H", 0, 1, 2, 1, 2, 3, 2, 3, 4)
    part = n.add("NiSkinPartition", sp)
    inst = n.add("BSDismemberSkinInstance", struct.pack("<iiiI", data, part, root, 4)
                 + struct.pack("<4i", head, h1, h2, h3) + struct.pack("<I", 1) + struct.pack("<HH", 257, 30))
    body = n.av(n.s(b"KSSMP_Test")) + struct.pack("<4f", 0, 0, 0, 1) + struct.pack("<iii", inst, shader, -1) \
        + struct.pack("<Q", desc) + struct.pack("<HHI", 3, 5, 0) + struct.pack("<I", 0)
    sh = n.add("BSTriShape", body)
    n.node(root, b"Hair", [head, sh])
    if config:
        n.add("NiStringExtraData", struct.pack("<II", n.s(b"HDT Skinned Mesh Physics Object"), n.s(config)))
    return n.bytes()


def sf_world():
    world = smpcloth.skeleton_world(smpcloth.human_skeleton(template_root()))
    return {"Root": world[0], "C_Chest": world[1], "C_Head": world[2]}


class HairTests(unittest.TestCase):
    def test_convert(self):
        w = sf_world()
        hair = skyrimhair.convert(hair_nif_bytes(), SMP_XML, w)
        self.assertEqual([b.name for b in hair.bones], ["S2S_Hair_2", "S2S_Hair_3"])
        self.assertEqual(hair.host_of_root, {"S2S_Hair_2": "C_Head"})       # Hair 1 (kinematic) merged into C_Head
        self.assertEqual(hair.bones[1].parent, "S2S_Hair_2")
        self.assertAlmostEqual(hair.bones[0].mass, 0.25)                    # comma decimal from the config
        self.assertAlmostEqual(hair.bones[1].limit, 0.3)
        u, s, off = skyrimhair.UNIT, skyrimhair.HEAD_SCALE, np.array(skyrimhair.HEAD_OFFSET)
        want = w["C_Head"][:3, 3] + off + s * (np.array([0, -5, 114]) - np.array([0, 0, 120])) * u
        np.testing.assert_allclose(hair.bones[0].world[:3, 3], want, atol=1e-6)
        sh = hair.shapes[0]
        self.assertEqual([dict(x) for x in sh.weights][:3], [{"C_Head": 1.0}, {"C_Head": 1.0}, {"S2S_Hair_2": 1.0}])
        self.assertEqual(dict(sh.weights[3]), {"S2S_Hair_3": 0.5, "S2S_Hair_2": 0.5})
        np.testing.assert_allclose(sh.positions[0], w["C_Head"][:3, 3] + off + s * np.array([0, -6, 1]) * u,
                                   atol=1e-6)
        tip = hair.bones[1].tip                                                # down to the lowest vertex it moves
        self.assertAlmostEqual(float(tip[2]), float(sh.positions[4][2]), places=6)

    def test_nif_files(self):
        w = sf_world()
        hair = skyrimhair.convert(hair_nif_bytes(), SMP_XML, w)
        payload = b"TAG0-cloth-bytes"
        files = skyrimhair.nif_files(hair, ["materials\\s2s\\hair.mat"], payload, w, "s2s/hair/test", [True])
        self.assertIn("meshes/s2s/hair/test.nif", files)
        n = nif.parse(files["meshes/s2s/hair/test.nif"])
        cloth = [i for i in range(len(n.blocks)) if n.type_of(i) == "BSClothExtraData"]
        self.assertEqual(len(cloth), 1)
        self.assertEqual(sfcloth.payload(n.blocks[cloth[0]]) if payload[4:8] == b"TAG0" else
                         n.blocks[cloth[0]][4:], payload)
        _name, ne = struct.unpack_from("<iI", n.blocks[0], 0)
        self.assertEqual(list(struct.unpack_from(f"<{ne}i", n.blocks[0], 8)), [1, cloth[0]])
        skin = sfnif.parse_skin(n)
        self.assertEqual(skin["bones"], [b"C_Head", b"S2S_Hair_2", b"S2S_Hair_3"])
        world = {"C_Head": w["C_Head"], "S2S_Hair_2": hair.bones[0].world, "S2S_Hair_3": hair.bones[1].world}
        for name, (_sph, rot, tr, sc) in zip(skin["bones"], skin["binds"]):
            bind = np.eye(4)
            bind[:3, :3] = np.array(rot).reshape(3, 3) * sc
            bind[:3, 3] = tr
            np.testing.assert_allclose(bind @ world[name.decode()], np.eye(4), atol=1e-6)
        mesh = [v for k, v in files.items() if k.endswith(".mesh")]
        m = sfmesh.parse(mesh[0])
        self.assertEqual(len(m.positions), 10)                                 # double-sided: back faces added
        self.assertEqual(m.weights_per_vertex, 4)
        for v in range(len(m.positions)):
            self.assertEqual(sum(wt for _b, wt in m.weights[4 * v:4 * v + 4]), 65535)

    def test_head_capsule_clears_the_particles(self):
        w = sf_world()
        hair = skyrimhair.convert(hair_nif_bytes(), SMP_XML, w)
        cap = skyrimhair.head_capsule(w, hair)
        head = w["C_Head"][:3, 3]
        for b in hair.bones[1:]:
            q = b.world[:3, 3] - head
            self.assertGreater(float(np.linalg.norm(q - cap.start)), cap.radius)

    def test_bone_names(self):
        self.assertEqual(skyrimhair.bone_name("Zoella Flyaways L 1"), "S2S_Zoella_Flyaways_L_1")
        self.assertEqual(skyrimhair.bone_name("Anna Back 2"), "S2S_Anna_Back_2")


class ControlHelperTests(unittest.TestCase):
    def test_facebones_template_reads_the_vanilla_hair_skin(self):
        import hair_pack
        from unittest import mock
        from fo4sf import convert_static
        pts = [(0.0, 0.0, 1.8), (0.05, 0.0, 1.7), (0.0, -0.1, 1.6)]
        scale, raw = sfmesh.encode_positions(pts)
        m = sfmesh.SfMesh(triangles=[(0, 1, 2)], scale=scale, positions=raw, weights_per_vertex=2,
                          weights=[(0, 65535), (0, 0), (1, 52428), (0, 13107), (2, 65535), (0, 0)])
        sfmesh.build_meshlets(m)
        data = sfmesh.serialize(m)
        d, f = convert_static.mesh_file_path(data)
        ident = (1, 0, 0, 0, 1, 0, 0, 0, 1)
        sh = sfnif.SkinnedShape(b"Bob", f"{d}\\{f}".encode(), 3, 3, "materials\\hair.mat",
                                [b"faceBone_C_HeadTop", b"faceBone_L_Temple", b"Hair_1"],
                                [((0, 0, 0, 1), ident, (0, 0, -1.76), 1.0), ((0, 0, 0, 1), ident, (-0.06, 0, -1.7), 1.0),
                                 ((0, 0, 0, 1), ident, (0, 0.1, -1.6), 1.0)])
        bob = nif.serialize(sfnif.build_skinned_nif(b"Bob", [sh]))
        hat = sfnif.SkinnedShape(b"Hat", b"aa\\bb", 3, 3, "materials\\hat.mat", [b"faceBone_C_HeadTop"],
                                 [((0, 0, 0, 1), ident, (0, 0, -1.75), 1.0)])
        game = {"meshes/clothes/hat_f_facebones.nif": nif.serialize(sfnif.build_skinned_nif(b"Hat", [hat])),
                "meshes/hair/bob_f_facebones.nif": bob, f"geometries/{d}/{f}.mesh": data}
        rep = {}
        with mock.patch.object(hair_pack, "read_game_file",
                               lambda sfp, rel: game.get(rel.replace("\\", "/").lower())):
            fb = hair_pack.facebones_template("sf", "Clothes\\Hat_F.nif", rep, "Meshes01.ba2:meshes/hair/bob_f.nif")
        self.assertEqual(rep["facebones"]["used"], "hair")
        self.assertEqual(rep["facebones"]["hair_skin_vertices"], 3)
        self.assertEqual(sorted(fb[2]), ["faceBone_C_HeadTop", "faceBone_L_Temple"])
        points, weights = fb[4]
        np.testing.assert_allclose(points, pts, atol=1e-4)
        self.assertEqual([b for b, _w in weights[1]], ["faceBone_L_Temple", "faceBone_C_HeadTop"])
        self.assertAlmostEqual(weights[1][0][1], 0.8, places=4)
        self.assertNotIn("_face_skin", rep)

    def test_tint_layer_gets_a_higher_cutoff(self):
        import hair_pack
        from unittest import mock
        calls = []

        class Conv:
            def skyrim_material(self, *args, **kw):
                calls.append(args)
                return "materials\\tint.mat"

            def _shape_material(self, n, sh):
                return "materials\\plain.mat"
        sh = skyrimhair.HairShape(b"Hairline", np.zeros((1, 3)), [], [], [], [], [[]], 7, 8, 0)
        with mock.patch.object(hair_pack.skyrimnif, "texture_set", lambda n, ref: ["tex\\hl.dds", "tex\\hl_n.dds"]):
            got = hair_pack.tint_material(Conv(), None, sh, 128)
        self.assertEqual(got, "materials\\tint.mat")
        self.assertEqual(calls, [("tex\\hl.dds", "tex\\hl_n.dds", True, False, 128)])   # cutout at 128, no blend

    def test_hide_hair_replaces_morph_hair(self):
        import hair_pack
        arma = (b"ARMA", b"", [(b"EDID", b"X\0"), (b"BO64", struct.pack("<Q", 0x12))], 1)   # the Akila hat's addon
        bits = struct.unpack("<Q", dict(hair_pack.hide_hair(arma)[2])[b"BO64"])[0]
        self.assertEqual(bits, 0x11)                                          # Hide Hair + Hat, no Morph Hair

    def test_nif_materials_and_arma_model(self):
        import hair_pack
        sh = sfnif.SkinnedShape(b"Hat", b"aa\\bb", 3, 3, "materials\\clothes\\hat.mat", [b"C_Head"],
                                [((0.0, 0.0, 0.0, 1.0), (1, 0, 0, 0, 1, 0, 0, 0, 1), (0, 0, 0), 1.0)])
        raw = nif.serialize(sfnif.build_skinned_nif(b"Hat", [sh]))
        self.assertEqual(hair_pack.nif_materials(raw), ["materials\\clothes\\hat.mat"])
        arma = (b"ARMA", b"", [(b"MOD2", b"Clothes\\Hat_M.nif\0"), (b"MOD3", b"Clothes\\Hat_F.nif\0")], 1)
        self.assertEqual(hair_pack.arma_model(arma), "Clothes\\Hat_F.nif")
        self.assertEqual(hair_pack.arma_model((b"ARMA", b"", [(b"MOD2", b"M.nif\0"), (b"MOD3", b"\0")], 1)), "M.nif")


class BodyColliderTests(unittest.TestCase):
    def test_body_capsules_mirror_shrink_and_skip(self):
        def at(x, y, z):
            m = np.eye(4)
            m[:3, 3] = (x, y, z)
            return m
        w = {"C_Neck": at(0, -0.04, 1.49), "C_Chest": at(0, -0.02, 1.23), "C_Spine1": at(0, -0.01, 1.11),
             "C_Hips": at(0, -0.02, 1.06), "L_Thigh": at(-0.12, -0.02, 0.94), "R_Thigh": at(0.12, -0.02, 0.94),
             "L_Biceps": at(-0.15, -0.05, 1.40)}                                  # no R_Biceps: skipped
        far = smpcloth.ChainBone("S2S_A", "C_Head", at(0, -0.40, 1.30), 0.1, 0.3, np.array([0, -0.40, 1.0]))
        hair = skyrimhair.Hair([], [far], {}, {})
        caps, rep = skyrimhair.body_capsules(w, hair)
        names = {c.name: c for c in caps}
        self.assertEqual(rep["S2S_R_upperarm"], "no bone R_Biceps")
        self.assertEqual(set(names), {"S2S_neck", "S2S_chest", "S2S_waist", "S2S_hips", "S2S_L_thigh", "S2S_R_thigh",
                                      "S2S_L_upperarm"})
        np.testing.assert_allclose(names["S2S_R_thigh"].start, [0.11 - 0.12, 0.0, 0.90 - 0.94], atol=1e-12)
        np.testing.assert_allclose(names["S2S_L_thigh"].start, [-0.11 + 0.12, 0.0, 0.90 - 0.94], atol=1e-12)
        self.assertAlmostEqual(names["S2S_chest"].radius, 0.105)               # hair far behind: full size
        # a particle 0.06 m behind the chest axis: the chest capsule shrinks to keep it outside (minus the margin)
        near = smpcloth.ChainBone("S2S_B", "S2S_A", at(0, -0.06, 1.31), 0.1, 0.3, None)
        caps, rep = skyrimhair.body_capsules(w, skyrimhair.Hair([], [far, near], {}, {}))
        self.assertAlmostEqual(rep["S2S_chest"], 0.06 - 0.025, places=6)          # default margin 2.5 cm
        # one right on the waist axis: that capsule is left out
        on = smpcloth.ChainBone("S2S_C", "S2S_A", at(0, -0.01, 1.14), 0.1, 0.3, None)
        _caps, rep = skyrimhair.body_capsules(w, skyrimhair.Hair([], [far, on], {}, {}))
        self.assertEqual(rep["S2S_waist"], "left out: the hair starts inside it")
        _caps, rep = skyrimhair.body_capsules(w, hair, scale=0.5)
        self.assertAlmostEqual(rep["S2S_hips"], 0.055)


class FaceSkinTests(unittest.TestCase):
    def test_on_face_bones_spreads_the_head_weight_like_the_reference(self):
        sh = skyrimhair.HairShape(b"S", np.array([[0.0, 0.0, 1.80], [0.05, 0.0, 1.70], [0.0, -0.1, 1.2]]),
                                  np.tile([0.0, 0.0, 1.0], (3, 1)), np.tile([1.0, 0.0, 0.0], (3, 1)), [(0, 0)] * 3,
                                  [(0, 1, 2)], [[("C_Head", 1.0)], [("C_Head", 0.5), ("S2S_X", 0.5)],
                                                [("S2S_X", 1.0)]], -1, -1, 0)
        hair = skyrimhair.Hair([sh], [], {}, {})
        ref = np.array([[0.0, 0.0, 1.80], [0.05, 0.0, 1.70], [0.0, 0.5, 1.0]])
        refw = [[("faceBone_C_HeadTop", 1.0)], [("faceBone_L_Temple", 0.8), ("faceBone_C_HeadTop", 0.2)],
                [("Hair_1", 1.0)]]                                            # not a face vertex: ignored
        out = skyrimhair.on_face_bones(hair, ref, refw, k=1)
        w = out.shapes[0].weights
        self.assertEqual(w[0], [("faceBone_C_HeadTop", 1.0)])
        self.assertEqual(dict(w[1]), {"S2S_X": 0.5, "faceBone_L_Temple": 0.4, "faceBone_C_HeadTop": 0.1})
        self.assertEqual(w[2], [("S2S_X", 1.0)])                             # no head weight: unchanged
        blend = skyrimhair.on_face_bones(hair, ref, refw, k=2).shapes[0].weights[0]
        self.assertAlmostEqual(sum(x for _b, x in blend), 1.0)
        self.assertGreater(dict(blend)["faceBone_C_HeadTop"], 0.9)            # the exact match dominates
        with self.assertRaises(skyrimhair.HairError):
            skyrimhair.on_face_bones(hair, ref[2:], refw[2:])

    def test_face_capsule_shrinks_or_stays_out(self):
        w = sf_world()
        far = smpcloth.ChainBone("S2S_A", "C_Head", np.eye(4), 0.1, 0.3, None)
        far.world[:3, 3] = w["C_Head"][:3, 3] + (0.0, -0.3, 0.0)
        cap = skyrimhair.face_capsule(w, skyrimhair.Hair([], [far], {}, {}))
        self.assertEqual((cap.name, cap.bone, cap.radius), ("S2S_face", "C_Head", 0.055))
        near = smpcloth.ChainBone("S2S_B", "S2S_A", np.eye(4), 0.1, 0.3, None)
        near.world[:3, 3] = w["C_Head"][:3, 3] + (0.0, 0.035 + 0.06, 0.0)      # 6 cm in front of the axis
        cap = skyrimhair.face_capsule(w, skyrimhair.Hair([], [far, near], {}, {}))
        self.assertAlmostEqual(cap.radius, 0.06 - 0.024)
        inside = smpcloth.ChainBone("S2S_C", "S2S_A", np.eye(4), 0.1, 0.3, None)
        inside.world[:3, 3] = w["C_Head"][:3, 3] + (0.0, 0.035, 0.0)
        self.assertIsNone(skyrimhair.face_capsule(w, skyrimhair.Hair([], [far, inside], {}, {})))


class HeadFitTests(unittest.TestCase):
    def test_fit_head_axes_recovers_per_axis_scale(self):
        rng = np.random.default_rng(3)
        d = rng.normal(size=(4000, 3))
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        sf_head = np.eye(4)
        sf_head[:3, 3] = (0.0, -0.002, 1.632)
        sf_pts = sf_head[:3, 3] + d * [0.072, 0.095, 0.09] + [0.0, 0.02, 0.05]
        sky_head = np.eye(4)
        sky_head[:3, 3] = (0.0, -1.5, 120.0)
        sc, off = np.array([0.90, 0.96, 0.99]), np.array([0.0, -0.02, 0.004])
        sky_pts = (sf_pts - sf_head[:3, 3] - off) / sc / skyrimhair.UNIT + sky_head[:3, 3]
        s3, t3, rms = skyrimhair.fit_head_axes(sky_pts, sky_head, sf_pts, sf_head)
        np.testing.assert_allclose(s3, sc, atol=4e-3)
        np.testing.assert_allclose(t3, off, atol=2e-3)
        self.assertLess(rms, 2e-3)
        s1, _t1, rms1 = skyrimhair.fit_head(sky_pts, sky_head, sf_pts, sf_head)
        self.assertLess(rms, rms1)                                             # proportions fit better per axis

    def test_skin_to_model_inverts_the_skin_transform(self):
        from types import SimpleNamespace
        from fo4sf import skyrimskin
        R = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
        st = skyrimskin.Bind(tuple(R.ravel()), (1.0, 2.0, -120.0), 1.0)          # model -> skin
        shape = SimpleNamespace(skin_transform=st)
        p_model = np.array([3.0, 4.0, 121.0])
        p_skin = R @ p_model + [1.0, 2.0, -120.0]
        to_model, rot = skyrimhair.skin_to_model(shape)
        np.testing.assert_allclose(to_model(p_skin), p_model, atol=1e-12)
        np.testing.assert_allclose(rot(R @ [0.0, 0.0, 1.0]), [0.0, 0.0, 1.0], atol=1e-12)
        ident, _ = skyrimhair.skin_to_model(SimpleNamespace(skin_transform=None))
        np.testing.assert_allclose(ident([1, 2, 3]), [1, 2, 3])

    def test_fit_head_recovers_scale_and_offset(self):
        rng = np.random.default_rng(1)
        d = rng.normal(size=(3000, 3))
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        sf_head = np.eye(4)
        sf_head[:3, 3] = (0.0, -0.002, 1.632)
        sf_pts = sf_head[:3, 3] + d * [0.075, 0.095, 0.09] + [0.0, 0.02, 0.05]       # an egg around the skull
        sky_head = np.eye(4)
        sky_head[:3, 3] = (0.0, -1.5, 120.0)                                         # units
        scale, offset = 0.95, np.array([0.001, -0.018, -0.006])
        rel = sf_pts - sf_head[:3, 3]
        sky_pts = (rel - offset) / scale / skyrimhair.UNIT + sky_head[:3, 3]
        s, t, rms = skyrimhair.fit_head(sky_pts, sky_head, sf_pts, sf_head)
        self.assertAlmostEqual(s, scale, places=3)
        np.testing.assert_allclose(t, offset, atol=1e-3)
        self.assertLess(rms, 2e-3)
        with self.assertRaises(skyrimhair.HairError):
            skyrimhair.fit_head(sky_pts[:10], sky_head, sf_pts, sf_head)


class FaceBoneTests(unittest.TestCase):
    def test_face_bone_worlds_invert_the_binds(self):
        rot = (0, -1, 0, 1, 0, 0, 0, 0, 1)
        skin = {"bones": [b"C_Head", b"faceBone_C_HeadTop", b"faceBone_C_Chin"],
                "binds": [((0, 0, 0, 1), (1, 0, 0, 0, 1, 0, 0, 0, 1), (0, 0, -1.6), 1.0),
                          ((0, 0, 0, 1), rot, (0.1, 0.2, -1.75), 1.0),
                          ((0, 0, 0, 1), (1, 0, 0, 0, 1, 0, 0, 0, 1), (0, -0.1, -1.55), 1.0)]}
        w = skyrimhair.face_bone_worlds(skin)
        self.assertEqual(sorted(w), ["faceBone_C_Chin", "faceBone_C_HeadTop"])     # face bones only
        inv = np.eye(4)
        inv[:3, :3] = np.array(rot, float).reshape(3, 3)
        inv[:3, 3] = (0.1, 0.2, -1.75)
        np.testing.assert_allclose(w["faceBone_C_HeadTop"] @ inv, np.eye(4), atol=1e-12)
        self.assertEqual(skyrimhair.pick_face_bone(w), "faceBone_C_HeadTop")
        node = skyrimhair.xf_matrix(((1, 0, 0, 0, 1, 0, 0, 0, 1), (0, 0, 1.6), 1.0))      # an offset shape node
        wn = skyrimhair.face_bone_worlds(skin, node)
        np.testing.assert_allclose(wn["faceBone_C_HeadTop"], node @ w["faceBone_C_HeadTop"], atol=1e-12)
        self.assertEqual(skyrimhair.pick_face_bone({"faceBone_Z": np.eye(4), "faceBone_A": np.eye(4)}), "faceBone_A")

    def test_on_face_bone_moves_only_the_host_weights(self):
        hair = skyrimhair.convert(hair_nif_bytes(), SMP_XML, sf_world())
        fb = skyrimhair.on_face_bone(hair, "faceBone_C_HeadTop")
        for a, b in zip(hair.shapes, fb.shapes):
            for va, vb in zip(a.weights, b.weights):
                self.assertEqual([("faceBone_C_HeadTop" if n == "C_Head" else n, w) for n, w in va], vb)
        self.assertEqual([x.name for x in fb.bones], [x.name for x in hair.bones])   # the cloth chain unchanged


class HeadLocalTests(unittest.TestCase):
    def test_head_local_puts_the_hair_in_the_head_frame(self):
        w = sf_world()
        th = np.radians(30)
        w["C_Head"] = np.array([[np.cos(th), -np.sin(th), 0, 0.1], [np.sin(th), np.cos(th), 0, 0.2], [0, 0, 1, 1.6],
                                [0, 0, 0, 1]])                       # a turned head, to see the frame change
        hair = skyrimhair.rigid(skyrimhair.convert(hair_nif_bytes(), SMP_XML, w))
        hl, hw = skyrimhair.head_local(hair, w)
        self.assertEqual(list(hw), ["C_Head"])
        np.testing.assert_allclose(hw["C_Head"], np.eye(4))
        for a, b in zip(hair.shapes, hl.shapes):
            back = np.asarray(b.positions) @ w["C_Head"][:3, :3].T + w["C_Head"][:3, 3]
            np.testing.assert_allclose(back, a.positions, atol=1e-9)     # head world @ local = model space
            np.testing.assert_allclose(np.asarray(b.normals) @ w["C_Head"][:3, :3].T,
                                       np.asarray(a.normals) / np.linalg.norm(a.normals, axis=1, keepdims=True),
                                       atol=1e-9)
            self.assertTrue(all(vw == [("C_Head", 1.0)] for vw in b.weights))


class PackHelperTests(unittest.TestCase):
    def test_loose_roots_and_wig_names(self):
        import hair_pack
        with tempfile.TemporaryDirectory() as d:
            for rel in ("00 Core/Meshes/KS Hairdo's/HDT/XML/Test.xml", "01 Wigs/Meshes/Armor/KSWigsHDT/f/Test.nif",
                        "00 Core/Textures/KS Hairdo's/HDT/test.dds"):
                p = os.path.join(d, *rel.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as fh:
                    fh.write(rel.encode())
            src = hair_pack.LooseRoots([d])
            self.assertEqual(src.data("Data\\meshes\\KS Hairdo's\\HDT\\XML\\Test.xml"),
                             b"00 Core/Meshes/KS Hairdo's/HDT/XML/Test.xml")
            self.assertIsNotNone(src.texture("KS Hairdo's\\HDT\\test.dds"))
            wigs = [k for k in src.index if k.startswith("meshes/") and hair_pack.WIG_GLOB.search(k)]
            self.assertEqual(wigs, ["meshes/armor/kswigshdt/f/test.nif"])

    def test_head_apparel(self):
        import hair_pack
        kw = {0x100: "ArmorTypeApparelHead", 0x200: "ArmorTypeApparelOrNakedBody"}
        arma = [(b"ARMA", b"", [(b"EDID", b"AA_Hat\0")], 0x10)]
        armo = [(b"ARMO", b"", [(b"EDID", b"Body\0"), (b"KSIZ", struct.pack("<I", 1)),
                                (b"KWDA", struct.pack("<I", 0x200)), (b"MODL", struct.pack("<I", 0x10))], 0x20),
                (b"ARMO", b"", [(b"EDID", b"Hat\0"), (b"KSIZ", struct.pack("<I", 1)),
                                (b"KWDA", struct.pack("<I", 0x100)), (b"MODL", struct.pack("<I", 0x10))], 0x21)]
        ao, aa = hair_pack.head_apparel(armo, arma, kw)
        self.assertEqual((ao[3], aa[3]), (0x21, 0x10))


class PackEndToEndTests(unittest.TestCase):
    def test_main_on_synthetic_games(self):
        """The glue of hair_pack.main (wig search, config lookup, conversion, files, records), with the cloth
        template's tagfile side mocked (a synthetic TYPE section with every cloth class is out of scope here)."""
        import contextlib
        import io
        import json
        from unittest import mock
        import hair_pack
        from fo4sf import sfplugin, textures
        with tempfile.TemporaryDirectory() as d:
            ks = os.path.join(d, "KS")
            for rel, data in (("01 Wigs/Meshes/Armor/KSWigsHDT/f/Test.nif",
                               hair_nif_bytes(b"Data\\meshes\\KS Hairdo's\\HDT\\XML\\Test.xml")),
                              ("00 Core/Meshes/KS Hairdo's/HDT/XML/Test.xml", SMP_XML),
                              ("00 Core/Textures/hair/h.dds", F.rgba_dds()),
                              ("00 Core/Textures/hair/h_n.dds", F.rgba_dds())):
                p = os.path.join(ks, *rel.split("/"))
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as fh:
                    fh.write(data)
            sf = os.path.join(d, "Starfield")
            os.makedirs(os.path.join(sf, "Data"))
            os.makedirs(os.path.join(sf, "Tools"))
            kw = struct.pack("<4sIII", b"KYWD", 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)
            ar = struct.pack("<4sIII", b"ARMA", 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)
            ao = struct.pack("<4sIII", b"ARMO", 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)
            recs = [(b"KYWD", kw, [(b"EDID", b"ArmorTypeApparelHead\0")], 0x000A0001),
                    (b"ARMA", ar, [(b"EDID", b"AA_Hat\0"), (b"BO64", struct.pack("<Q", 1)),
                                   (b"MOD2", b"Clothes\\Hat_M.nif\0"), (b"MOD3", b"Clothes\\Hat_F.nif\0")],
                     0x000C0001),
                    (b"ARMO", ao, [(b"EDID", b"Clothes_Hat\0"), (b"BO64", struct.pack("<Q", 0x10)),
                                   (b"KSIZ", struct.pack("<I", 1)),
                                   (b"KWDA", struct.pack("<I", 0x000A0001)), (b"INDX", struct.pack("<H", 0)),
                                   (b"MODL", struct.pack("<I", 0x000C0001))], 0x000C0002)]
            with open(os.path.join(sf, "Data", "Starfield.esm"), "wb") as fh:
                fh.write(sfplugin.build(recs, {"hedr_version": 0.96, "form_version": 555}, masters=()))
            F.content_resources(os.path.join(sf, "Tools", "ContentResources.zip"))
            out = os.path.join(d, "mod")
            cloth = b"\x10\x00\x00\x40TAG0-synthetic"
            ident = (1, 0, 0, 0, 1, 0, 0, 0, 1)

            def game_nif(bones, binds):
                sh = sfnif.SkinnedShape(b"Hat", b"aa\\bb", 3, 3, "materials\\clothes\\hat.mat", bones,
                                        [((0.0, 0.0, 0.0, 1.0), ident, t, 1.0) for t in binds])
                return nif.serialize(sfnif.build_skinned_nif(b"Hat", [sh]))
            game = {"meshes/clothes/hat_f.nif": game_nif([b"C_Head"], [(0, 0, -1.6)]),       # inverse rest worlds
                    "meshes/clothes/hat_f_facebones.nif": game_nif([b"faceBone_C_Chin", b"faceBone_C_HeadTop"],
                                                                    [(0, -0.1, -1.55), (0, 0, -1.75)])}
            with mock.patch.object(textures, "texconv", lambda *a, **k: None), \
                    mock.patch.object(hair_pack, "read_game_file",
                                      lambda sfp, rel: game.get(rel.replace("\\", "/").lower())), \
                    mock.patch.object(hair_pack, "read_template", lambda spec: cloth), \
                    mock.patch.object(smpcloth, "check_template", lambda blob: template_root()), \
                    mock.patch.object(smpcloth, "write", lambda blob, root: cloth), \
                    mock.patch.object(smpcloth, "verify", lambda blob: {"ok": True}), \
                    contextlib.redirect_stdout(io.StringIO()):
                rc = hair_pack.main(["--ks", ks, "--starfield", sf, "--texconv", "texconv.exe", "--out", out,
                                     "--cloth-template", "x.nif"])
            self.assertEqual(rc, 0)
            rep = json.load(open(os.path.join(out, "hair_pack.json")))
            wig, = rep["wigs"]
            self.assertTrue(wig["ok"], wig)
            self.assertEqual(wig["chain_bones"], ["S2S_Hair_2", "S2S_Hair_3"])
            self.assertEqual(wig["model"], "s2s\\hair\\test.nif")
            self.assertEqual(rep["apparel_template"]["armo"], "Clothes_Hat")
            n = nif.parse(open(os.path.join(out, "meshes", "s2s", "hair", "test.nif"), "rb").read())
            self.assertIn("BSClothExtraData", [n.type_of(i) for i in range(len(n.blocks))])
            self.assertEqual(sfnif.parse_skin(n)["bones"], [b"C_Head", b"S2S_Hair_2", b"S2S_Hair_3"])
            got = {sfplugin.edid(r[2]): r for r in sfplugin.records(os.path.join(out, "S2SHair.esm"),
                                                                    [b"ARMO", b"ARMA"])}
            self.assertEqual(dict(got["S2S_KSWig_Test_AA"][2])[b"MOD3"], b"s2s\\hair\\test.nif\0")
            self.assertEqual(dict(got["S2S_KSWig_Test"][2])[b"FULL"], b"Test wig (Skyrim)\0")
            self.assertIn(0x000A0001, sfplugin.keywords(got["S2S_KSWig_Test"][2]))   # still head apparel
            rn = nif.parse(open(os.path.join(out, "meshes", "s2s", "hair", "test_rigid.nif"), "rb").read())
            self.assertNotIn("BSClothExtraData", [rn.type_of(i) for i in range(len(rn.blocks))])
            self.assertEqual(sfnif.parse_skin(rn)["bones"], [b"C_Head"])          # the control: no new bones
            self.assertEqual(dict(got["S2S_KSWig_Test_Rigid"][2])[b"FULL"], b"Test wig (Skyrim, no physics)\0")
            hn = nif.parse(open(os.path.join(out, "meshes", "s2s", "hair", "test_head.nif"), "rb").read())
            hs = sfnif.parse_skin(hn)
            self.assertEqual(hs["bones"], [b"C_Head"])                           # second control: the left
            sphere, rot, trans, scale = hs["binds"][0]                             # blade's identity bind
            self.assertEqual((rot, trans, scale), ((1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0), (0, 0, 0), 1.0))
            self.assertEqual(dict(got["S2S_KSWig_Test_Head"][2])[b"FULL"], b"Test wig (Skyrim, head bone)\0")
            ctl = got["S2S_KSWig_ControlHat"][2]                                   # the vanilla hat, renamed
            self.assertEqual(dict(ctl)[b"MODL"], struct.pack("<I", 0x000C0001))
            self.assertEqual(dict(ctl)[b"FULL"], b"S2S control hat (vanilla model)\0")
            ctrl = rep["controls"]
            self.assertTrue(ctrl["hat_found"])
            self.assertEqual(set(ctrl) & {"opaque", "hatmat", "hatcopy", "armacopy"},
                             {"opaque", "hatmat", "hatcopy", "armacopy"})
            ac = dict(got["S2S_KSWig_Control_armacopy"][2])                       # the copy, vanilla model path
            self.assertEqual(ac[b"FULL"], b"S2S control hat (copied addon, vanilla path)\0")
            self.assertEqual(dict(got["S2S_KSWig_Control_armacopy_AA"][2])[b"MOD3"], b"Clothes\\Hat_F.nif\0")
            self.assertEqual([r[0] for r in ctrl["arma_template"]], ["EDID", "BO64", "MOD2", "MOD3"])
            sol = got["S2S_KSWig_Control_opaque"][2]
            self.assertEqual(dict(sol)[b"FULL"], b"Test wig (Skyrim, solid material)\0")
            hair_dir = os.path.join(out, "meshes", "s2s", "hair")
            on = nif.parse(open(os.path.join(hair_dir, "test_opaque.nif"), "rb").read())
            self.assertEqual(sfnif.parse_skin(on)["bones"], [b"C_Head"])
            # the *_facebones.nif the game draws on actors with face bones: C_Head's weights on a face bone
            self.assertEqual(rep["face_bone"], "faceBone_C_HeadTop")
            self.assertTrue(wig["facebones"])
            fbn = sfnif.parse_skin(nif.parse(open(os.path.join(hair_dir, "test_facebones.nif"), "rb").read()))
            self.assertEqual(fbn["bones"], [b"S2S_Hair_2", b"S2S_Hair_3", b"faceBone_C_HeadTop"])
            k = fbn["bones"].index(b"faceBone_C_HeadTop")
            np.testing.assert_allclose(fbn["binds"][k][2], (0, 0, -1.75), atol=1e-6)   # inverse rest world kept
            for name in ("test_rigid_facebones", "test_head_facebones", "test_opaque_facebones",
                         "test_hatmat_facebones"):
                bones = sfnif.parse_skin(nif.parse(open(os.path.join(hair_dir, name + ".nif"), "rb").read()))["bones"]
                self.assertNotIn(b"C_Head", bones, name)
            self.assertEqual(open(os.path.join(hair_dir, "control_hat_copy_facebones.nif"), "rb").read(),
                             game["meshes/clothes/hat_f_facebones.nif"])
            self.assertNotIn("_fb", wig)
            self.assertEqual(rep["facebones"]["used"], "hat")
            self.assertNotIn("headshift", ctrl)                                   # hypothesis B ruled out
            self.assertIn("body_colliders", wig["cloth"])
            self.assertIn("S2S_face", wig["cloth"]["body_colliders"])
            self.assertNotIn("collision_capsule_C_Chest", wig["cloth"]["colliders"])   # template's left out
            self.assertEqual(struct.unpack("<Q", dict(got["S2S_KSWig_Test_AA"][2])[b"BO64"])[0], 1)   # Hide Hair
            self.assertEqual(struct.unpack("<Q", dict(got["S2S_KSWig_Test"][2])[b"BO64"])[0], 0x11)   # ARMO too
            self.assertNotIn("_control", wig)


if __name__ == "__main__":
    unittest.main()
