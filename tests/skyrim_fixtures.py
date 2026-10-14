"""Synthetic Skyrim (Special Edition) data for tests: BS 100 NIF blocks, BSA archives, an ESM with Tamriel terrain and
placed references, and stand-ins for the Starfield inputs (material templates, box-collision template NIF, texconv).
Every byte is built here; no game data."""
import json
import os
import struct
import zipfile

import numpy as np

from fo4sf import bsa, nif, sfnif, textures

IDENT_R = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


# ---------------------------------------------------------------------------------------------------------- NIF
class SseNif:
    """Builds a Skyrim SE NIF (20.2.0.7, user 12, BS 100) block by block."""

    def __init__(self):
        self.f = nif.NifFile(endian=1, user_version=12, bs_version=100, author=b"test", process_script=b"",
                             export_script=b"")

    def s(self, text: bytes) -> int:
        return self.f.string_index(text)

    def add(self, t, data):
        return self.f.add_block(t, data)

    def reserve(self, t):
        return self.add(t, b"")

    def set(self, i, data):
        self.f.blocks[i] = data

    @staticmethod
    def av(name, t=(0, 0, 0), r=IDENT_R, s=1.0, coll=-1, flags=0xE):
        return struct.pack("<iIiI", name, 0, -1, flags) + struct.pack("<3f9ff", *t, *r, s) + struct.pack("<i", coll)

    def node(self, i, name, children, t=(0, 0, 0), r=IDENT_R, s=1.0, coll=-1):
        self.set(i, self.av(self.s(name), t, r, s, coll) + struct.pack("<I", len(children))
                 + struct.pack(f"<{len(children)}i", *children) + struct.pack("<I", 0))

    def trishape(self, name, verts, uvs, tris, shader=-1, alpha=-1, t=(0, 0, 0), lod=False):
        vsize = 28
        desc = (vsize // 4) | (4 << 8) | (5 << 16) | (6 << 20) | ((0x1 | 0x2 | 0x8 | 0x10) << 44)
        vb = b""
        for (x, y, z), (u, v) in zip(verts, uvs):
            vb += struct.pack("<3ff", x, y, z, 0.0) + struct.pack("<2e", u, v) + bytes([127, 127, 255, 0]) \
                + bytes([255, 127, 127, 0])
        tb = b"".join(struct.pack("<3H", *tr) for tr in tris)
        body = self.av(self.s(name), t) + struct.pack("<4f", 0, 0, 0, 1) + struct.pack("<iii", -1, shader, alpha) \
            + struct.pack("<Q", desc) + struct.pack("<HHI", len(tris), len(verts), len(vb) + len(tb)) + vb + tb \
            + struct.pack("<I", 0)
        if lod:
            body += struct.pack("<3I", len(tris), 0, 0)
        return self.add("BSLODTriShape" if lod else "BSTriShape", body)

    def nitrishape(self, name, verts, uvs, tris, shader=-1, alpha=-1, crc=False):
        nv = len(verts)
        d = struct.pack("<iHBBB", 0, nv, 0, 0, 1) + b"".join(struct.pack("<3f", *v) for v in verts)
        d += struct.pack("<H", 0x1) + (struct.pack("<I", 0) if crc else b"")
        d += b"\x01" + b"".join(struct.pack("<3f", 0, 0, 1) for _ in verts)
        d += struct.pack("<4f", 0, 0, 0, 1) + b"\x00" + b"".join(struct.pack("<2f", *uv) for uv in uvs)
        d += struct.pack("<Hi", 0, -1) + struct.pack("<H", len(tris)) + struct.pack("<I", 3 * len(tris)) + b"\x01"
        d += b"".join(struct.pack("<3H", *t) for t in tris) + struct.pack("<H", 0)
        data = self.add("NiTriShapeData", d)
        return self.add("NiTriShape", self.av(self.s(name)) + struct.pack("<iiI", data, -1, 0) + struct.pack("<iB", -1, 0)
                        + struct.pack("<ii", shader, alpha))

    def lighting(self, diffuse, normal):
        paths = [diffuse, normal] + [""] * 7
        ts = self.add("BSShaderTextureSet", struct.pack("<I", len(paths))
                      + b"".join(struct.pack("<I", len(p)) + p.encode() for p in paths))
        return self.add("BSLightingShaderProperty", struct.pack("<IiIiII", 1, -1, 0, -1, 0x80000000, 0x8001)
                        + struct.pack("<4f", 0, 0, 1, 1) + struct.pack("<i", ts) + bytes(60))

    def effect(self):
        return self.add("BSEffectShaderProperty", struct.pack("<iIi", -1, 0, -1) + bytes(40))

    def alpha(self, flags, threshold):
        return self.add("NiAlphaProperty", struct.pack("<iIiHB", -1, 0, -1, flags, threshold))

    # -- collision
    def collision(self, target, shape, rigid_t=None):
        body = self.reserve("bhkRigidBodyT" if rigid_t else "bhkRigidBody")
        co = self.add("bhkCollisionObject", struct.pack("<iHi", target, 0x81, body))
        b = bytearray(250)
        struct.pack_into("<i", b, 0, shape)
        struct.pack_into("<4f", b, 72, 0, 0, 0, 1)
        if rigid_t:
            t, q = rigid_t
            struct.pack_into("<4f", b, 56, *t, 0)
            struct.pack_into("<4f", b, 72, *q)
        self.set(body, bytes(b))
        return co

    def mopp(self, shape):
        return self.add("bhkMoppBvTreeShape", struct.pack("<i", shape) + bytes(40))

    def cms(self, chunks, big_verts=(), big_tris=(), transforms=((0, 0, 0), (0, 0, 0, 1)), error=0.001):
        """chunks: [(translation, quantised xyz list, strips [[idx...]], list indices [...])]"""
        d = struct.pack("<IIIIf", 17, 18, 0x3FFFF, 0x1FFFF, error) + struct.pack("<8f", -9, -9, -9, 0, 9, 9, 9, 0)
        d += bytes([0, 1])
        d += struct.pack("<I", 0) + struct.pack("<I", 0) + struct.pack("<I", 0)        # materials 32/16/8
        d += struct.pack("<I", 1) + struct.pack("<II", 1, 0)                           # one chunk material
        d += struct.pack("<I", 0)                                                      # named materials
        tl = [transforms] if transforms and not isinstance(transforms[0][0], (tuple, list)) else list(transforms)
        d += struct.pack("<I", len(tl)) + b"".join(struct.pack("<4f4f", *t, 0, *q) for t, q in tl)
        d += struct.pack("<I", len(big_verts)) + b"".join(struct.pack("<4f", *v, 0) for v in big_verts)
        d += struct.pack("<I", len(big_tris)) + b"".join(struct.pack("<3HIH", *t, 0, 0) for t in big_tris)
        d += struct.pack("<I", len(chunks))
        for tr, qv, strips, lst in chunks:
            flat = [c for v in qv for c in v]
            idx = [i for s in strips for i in s] + list(lst)
            d += struct.pack("<4f", *tr, 0) + struct.pack("<IHH", 0, 0xFFFF, 0)
            d += struct.pack("<I", len(flat)) + struct.pack(f"<{len(flat)}H", *flat)
            d += struct.pack("<I", len(idx)) + struct.pack(f"<{len(idx)}H", *idx)
            d += struct.pack("<I", len(strips)) + struct.pack(f"<{len(strips)}H", *[len(s) for s in strips])
            d += struct.pack("<I", 0)
        d += struct.pack("<I", 0)
        data = self.add("bhkCompressedMeshShapeData", d)
        head = bytearray(56)
        struct.pack_into("<i", head, 0, -1)
        struct.pack_into("<i", head, 52, data)
        return self.add("bhkCompressedMeshShape", bytes(head))

    def box(self, half):
        return self.add("bhkBoxShape", struct.pack("<If", 0, 0.05) + bytes(8) + struct.pack("<3ff", *half, 0))

    def capsule(self, a, b, r):
        return self.add("bhkCapsuleShape", struct.pack("<If", 0, r) + bytes(8) + struct.pack("<3ff3ff", *a, r, *b, r))

    def convex(self, pts):
        return self.add("bhkConvexVerticesShape", struct.pack("<If", 0, 0.05) + bytes(24) + struct.pack("<I", len(pts))
                        + b"".join(struct.pack("<4f", *p, 0) for p in pts) + struct.pack("<I", 0))

    def list_shape(self, children):
        return self.add("bhkListShape", struct.pack("<I", len(children)) + struct.pack(f"<{len(children)}i", *children)
                        + struct.pack("<I", 0) + bytes(24) + struct.pack("<I", 0))

    def transform(self, child, t, r=IDENT_R):
        m = (r[0], r[3], r[6], 0, r[1], r[4], r[7], 0, r[2], r[5], r[8], 0, *t, 1)    # columns, then translation
        return self.add("bhkConvexTransformShape", struct.pack("<iIf", child, 0, 0.05) + bytes(8) + struct.pack("<16f", *m))

    def bytes(self):
        self.f.footer = struct.pack("<Ii", 1, 0)
        return nif.serialize(self.f)


def grid_mesh(nx, ny, size, z=lambda x, y: 0.0):
    verts, uvs, tris = [], [], []
    for j in range(ny + 1):
        for i in range(nx + 1):
            x, y = size * i / nx, size * j / ny
            verts.append((x, y, z(x, y)))
            uvs.append((i / nx, j / ny))
    for j in range(ny):
        for i in range(nx):
            a = j * (nx + 1) + i
            tris += [(a, a + 1, a + nx + 2), (a, a + nx + 2, a + nx + 1)]
    return verts, uvs, tris


def rock_nif(radius=600.0):
    """A dome-shaped rock (game units) with CMS collision of the same dome (havok units)."""
    n = SseNif()
    root = n.reserve("BSFadeNode")
    dome = lambda x, y: max(0.0, radius * radius - (x - radius) ** 2 - (y - radius) ** 2) ** 0.5 * 0.6  # noqa: E731
    v, uv, t = grid_mesh(12, 12, 2 * radius, dome)
    sh = n.trishape(b"Rock", v, uv, t, shader=n.lighting("textures\\landscape\\rocks\\rock01.dds",
                                                         "textures\\landscape\\rocks\\rock01_n.dds"))
    hv, _, ht = grid_mesh(8, 8, 2 * radius / 69.99124, lambda x, y: dome(x * 69.99124, y * 69.99124) / 69.99124)
    q = [tuple(int(round(c / 0.001)) for c in p) for p in hv]
    coll = n.collision(root, n.mopp(n.cms([((0.0, 0.0, 0.0), q, [], [i for tr in ht for i in tr])])))
    n.node(root, b"RockCliff01", [sh], coll=coll)
    return n.bytes()


def tree_nif():
    """Trunk (opaque) + leaves (alpha-tested) + capsule trunk collision through a rigid body T."""
    n = SseNif()
    root = n.reserve("BSFadeNode")
    trunk = n.trishape(b"Trunk", [(0, 0, 0), (40, 0, 0), (0, 40, 0), (0, 0, 800)], [(0, 0), (1, 0), (0, 1), (1, 1)],
                       [(0, 1, 3), (1, 2, 3), (2, 0, 3)],
                       shader=n.lighting("textures\\landscape\\trees\\bark.dds", "textures\\landscape\\trees\\bark_n.dds"))
    leaves = n.trishape(b"Leaves", [(-300, -300, 600), (300, -300, 600), (300, 300, 900)], [(0, 0), (1, 0), (1, 1)],
                        [(0, 1, 2)], shader=n.lighting("textures\\landscape\\trees\\leaves.dds",
                                                       "textures\\landscape\\trees\\leaves_n.dds"),
                        alpha=n.alpha(0x200 | 0xEC, 120))
    coll = n.collision(root, n.capsule((0, 0, 0.5), (0, 0, 10.0), 0.3), rigid_t=((0.0, 0.0, 0.2), (0, 0, 0, 1)))
    n.node(root, b"TreePine01", [trunk, leaves], coll=coll)
    return n.bytes()


def building_nif():
    """A box house: floor and walls as NiTriShape (older layout), a glow effect shape, list-shape collision of a floor
    box, a convex wall and a transformed box."""
    n = SseNif()
    root = n.reserve("BSFadeNode")
    v = [(0, 0, 0), (700, 0, 0), (700, 700, 0), (0, 700, 0), (0, 0, 350), (700, 0, 350)]
    walls = n.nitrishape(b"House", v, [(0, 0)] * 6, [(0, 1, 2), (0, 2, 3), (0, 1, 5), (0, 5, 4)],
                         shader=n.lighting("textures\\architecture\\wood.dds", "textures\\architecture\\wood_n.dds"))
    glow = n.trishape(b"Glow", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0)] * 3, [(0, 1, 2)], shader=n.effect())
    s = 1 / 69.99124
    floor = n.box((350 * s, 350 * s, 5 * s))
    floor_t = n.transform(floor, (350 * s, 350 * s, -5 * s))
    wall = n.convex([(0, 0, 0), (700 * s, 0, 0), (700 * s, 10 * s, 0), (0, 10 * s, 0), (0, 0, 350 * s),
                     (700 * s, 0, 350 * s), (700 * s, 10 * s, 350 * s), (0, 10 * s, 350 * s)])
    coll = n.collision(root, n.list_shape([floor_t, wall]))
    n.node(root, b"WRHouse01", [walls, glow], coll=coll)
    return n.bytes()


