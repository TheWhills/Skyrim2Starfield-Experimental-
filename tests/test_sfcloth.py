"""hktagfile value decoding, fo4sf.sfcloth and scripts/armor/sf_cloth_survey.py on a synthetic Havok tagfile (built
here, shaped like Starfield's BSClothExtraData payload) and synthetic NIFs. No game or mod files."""
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
from fo4sf import hktagfile as H  # noqa: E402
from fo4sf import nif as nifmod  # noqa: E402
from fo4sf import sfcloth as C  # noqa: E402
import sf_cloth_survey as V  # noqa: E402


def _sec(tag: str, payload: bytes) -> bytes:
    return struct.pack(">I", (len(payload) + 8) | 0x40000000) + tag.encode() + payload


class TagBuilder:
    """Minimal TAG0 writer for tests: types declared by name, objects laid out in DATA, items indexed."""

    def __init__(self):
        self.types, self.tstr, self.fstr = [], [], []
        self.data, self.items = bytearray(), [(0, 0, 0)]

    def _s(self, table, s):
        if s not in table:
            table.append(s)
        return table.index(s)

    def type(self, name, fmt=0, size=0, align=0, parent=0, sub=0, params=(), fields=()):
        """fields: [(name, type index, offset)]; returns the 1-based type index."""
        self.types.append(dict(name=name, fmt=fmt, size=size, align=align or size, parent=parent, sub=sub,
                               params=list(params), fields=list(fields)))
        return len(self.types)

    def item(self, ti, payload: bytes, count=1, single=False):
        while len(self.data) % 16:
            self.data.append(0)
        off = len(self.data)
        self.data += payload
        self.items.append((ti | ((0x10 if single else 0x20) << 24), off, count))
        return len(self.items) - 1

    def build(self) -> bytes:
        v = lambda x: bytes([x]) if x < 0x80 else bytes([0x80 | (x >> 8), x & 0xFF])  # noqa: E731
        tna = v(len(self.types) + 1)
        for t in self.types:
            tna += v(self._s(self.tstr, t["name"])) + v(len(t["params"]))
            for pn, pv in t["params"]:
                tna += v(self._s(self.tstr, pn)) + v(pv)
        body = b""
        for i, t in enumerate(self.types, 1):
            opt = 0x1 | (0x2 if t["sub"] else 0) | (0x8 if t["size"] else 0) | (0x20 if t["fields"] else 0)
            body += v(i) + v(t["parent"]) + v(opt)
            body += struct.pack(">I", t["fmt"])[0:0] + self._varint(t["fmt"])
            if t["sub"]:
                body += v(t["sub"])
            if t["size"]:
                body += v(t["size"]) + v(t["align"])
            if t["fields"]:
                body += v(len(t["fields"]))
                for fn, ft, fo in t["fields"]:
                    body += v(self._s(self.fstr, fn)) + v(0) + v(fo) + v(ft)
        body += v(0)
        typ = (_sec("TST1", b"".join(s.encode() + b"\0" for s in self.tstr)) + _sec("TNA1", tna)
               + _sec("FST1", b"".join(s.encode() + b"\0" for s in self.fstr)) + _sec("TBDY", body))
        idx = _sec("ITEM", b"".join(struct.pack("<III", *it) for it in self.items)) + _sec("PTCH", b"")
        return _sec("TAG0", _sec("SDKV", b"20190200") + _sec("DATA", bytes(self.data)) + _sec("TYPE", typ)
                    + _sec("INDX", idx))

    @staticmethod
    def _varint(x):
        if x < 0x80:
            return bytes([x])
        if x < 0x4000:
            return bytes([0x80 | (x >> 8), x & 0xFF])
        if x < 0x200000:
            return bytes([0xC0 | (x >> 16), (x >> 8) & 0xFF, x & 0xFF])
        return bytes([0xE0 | (x >> 24), (x >> 16) & 0xFF, (x >> 8) & 0xFF, x & 0xFF])


