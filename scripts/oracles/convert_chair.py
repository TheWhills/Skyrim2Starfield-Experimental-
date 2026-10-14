"""Convert one real FO4 NIF with the S1 converter and verify the output by re-parsing it.
usage: convert_chair.py <repo/src> <repo/scripts> <FO4 Meshes.ba2> <fo4 nif name (lowercase suffix)> <out dir> <out name>"""
import os
import sys

sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import recon  # noqa: E402
from fo4sf import convert_static, nif, sfmesh, sfnif  # noqa: E402

ba2 = recon.read_ba2(sys.argv[3])
want = sys.argv[4].lower()
hit = next(i for i, n in enumerate(ba2["names"]) if n.lower().replace("/", "\\").endswith(want))
raw = recon.extract_gnrl(ba2, hit)
src = nif.parse(raw)
shapes = nif.fo4_trishapes(src)
print(f"source: {ba2['names'][hit]}  {len(raw)} bytes, blocks {src.block_types}")
for s in shapes:
    xs = [p[0] for p in s.positions]; ys = [p[1] for p in s.positions]; zs = [p[2] for p in s.positions]
    print(f"  shape {s.name!r}: {len(s.positions)} verts, {len(s.triangles)} tris, uv={bool(s.uvs)} normals={bool(s.normals)} "
          f"tangents={bool(s.tangents)} colors={bool(s.colors)} skinned={s.skinned}")
    print(f"  FO4 size (units): x {max(xs)-min(xs):.1f}  y {max(ys)-min(ys):.1f}  z {max(zs)-min(zs):.1f}   node transform t={s.translation} s={s.scale}")

files = convert_static.convert_static(raw, sys.argv[6])
out_dir = sys.argv[5]
for rel, data in files.items():
    path = os.path.join(out_dir, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    print(f"wrote {rel}  {len(data)} bytes")

# ---- verify by re-reading what we wrote -------------------------------------------------
nif_rel = next(r for r in files if r.endswith(".nif"))
out = nif.parse(files[nif_rel])
assert nif.serialize(out) == files[nif_rel], "NIF container round trip"
print("\nverify: output NIF parses, round-trips; blocks:", [out.type_of(i) for i in range(len(out.blocks))], "bs", out.bs_version)
for k, b in enumerate(out.blocks):
    if out.type_of(k) != "BSGeometry":
        continue
    g = sfnif.parse_bsgeometry(b)
    assert sfnif.build_bsgeometry(g) == b
    mref = g.meshes[0]
    mp = "geometries/" + mref.path.decode().replace("\\", "/") + ".mesh"
    m = sfmesh.parse(files[mp])
    assert sfmesh.serialize(m) == files[mp], "mesh round trip"
    assert mref.indices_size == len(m.triangles) * 3 and mref.num_verts == len(m.positions)
    tri_start, vo, to = 0, 0, 0
    for (vc, v_off, tc, t_off) in m.meshlets:
        tris = m.triangles[tri_start:tri_start + tc]
        assert vc == len({v for t in tris for v in t}) and v_off == vo and t_off == to and vc <= 96 and tc <= 128
        tri_start += tc; vo += vc; to += -(-(3 * tc) // 4) * 4
    assert tri_start == len(m.triangles)
    assert max(max(t) for t in m.triangles) < len(m.positions)
    pts = [sfmesh.decode_position(p, m.scale) for p in m.positions]
    size = [max(p[a] for p in pts) - min(p[a] for p in pts) for a in range(3)]
    print(f"  mesh {mp}: {len(m.positions)} verts, {len(m.triangles)} tris, {len(m.meshlets)} meshlets, scale {m.scale:.4f}")
    print(f"  size in metres: x {size[0]:.3f}  y {size[1]:.3f}  z {size[2]:.3f}")
    print(f"  shader ref block {g.shader} -> {out.type_of(g.shader)}")
print("ALL CHECKS PASSED")