def fern_nif():
    """A plant without collision (Skyrim lets you walk through it)."""
    n = SseNif()
    root = n.reserve("BSFadeNode")
    sh = n.trishape(b"Fern", [(0, 0, 0), (50, 0, 0), (0, 50, 60)], [(0, 0), (1, 0), (0, 1)], [(0, 1, 2)],
                    shader=n.lighting("textures\\plants\\fern.dds", "textures\\plants\\fern_n.dds"),
                    alpha=n.alpha(0x200, 128))
    n.node(root, b"Fern01", [sh])
    return n.bytes()


def rgba_dds(w=8, h=8, alpha=255):
    import tempfile
    px = np.zeros((h, w, 4), np.uint8)
    px[..., 0], px[..., 1], px[..., 2] = 120, 128, 255
    px[..., 3] = alpha
    px[0, 0, 3] = 0
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "t.dds")
        textures.write_dds_dx10(p, w, h, textures.DXGI_R8G8B8A8_UNORM, px.tobytes(), 4)
        with open(p, "rb") as f:
            return f.read()


MODELS = {
    "meshes\\landscape\\rocks\\rockcliff01.nif": rock_nif,
    "meshes\\landscape\\trees\\treepine01.nif": tree_nif,
    "meshes\\architecture\\whiterun\\wrhouse01.nif": building_nif,
    "meshes\\landscape\\plants\\fern01.nif": fern_nif,
}
TEXTURES = ["textures\\landscape\\rocks\\rock01.dds", "textures\\landscape\\rocks\\rock01_n.dds",
            "textures\\landscape\\trees\\bark.dds", "textures\\landscape\\trees\\bark_n.dds",
            "textures\\landscape\\trees\\leaves.dds", "textures\\landscape\\trees\\leaves_n.dds",
            "textures\\architecture\\wood.dds", "textures\\architecture\\wood_n.dds",
            "textures\\plants\\fern.dds", "textures\\plants\\fern_n.dds"]