def cloth_tagfile() -> bytes:
    """Root container -> hclClothData (one sim cloth, one bone-deform operator) + hkaSkeleton
    [Root, C_Head, Tail_1, Tail_2]: Tail_1 under C_Head, Tail_2 under Tail_1, both driven."""
    b = TagBuilder()
    u32 = b.type("unsigned int", 0x8004, 4)
    hku32 = b.type("hkUint32", 0, 0, parent=u32)                        # typedef: format 0 inherits
    i16 = b.type("hkInt16", 0x4204, 2)
    u16 = b.type("hkUint16", 0x4004, 2)
    f32 = b.type("float", 0x174605, 4)
    sptr = b.type("hkStringPtr", 0x83, 8)
    boolean = b.type("hkBool", 0x2002, 1)
    vec = b.type("T[N]<float, 4>", 0x428, 16, sub=f32)                  # fixed array of 4

    def arr(sub):
        return b.type("hkArray", 0x8, 16, sub=sub, params=[("tT", sub)])

    def ptr(sub):
        return b.type("T*", 0x6, 8, sub=sub, params=[("tT", sub)])

    pd = b.type("hclSimClothData::ParticleData", 0x7, 8, fields=[("mass", f32, 0), ("radius", f32, 4)])
    shape = b.type("hclCapsuleShape", 0x7, 4, fields=[("radius", f32, 0)])
    coll = b.type("hclCollidable", 0x7, 16, fields=[("name", sptr, 0), ("shape", ptr(shape), 8)])
    cmap = b.type("CollidableTransformMap", 0x7, 16, fields=[("transformIndices", arr(u32), 0)])
    link = b.type("hclStretchLinkConstraintSet::Link", 0x7, 8, fields=[("stiffness", f32, 0)])
    cset = b.type("hclStretchLinkConstraintSet", 0x7, 24, fields=[("name", sptr, 0), ("links", arr(link), 8)])
    simi = b.type("SimulationInfo", 0x7, 20, fields=[("gravity", vec, 0), ("globalDampingPerSecond", f32, 16)])
    sim = b.type("hclSimClothData", 0x7, 136, fields=[
        ("name", sptr, 0), ("simulationInfo", simi, 16), ("particleDatas", arr(pd), 40),
        ("fixedParticles", arr(u16), 56), ("staticConstraintSets", arr(ptr(cset)), 72),
        ("perInstanceCollidables", arr(ptr(coll)), 88), ("collidableTransformMap", cmap, 104),
        ("triangleIndices", arr(u16), 120)])
    tbp = b.type("hclSimpleMeshBoneDeformOperator::TriangleBonePair", 0x7, 8,
                 fields=[("boneOffset", hku32, 0), ("triangleOffset", hku32, 4)])
    op = b.type("hclSimpleMeshBoneDeformOperator", 0x7, 24, fields=[("name", sptr, 0),
                                                                    ("triangleBonePairs", arr(tbp), 8)])
    cd = b.type("hclClothData", 0x7, 48, fields=[("name", sptr, 0), ("simClothDatas", arr(ptr(sim)), 8),
                                                 ("operators", arr(ptr(op)), 24), ("enabled", boolean, 40)])
    bone = b.type("hkaBone", 0x7, 8, fields=[("name", sptr, 0)])
    skel = b.type("hkaSkeleton", 0x7, 32, fields=[("bones", arr(bone), 0), ("parentIndices", arr(i16), 16)])
    nv = b.type("hkRootLevelContainer::NamedVariant", 0x7, 24,
                fields=[("name", sptr, 0), ("className", sptr, 8), ("variant", ptr(0), 16)])
    rlc = b.type("hkRootLevelContainer", 0x7, 16, fields=[("namedVariants", arr(nv), 0)])

    def s(text):
        return b.item(b.type("char", 0x2004, 1), text.encode() + b"\0", len(text) + 1)

    def a(item, n):
        return struct.pack("<QII", item, n, n)

    q = lambda x: struct.pack("<Q", x)  # noqa: E731
    root = b.item(rlc, bytes(16), single=True)                         # item 1, patched below
    bones = [s(n) for n in ("Root", "C_Head", "Tail_1", "Tail_2")]
    bone_items = b.item(bone, b"".join(q(x) for x in bones), 4)
    par = b.item(i16, struct.pack("<4h", -1, 0, 1, 2), 4)
    skel_item = b.item(skel, a(bone_items, 4) + a(par, 4), single=True)
    pds = b.item(pd, struct.pack("<6f", 0, 0.002, 0.01, 0.002, 0.01, 0.002), 3)
    fixed = b.item(u16, struct.pack("<H", 0), 1)
    links = b.item(link, struct.pack("<f4xf4x", 1.0, 0.5), 2)
    cs = b.item(cset, q(s("StretchLink Constraint")) + a(links, 2), single=True)
    cs_arr = b.item(ptr(cset), q(cs), 1)
    cap = b.item(shape, struct.pack("<f", 0.07), single=True)
    col = b.item(coll, q(s("collision_capsule_head")) + q(cap), single=True)
    col_arr = b.item(ptr(coll), q(col), 1)
    tix = b.item(u32, struct.pack("<I", 1), 1)
    tris = b.item(u16, struct.pack("<6H", 0, 1, 2, 1, 2, 0), 6)
    sim_payload = (q(s("Sim")) + bytes(8) + struct.pack("<5f", 0, 0, -9.81, 0, 0.9) + bytes(4) + a(pds, 3) + a(fixed, 1)
                   + a(cs_arr, 1) + a(col_arr, 1) + a(tix, 1) + a(tris, 6))
    sim_item = b.item(sim, sim_payload, single=True)
    sim_arr = b.item(ptr(sim), q(sim_item), 1)
    pairs = b.item(tbp, struct.pack("<4I", 2 * 64, 0, 3 * 64, 6), 2)
    op_item = b.item(op, q(s("Deform")) + a(pairs, 2), single=True)
    op_arr = b.item(ptr(op), q(op_item), 1)
    cd_item = b.item(cd, q(s("Character Bone Deforming Clothing")) + a(sim_arr, 1) + a(op_arr, 1) + b"\1"
                     + bytes(7), single=True)
    nvs = b.item(nv, q(0) + q(s("hclClothData")) + q(cd_item) + q(0) + q(s("hkaSkeleton")) + q(skel_item), 2)
    off = b.items[root][1]
    b.data[off:off + 16] = a(nvs, 2)
    return b.build()


