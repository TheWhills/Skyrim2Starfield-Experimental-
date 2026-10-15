"""skyrimhkx.describe on a synthetic hk_2010.2.0-r1 64-bit packfile (no game data). The builder writes the layout the
reader assumes; real Skyrim files are the check on the offsets (see the module docstring)."""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from fo4sf import hkpackfile, skyrimhkx  # noqa: E402


class Hkx2010:
    """Builds a 3-section packfile (__classnames__, __types__, __data__) with local and virtual fixups."""

    def __init__(self):
        self.data = bytearray()
        self.local = []                      # (src, dst)
        self.virtual = []                    # (obj, class name)

    def alloc(self, n, align=16):
        while len(self.data) % align:
            self.data.append(0)
        at = len(self.data)
        self.data += bytes(n)
        return at

    def obj(self, cls, size):
        at = self.alloc(size)
        self.virtual.append((at, cls))
        return at

    def put(self, at, fmt, *v):
        struct.pack_into(fmt, self.data, at, *v)

    def ptr(self, at, target):
        self.local.append((at, target))

    def string(self, at, text):
        s = self.alloc(len(text) + 1, align=2)
        self.data[s:s + len(text)] = text.encode()
        self.ptr(at, s)

    def array(self, at, target, count):
        self.put(at + 8, "<iI", count, count | 0x80000000)
        if count:
            self.ptr(at, target)

    def bytes(self):
        names = sorted({c for _, c in self.virtual})
        cn, name_at = bytearray(), {}
        for c in names:
            cn += struct.pack("<I", 0x12345678) + b"\x09"
            name_at[c] = len(cn)
            cn += c.encode() + b"\0"
        while len(cn) % 16:
            cn.append(0xFF)
        d = bytes(self.data)
        while len(d) % 16:
            d += b"\0"
        loc = b"".join(struct.pack("<ii", a, b) for a, b in self.local)
        vir = b"".join(struct.pack("<iii", a, 0, name_at[c]) for a, c in self.virtual)
        body_cn = bytes(cn)
        head = 64 + 3 * 48
        cn_start = head
        types_start = cn_start + len(body_cn)
        data_start = types_start
        loc_off, glo_off = len(d), len(d) + len(loc)
        vir_off = glo_off
        end = vir_off + len(vir)

        def sh(tag, start, offs):
            return tag.encode().ljust(19, b"\0") + b"\xff" + struct.pack("<7i", start, *offs)
        hdr = struct.pack("<8sii4Biiiii", hkpackfile.MAGIC, 0, 8, 8, 1, 0, 1, 3, 2, 0, 0, 75)
        hdr += b"hk_2010.2.0-r1".ljust(16, b"\0") + struct.pack("<ii", 0, -1)
        n = len(body_cn)
        sections = (sh("__classnames__", cn_start, (n, n, n, n, n, n))
                    + sh("__types__", types_start, (0, 0, 0, 0, 0, 0))
                    + sh("__data__", data_start, (loc_off, glo_off, vir_off, end, end, end)))
        return hdr + sections + body_cn + d + loc + vir


def build_animation_file():
    h = Hkx2010()
    root = h.obj("hkRootLevelContainer", 16)
    cont = h.obj("hkaAnimationContainer", 96)
    skel = h.obj("hkaSkeleton", 120)
    anim = h.obj("hkaSplineCompressedAnimation", 176)
    bind = h.obj("hkaAnimationBinding", 72)
    # root: one named variant
    nv = h.alloc(24)
    h.array(root, nv, 1)
    h.string(nv, "Merged Animation Container")
    h.string(nv + 8, "hkaAnimationContainer")
    h.ptr(nv + 16, cont)
    # container: 1 skeleton, 1 animation, 1 binding
    for k, target in enumerate((skel, anim, bind)):
        lst = h.alloc(8)
        h.ptr(lst, target)
        h.array(cont + 16 + 16 * k, lst, 1)
    # skeleton: 3 bones
    h.string(skel + 16, "NPC Root [Root]")
    par = h.alloc(6)
    h.put(par, "<3h", -1, 0, 1)
    h.array(skel + 24, par, 3)
    bones = h.alloc(48)
    for k, name in enumerate(("NPC Root [Root]", "NPC COM [COM ]", "NPC Pelvis [Pelv]")):
        h.string(bones + 16 * k, name)
    h.array(skel + 40, bones, 3)
    pose = h.alloc(3 * 48)
    for k in range(3):
        h.put(pose + 48 * k, "<12f", 0, 0, 68.9 * k, 0, 0, 0, 0, 1, 1, 1, 1, 0)
    h.array(skel + 56, pose, 3)
    # animation: spline, 2.0 s, 3 tracks, 61 frames in 2 blocks, two annotations
    h.put(anim + 16, "<ifii", 5, 2.0, 3, 0)
    h.put(anim + 56, "<iiiifff", 61, 2, 32, 120, 1.0333, 0.9677, 1.0 / 30.0)
    data = h.alloc(64)
    h.array(anim + 152, data, 64)
    tracks = h.alloc(3 * 24)
    ann = h.alloc(2 * 16)
    h.put(ann, "<f", 0.25)
    h.string(ann + 8, "FootLeft")
    h.put(ann + 16, "<f", 0.75)
    h.string(ann + 24, "FootRight")
    h.string(tracks, "NPC Root [Root]")
    h.array(tracks + 8, ann, 2)
    h.array(anim + 40, tracks, 3)
    # binding
    h.string(bind + 16, "NPC Root [Root]")
    h.ptr(bind + 24, anim)
    idx = h.alloc(6)
    h.put(idx, "<3h", 0, 1, 2)
    h.array(bind + 32, idx, 3)
    return h.bytes()