def skyrim_data(path):
    """A Skyrim SE Data folder: meshes in an LZ4 v105 archive, textures in a zlib v104-style second archive."""
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "Skyrim - Meshes0.bsa"), "wb") as f:
        f.write(bsa.build({k: fn() for k, fn in MODELS.items()}, version=105, compress=True))
    tex = {t: rgba_dds(alpha=200 if "leaves" in t or "fern" in t else 255) for t in TEXTURES}
    with open(os.path.join(path, "Skyrim - Textures0.bsa"), "wb") as f:
        f.write(bsa.build(tex, version=105, compress=False, embed_names=True))
    return path


# ---------------------------------------------------------------------------------------------------------- Starfield
def content_resources(path):
    mat = {"Objects": [{"Components": [{"Type": "BSComponentDB::CTName", "Data": {"Name": "x"}}]}],
           "Summary": {"Layer1": {"Textures": {"Albedo": {"File": "a"}, "Normal": {"File": "b"},
                                                "Roughness": {"File": "c"}, "Opacity": {"File": "d"},
                                                "Metalness": {}}}}}
    from fo4sf import convert_material as cm
    with zipfile.ZipFile(path, "w") as z:
        for name in (cm.TEMPLATE_MAT, cm.DECAL_TEMPLATE_MAT, cm.GLASS_TEMPLATE_MAT):
            z.writestr(name, json.dumps(mat))
    return path