def cloth_nif(payload: bytes) -> bytes:
    n = nifmod.NifFile(user_version=12, bs_version=172, sf_data=b"")
    n.string_index(b"root")
    n.add_block("NiNode", struct.pack("<iI", 0, 1) + struct.pack("<i", 1) + bytes(64) + struct.pack("<II", 0, 0))
    n.add_block("BSClothExtraData", struct.pack("<I", len(payload)) + payload)
    n.footer = struct.pack("<Ii", 1, 0)
    return nifmod.serialize(n)


class DecodeTests(unittest.TestCase):
    def test_values(self):
        tf = H.Tagfile(cloth_tagfile())
        r = tf.root()
        self.assertEqual(sorted(r), ["hclClothData", "hkaSkeleton"])
        cd = r["hclClothData"]
        self.assertEqual(cd["$class"], "hclClothData")
        self.assertEqual(cd["name"], "Character Bone Deforming Clothing")
        self.assertIs(cd["enabled"], True)
        sim = cd["simClothDatas"][0]
        self.assertEqual(sim["simulationInfo"]["gravity"][2], struct.unpack("<f", struct.pack("<f", -9.81))[0])
        self.assertEqual(len(sim["particleDatas"]), 3)
        self.assertEqual(cd["operators"][0]["triangleBonePairs"][1], {"boneOffset": 192, "triangleOffset": 6})
        self.assertEqual(r["hkaSkeleton"]["parentIndices"], [-1, 0, 1, 2])          # signed 16-bit
        self.assertEqual(sim["perInstanceCollidables"][0]["shape"]["$class"], "hclCapsuleShape")
        self.assertIsNone(tf.item_value(0))


class ClothTests(unittest.TestCase):
    def test_summary_and_chains(self):
        s = C.summary(cloth_tagfile())
        self.assertEqual((s["mode"], s["driven_bones"], s["skeleton_bones"]), ("bones", ["Tail_1", "Tail_2"], 4))
        self.assertEqual(s["bone_parents"], [{"bone": "Tail_1", "parent": "C_Head"},
                                             {"bone": "Tail_2", "parent": "Tail_1"}])
        sim = s["sims"][0]
        self.assertEqual((sim["particles"], sim["fixed"], sim["triangles"]), (3, 1, 2))
        self.assertEqual(sim["mass"], [0.0, 0.01])
        self.assertEqual(sim["constraint_sets"][0]["class"], "hclStretchLinkConstraintSet")
        self.assertEqual(sim["constraint_sets"][0]["stiffness"], [0.5, 1.0])
        self.assertEqual(sim["collidables"], [{"name": "collision_capsule_head", "shape": "hclCapsuleShape",
                                               "bone": "C_Head", "radius": 0.07}])
        self.assertEqual(C.chains(s), [{"host": "C_Head", "bones": 2, "depth": 2}])
        st = C.stats([s])
        self.assertEqual((st["mode:bones"], st["collider:hclCapsuleShape"]), (1, 1))

    def test_payload(self):
        blob = cloth_tagfile()
        self.assertEqual(C.payload(struct.pack("<I", len(blob)) + blob), blob)
        with self.assertRaises(C.ClothError):
            C.payload(b"\0" * 16)


class SurveyTests(unittest.TestCase):
    def test_survey_finds_loose_nif_and_hkx(self):
        blob = cloth_tagfile()
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "meshes", "hair"))
            with open(os.path.join(d, "meshes", "hair", "tail.nif"), "wb") as fh:
                fh.write(cloth_nif(blob))
            with open(os.path.join(d, "meshes", "hair", "tail.hkx"), "wb") as fh:
                fh.write(blob)
            with open(os.path.join(d, "meshes", "hair", "plain.nif"), "wb") as fh:
                fh.write(b"Gamebryo File Format, nothing here")
            with open(os.path.join(d, "meshes", "hair", "broken.nif"), "wb") as fh:
                fh.write(cloth_nif(b"TAG0junkjunkjunk")[:-30] + b"BSClothExtraData")
            out = os.path.join(d, "out")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(V.main(["--root", d, "--out", out]), 0)
            with open(os.path.join(out, "sf_cloth_survey.json"), encoding="utf-8") as fh:
                r = json.load(fh)
        self.assertEqual(r["cloth"], 2)
        self.assertEqual(sorted(os.path.basename(f["file"]) for f in r["files"]), ["tail.hkx", "tail.nif"])
        self.assertEqual(r["files"][0]["chains"], [{"host": "C_Head", "bones": 2, "depth": 2}])
        self.assertEqual(len(r["errors"]), 1)                                       # broken.nif reported


if __name__ == "__main__":
    unittest.main()