class HkxTests(unittest.TestCase):
    def test_describe_skeleton_animation_binding_annotations(self):
        d = skyrimhkx.describe(build_animation_file())
        self.assertEqual(d["havok"], "hk_2010.2.0-r1")
        self.assertEqual(d["checks"], [])
        sk, = d["skeletons"]
        self.assertEqual((sk["name"], sk["bones"], sk["parents"]),
                         ("NPC Root [Root]", ["NPC Root [Root]", "NPC COM [COM ]", "NPC Pelvis [Pelv]"], [-1, 0, 1]))
        self.assertAlmostEqual(sk["reference_pose"][2]["t"][2], 137.8, places=3)
        a, = d["animations"]
        self.assertEqual((a["class"], a["type"], a["transform_tracks"], a["frames"], a["blocks"], a["data_bytes"]),
                         ("hkaSplineCompressedAnimation", "spline_compressed", 3, 61, 2, 64))
        self.assertAlmostEqual(a["duration"], 2.0)
        self.assertEqual([(e["time"], e["text"]) for e in a["annotations"]], [(0.25, "FootLeft"), (0.75, "FootRight")])
        b, = d["bindings"]
        self.assertEqual((b["skeleton"], b["animation"], b["track_to_bone"]), ("NPC Root [Root]", 0, [0, 1, 2]))

    def test_rejects_other_versions_and_non_packfiles(self):
        raw = bytearray(build_animation_file())
        struct.pack_into("<i", raw, 12, 11)
        with self.assertRaises(skyrimhkx.HkxError):
            skyrimhkx.describe(bytes(raw))
        with self.assertRaises(skyrimhkx.HkxError):
            skyrimhkx.describe(b"<?xml version='1.0'?><hkpackfile/>")

    def test_wrong_offsets_show_up_in_checks(self):
        raw = bytearray(build_animation_file())
        d = skyrimhkx.describe(bytes(raw))
        self.assertEqual(d["checks"], [])
        pf = hkpackfile.Packfile(bytes(raw))
        anim = pf.objects("hkaSplineCompressedAnimation")[0][0]
        struct.pack_into("<f", raw, pf.data_section.start + anim + 20, -7.0)      # nonsense duration
        self.assertTrue(any("duration -7.0" in c for c in skyrimhkx.describe(bytes(raw))["checks"]))


if __name__ == "__main__":
    unittest.main()


class SurveyTests(unittest.TestCase):
    def test_survey_counts_animations_failures_and_events(self):
        import contextlib
        import io
        import json
        import tempfile
        sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
        import hkx_survey
        from fo4sf import bsa
        with tempfile.TemporaryDirectory() as tmp:
            data = os.path.join(tmp, "Data")
            os.makedirs(data)
            with open(os.path.join(data, "Skyrim - Animations.bsa"), "wb") as f:
                f.write(bsa.build({"meshes\\actors\\character\\animations\\mt_idle.hkx": build_animation_file(),
                                   "meshes\\actors\\character\\animations\\broken.hkx": b"<?xml?>",
                                   "meshes\\actors\\character\\character assets\\skeleton.nif": b"not hkx"}))
            out = os.path.join(tmp, "out")
            with contextlib.redirect_stdout(io.StringIO()):
                hkx_survey.main(["--skyrim-data", data, "--out", out])
            with open(os.path.join(out, "report.json"), encoding="utf-8") as f:
                r = json.load(f)
        self.assertEqual((r["files"], r["failed"], r["with_checks"]), (2, 1, 0))
        self.assertEqual(r["kinds"], {"animation": 1})
        self.assertEqual(r["animation_types"], {"hkaSplineCompressedAnimation / spline_compressed": 1})
        self.assertEqual(r["annotation_events"], {"FootLeft": 1, "FootRight": 1})