def collision_template_nif(path):
    from test_collision import fake_template
    shape = sfnif.StaticShape(b"s", b"0" * 20 + b"\\" + b"1" * 20, 3, 3, "m.mat", (0, 0, 0, 1), (0, 0, 0, 1, 1, 1))
    f = sfnif.build_static_nif(b"box", [shape], collision_blob=fake_template())
    with open(path, "wb") as fh:
        fh.write(nif.serialize(f))
    return path


def starfield_meshes_ba2(path, files):
    """A version-1 GNRL archive (stored entries) holding {name: bytes}, as 'Starfield - Meshes01.ba2'."""
    names = list(files)
    head = 24 + 36 * len(names)
    offs, pos = [], head
    for n in names:
        offs.append(pos)
        pos += len(files[n])
    out = [struct.pack("<4sI4sIQ", b"BTDX", 1, b"GNRL", len(names), pos)]
    for n, o in zip(names, offs):
        out.append(struct.pack("<I4sIIQIII", 0, b"nif\0", 0, 0, o, 0, len(files[n]), 0xBAADF00D))
    out += [files[n] for n in names]
    out += [struct.pack("<H", len(n)) + n.encode() for n in names]
    with open(path, "wb") as f:
        f.write(b"".join(out))
    return path


# ---------------------------------------------------------------------------------------------------------- ESM
BASES = [  # (sig, form id, editor id, model)
    (b"STAT", 0x0A01, "RockCliff01", "Landscape\\Rocks\\RockCliff01.nif"),
    (b"TREE", 0x0A02, "TreePine01", "Landscape\\Trees\\TreePine01.nif"),
    (b"STAT", 0x0A03, "WRHouse01", "Architecture\\Whiterun\\WRHouse01.nif"),
    (b"FLOR", 0x0A04, "Fern01", "Landscape\\Plants\\Fern01.nif"),
    (b"STAT", 0x0A05, "XMarkerHeading", "Marker_Heading.nif"),
    (b"LIGH", 0x0A06, "TorchLight", "Clutter\\Torch.nif"),
    (b"STAT", 0x0A07, "FXFogBank", "Effects\\FXFogBank.nif"),
    (b"STAT", 0x0A08, "MissingMesh01", "Clutter\\DoesNotExist.nif"),
    (b"NPC_", 0x0A09, "Guard", ""),
]


