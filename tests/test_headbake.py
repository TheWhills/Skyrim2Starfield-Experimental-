"""headbake: a race shape baked into a head's own meshes and NIF (2026-11-10, owner: the Orc race did not look Orc
after the race change; the shape was only an optional chargen blend)."""
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fo4sf import headbake, nif as nifmod, sfmesh, sfnif  # noqa: E402
from fo4sf.convert_static import mesh_file_path  # noqa: E402


def grid(n=6, step=0.01):
    """A flat n x n vertex grid facing +z as an SfMesh (normals +z, tangents +x), and its points."""
    pts = [(x * step, y * step, 0.0) for y in range(n) for x in range(n)]
    tris = []
    for y in range(n - 1):
        for x in range(n - 1):
            a, b, c, d = y * n + x, y * n + x + 1, (y + 1) * n + x, (y + 1) * n + x + 1
            tris += [(a, b, d), (a, d, c)]
    scale, raw = sfmesh.encode_positions(pts, margin=0.02)
    m = sfmesh.SfMesh(triangles=tris, scale=scale, positions=raw, uv1=[(0, 0)] * len(pts), uv2=[],
                      colors=[], normals=[sfmesh.encode_packed(0, 0, 1)] * len(pts),
                      tangents=[sfmesh.encode_packed(1, 0, 0, 1)] * len(pts), weights=[], lods=[])
    sfmesh.build_meshlets(m)
    return m, np.array(pts, float)


def positions(m):
    return np.array([sfmesh.decode_position(p, m.scale) for p in m.positions], float)


class BakedMeshTests(unittest.TestCase):
    def test_moves_keep_room_and_turn_normals(self):
        m, pts = grid()
        room = m.scale - np.abs(pts).max()
        disp = np.zeros_like(pts)
        disp[:, 2] = pts[:, 0] * 0.5                       # a slope: z rises along x
        out = headbake.baked_mesh(m, pts, disp)
        self.assertLess(np.abs(positions(out) - (pts + disp)).max(), 1e-5)
        self.assertGreaterEqual(out.scale - np.abs(pts + disp).max(), room - 1e-9)   # chargen morph room kept
        n = np.array([sfmesh.decode_packed(u)[:3] for u in out.normals])
        want = np.array([-0.5, 0, 1]) / np.linalg.norm([-0.5, 0, 1])                # normal of z = 0.5 x
        self.assertGreater(float((n[14] / np.linalg.norm(n[14])) @ want), 0.99)
        t = np.array([sfmesh.decode_packed(u) for u in out.tangents])
        self.assertAlmostEqual(abs(float(t[14, :3] @ want)), 0.0, delta=0.02)         # still in the surface
        self.assertEqual(round(t[14, 3]), 1)                                          # bitangent sign kept
        self.assertEqual(len(out.meshlets), len(m.meshlets))
        self.assertNotEqual(out.cull_data, m.cull_data)
        self.assertEqual(len(m.positions), len(out.positions))
        self.assertLess(np.abs(positions(m) - pts).max(), 1e-5)                         # the input untouched

    def test_lod_takes_nearest_head_vertex(self):
        m, pts = grid()
        lod, lpts = grid(3, 0.025)                         # 9 vertices on the same plane
        disp = np.zeros_like(pts)
        disp[:, 2] = np.arange(len(pts)) * 1e-4
        out = headbake.baked_mesh(lod, pts, disp)
        near = headbake.nearest(pts, lpts)
        self.assertLess(np.abs(positions(out)[:, 2] - disp[near, 2]).max(), 1e-5)
        self.assertEqual(int(near[0]), 0)


class BakedNifTests(unittest.TestCase):
    def test_head_geometry_repointed(self):
        m, pts = grid()
        data = sfmesh.serialize(m)
        d, f = mesh_file_path(data)
        head_path = f"{d}\\{f}"
        other, _p = grid(2)
        od, of = mesh_file_path(sfmesh.serialize(other))
        shapes = [sfnif.SkinnedShape(b"Head", head_path.encode(), len(m.triangles) * 3, len(m.positions),
                                     "x.mat", [b"C_Head"], [((0, 0, 0, 1), (1, 0, 0, 0, 1, 0, 0, 0, 1), (0, 0, 0), 1.0)]),
                  sfnif.SkinnedShape(b"Other", f"{od}\\{of}".encode(), 6, 4, "y.mat", [b"C_Head"],
                                     [((0, 0, 0, 1), (1, 0, 0, 0, 1, 0, 0, 0, 1), (0, 0, 0), 1.0)])]
        nif_bytes = nifmod.serialize(sfnif.build_skinned_nif(b"Head", shapes))
        files = {f"geometries/{d}/{f}.mesh": data}
        disp = np.tile([0.0, 0.0, 0.003], (len(pts), 1))
        out = headbake.baked_head_files(nif_bytes, files.__getitem__, head_path, pts, disp,
                                        "meshes/s2s/races/orc/malehead.nif")
        self.assertIn("meshes/s2s/races/orc/malehead.nif", out)
        meshes = [k for k in out if k.startswith("geometries/")]
        self.assertEqual(len(meshes), 1)
        baked = sfmesh.parse(out[meshes[0]])
        self.assertLess(np.abs(positions(baked) - (pts + disp)).max(), 1e-5)
        n = nifmod.parse(out["meshes/s2s/races/orc/malehead.nif"])
        paths = [g.meshes[0].path.decode() for g in (sfnif.parse_bsgeometry(b) for i, b in enumerate(n.blocks)
                                                       if n.type_of(i) == "BSGeometry")]
        self.assertEqual(paths, [meshes[0][len("geometries/"):-len(".mesh")].replace("/", "\\"), f"{od}\\{of}"])
        with self.assertRaises(ValueError):
            headbake.baked_head_files(nif_bytes, files.__getitem__, "nope\\nope", pts, disp, "x.nif")


if __name__ == "__main__":
    unittest.main()
