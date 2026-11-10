"""item_physics_probe: vanilla loose items' bodies grouped by motion word, against the static box template and the
keyframed door donor (2026-11-10, owner: items you can pick up, drop, with physics)."""
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "interior"))

from fo4sf import nif as nifmod, sfcollision, sfnif, sfplugin  # noqa: E402
import item_physics_probe as P  # noqa: E402

Z = lambda t: t.encode() + b"\0"                                         # noqa: E731


def template(motion):
    b = bytearray(sfcollision.BLOB_SIZE)
    b[0:8] = b"\x00\x00\x18\x18TAG0"
    b[100:112] = b"hknpBoxShape"
    for off, v in ((528, (1.0, 0.0, 0.0)), (544, (0.0, 1.0, 0.0)), (560, (0.0, 0.0, 1.0))):
        struct.pack_into("<3f", b, off, *v)
    struct.pack_into("<I", b, 240, motion)
    struct.pack_into("<4f", b, 1064, 2.5, 0.1, 0.1, 0.1)
    return bytes(b)


def nif_with(blob):
    sh = sfnif.StaticShape(b"Shape", b"aaaa\\bbbb", 3, 3, "m.mat", (0, 0, 0, 1), (0, 0, 0, 1, 1, 1))
    return nifmod.serialize(sfnif.build_static_nif(b"Root", [sh], collision_blob=blob))


class FakeArchives:
    def __init__(self, files):
        self.files = {k.replace("/", "\\").lower(): v for k, v in files.items()}

    def read(self, path):
        k = path.replace("/", "\\").lower().lstrip("\\")
        if k not in self.files:
            raise FileNotFoundError(path)
        return self.files[k]


class ProbeTests(unittest.TestCase):
    def test_groups_by_motion_word(self):
        static = sfcollision.box_blob(template(1), (0, 0, 0.5), (0.5, 0.5, 0.5))
        door = sfcollision.box_blob(template(2), (0, 0, 1), (0.5, 0.05, 1))
        bottle = sfcollision.box_blob(template(3), (0, 0, 0.15), (0.04, 0.04, 0.15))
        files = {P.STATIC_TEMPLATE: nif_with(static), P.DOOR_DONOR: nif_with(door),
                 "meshes\\clutter\\bottle.nif": nif_with(bottle), "meshes\\clutter\\plate.nif": nif_with(static)}
        h = lambda t: struct.pack("<4sIII", t, 0, 0, 0) + bytes(4) + struct.pack("<HH", 555, 0)   # noqa: E731
        recs = [(b"ALCH", h(b"ALCH"), [(b"EDID", Z("Wine")), (b"MODL", Z("Clutter\\Bottle.nif"))], 0x100),
                (b"MISC", h(b"MISC"), [(b"EDID", Z("Plate")), (b"MODL", Z("Clutter\\Plate.nif"))], 0x101),
                (b"MISC", h(b"MISC"), [(b"EDID", Z("Ghost")), (b"MODL", Z("Clutter\\Missing.nif"))], 0x102)]
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "Starfield.esm"), "wb") as fh:
                fh.write(sfplugin.build(recs, {"hedr_version": 0.96, "form_version": 555}, masters=()))
            rep = P.probe(d, arcs=FakeArchives(files))
            md = P.markdown(rep)
        self.assertEqual(rep["counts"]["items_by_type"], {"ALCH": 1, "MISC": 2})
        g = {x["motion_240"]: x for x in rep["box_layout_groups"]}
        self.assertEqual(g[struct.pack("<I", 3).hex()]["like"], "other (dynamic?)")
        self.assertEqual(g[struct.pack("<I", 3).hex()]["examples"][0]["edid"], "Wine")
        self.assertEqual(g[struct.pack("<I", 3).hex()]["examples"][0]["box"]["half"], [0.04, 0.04, 0.15])
        self.assertEqual(g[struct.pack("<I", 1).hex()]["like"], "static template")
        self.assertEqual(g[struct.pack("<I", 3).hex()]["examples"][0]["mass"], [2.5, 0.1, 0.1, 0.1])
        ghost = next(r for r in rep["items"] if r["edid"] == "Ghost")
        self.assertIn("error", ghost["bodies"])
        self.assertIn("Wine", md)


if __name__ == "__main__":
    unittest.main()