def build_esm(world_items_cells, hills, extent, base_records=BASES, persistent_refs=()):
    """Skyrim.esm-shaped plugin: base groups, Tamriel with LAND everywhere in `extent` and the given references.
    world_items_cells: {(cx, cy): [(sig, fid, base, pos, rot, scale, flags, xesp)]}"""
    from test_fo4land import grup, rec
    from test_skyrimland import cell_vhgt
    tes4 = rec(b"TES4", 0, [(b"HEDR", struct.pack("<fII", 1.71, 0, 0x800))])
    groups = {}
    for sig, fid, edid, model in base_records:
        f = [(b"EDID", edid.encode() + b"\0")] + ([(b"MODL", model.encode() + b"\0")] if model else [])
        groups.setdefault(sig, []).append(rec(sig, fid, f, compress=(sig == b"TREE")))
    out = tes4 + b"".join(grup(sig, 0, items) for sig, items in groups.items())

    def ref(sig, fid, base, pos, rot, scale, flags, xesp):
        f = [(b"NAME", struct.pack("<I", base)), (b"DATA", struct.pack("<6f", *pos, *rot))]
        if scale != 1.0:
            f.append((b"XSCL", struct.pack("<f", scale)))
        if xesp:
            f.append((b"XESP", struct.pack("<IB", *xesp)))
        r = rec(sig, fid, f)
        if flags:
            r = r[:8] + struct.pack("<I", flags) + r[12:]
        return r

    pcell = rec(b"CELL", 0x200, [(b"DATA", b"\x02\0")])
    items = [pcell, grup(0x200, 6, [grup(0x200, 8, [ref(*r) for r in persistent_refs])])]
    sub, fid = [], 0x1000
    x0, x1, y0, y1 = extent
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            cfid, lfid = fid, fid + 1
            fid += 2
            sub.append(rec(b"CELL", cfid, [(b"DATA", b"\0\0"), (b"XCLC", struct.pack("<iiI", x, y, 0))], compress=True))
            vh, _ = cell_vhgt(x, y)
            kids = [rec(b"LAND", lfid, [(b"DATA", b"\0" * 4), (b"VHGT", vh)], compress=True)]
            kids += [ref(*r) for r in world_items_cells.get((x, y), [])]
            sub.append(grup(cfid, 6, [grup(cfid, 9, kids)]))
    items.append(grup(b"\0\0\0\0", 4, [grup(b"\0\0\0\0", 5, sub)]))
    wrld = rec(b"WRLD", 0x3C, [(b"EDID", b"Tamriel\0"), (b"DNAM", struct.pack("<ff", -2048.0, -14000.0))])
    return out + grup(b"WRLD", 0, [wrld, grup(0x3C, 1, items)])
