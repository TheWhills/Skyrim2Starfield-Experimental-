# S1: write a Starfield mesh from a script

**Question:** can a script produce a Starfield static (NIF + external `.mesh`) from a Fallout 4 NIF?
**Result (2026-10-07): offline part is GO.** Everything we can check without launching Starfield passes.
**Not yet verified:** that NifSkope displays it and that the game renders it (oracle levels L1-L3).
That needs a human with NifSkope, then S2 (plugin) and S9 (loading) for the in-game check.

Code: `src/fo4sf/sfmesh.py`, `nif.py`, `sfnif.py`, `convert_static.py`. Oracles: `scripts/oracles/`.
Versions: Fallout 4 1.10.163, Starfield 1.16.244.

## What was established (all measured on vanilla files)

| Fact | Evidence |
|---|---|
| `.mesh` layout = `BSMeshData` from the fo76utils `nif.xml` | 3,000 of 3,000 sampled vanilla meshes parse and re-serialise **byte-identical** |
| Last two sections (meshlets, cull data) are optional | 15 skinned face meshes end right after the LOD count |
| Positions: `int16 / 32767 * scale`; scale = largest absolute coordinate works | decode/encode test; coordinates are **metres** |
| Normals/tangents: 10:10:10:2 packed, `x = (bits/1023)*2-1`; normal w bits = 1 | mean unit-length error 0.0007 over 17k normals |
| Tangent sign: top two bits are `3` = positive, `0` = negative handedness (UV-derived) | 98.8% / 98.6% agreement over 22k vertices |
| **Meshlets:** consecutive triangle groups of at most **96 unique vertices and 128 triangles**; `vertex_count` = unique verts of the group; `vertex_offset` = running sum of vertex counts; `tri_offset` = running sum of `round_up(3 * tri_count, 4)` | holds for **4,000 of 4,000** meshes; greedy in-order split reproduces the real partition on 2,000 of 2,000 |
| Cull data per meshlet: bounding box of the group's vertices, 6 floats (centre xyz, half-extent xyz) | within 1e-3 for 1,998 of 2,000 meshes |
| NIF container: header + string table + sized blocks round-trips | 1,500/1,500 Fallout 4 (BS 130) and 1,500/1,500 Starfield (BS 173) |
| Starfield header has an extra `Unknown Data` field and no `Max Filepath` | spec + round-trip |
| Base-game Starfield NIFs are **BS 173**; newer DLC is **BS 175** | `Starfield - Meshes01.ba2` sample vs DLC sample |
| `BSGeometry` layout, `Meshes[4]` slots (LOD 0..3), `Mesh Path` = `<20 hex>\<20 hex>` relative to `Data/geometries`, no extension; flags always `0x40` | 20,224 of 20,224 vanilla blocks rebuilt byte-identical |
| The shader property block is just a name: the **`.mat` path** | vanilla `setdressing` props are 5 blocks: `NiNode, BSXFlags, BSGeometry, NiIntegerExtraData, BSLightingShaderProperty` |
| `NiIntegerExtraData "MaterialID"` = CRC32 (poly `0xEDB88320`, init 0, no final xor) of the lowercase material path with backslashes | 60 of 60 vanilla pairs |

## Result on a real Fallout 4 asset

`Meshes\SetDressing\PatioFurniture\ChairPatio01.nif` (1,034 vertices, 940 triangles) converts to a
607-byte NIF plus one 24,788-byte `.mesh` (12 meshlets). Size 0.91 x 0.83 x 1.04 m at 1/70 m per
Fallout 4 unit. Re-reading the output with our own parsers passes every consistency check (container,
`BSGeometry`, mesh round trip, meshlet rules, index range). A turntable render *from the generated
files* looked like the chair.

## Open items before S1 is closed

1. **L1:** open the output in the fo76utils NifSkope (`Settings > Resources`: add the staging folder) and confirm shape and no errors.
2. **L2/L3:** reference the NIF from a `STAT` (needs S2) and place it in game (needs S9).
3. **Units (S4):** 1/70 m per unit is an assumption; compare with a vanilla chair in game.
4. Winding, UV orientation, `BSXFlags` and the `Unknown Data` header bytes are copied from vanilla conventions; the game is the real judge.
5. Not covered: skinned meshes, LOD slots 1-3, collision (S6), real materials (S3), `BSSubIndexTriShape` segments.

## Reproduce

```
python -I scripts/oracles/validate_mesh.py        src scripts <Starfield Data> 3000
python -I scripts/oracles/verify_meshlet_rule.py  src scripts <Starfield Data>
python -I scripts/oracles/roundtrip_nif.py        src scripts <FO4 Meshes.ba2> <Starfield Meshes01.ba2> 1500
python -I scripts/oracles/roundtrip_bsgeometry.py src scripts <Starfield Data>
python -I scripts/oracles/convert_chair.py        src scripts <FO4 Meshes.ba2> setdressing\patiofurniture\chairpatio01.nif <out dir> fo4port/setdressing/chairpatio01
```

## In-game result (2026-10-07): L3 passed

The converted `ChairPatio01` loads in Starfield 1.16.244 and renders: correct silhouette, **not inside-out** (winding is right),
natural size (the 1/70 m assumption holds), lit and shadowed by the scene, with the placeholder `MetalIronCast01.mat`
material. Screenshot: [media/fo4-chair-in-starfield.png](media/fo4-chair-in-starfield.png). Header bytes copied from vanilla
(`Unknown Data`, `BSXFlags`) were accepted. Still open: skinned meshes, LOD slots, collision (S6; the chair has none yet), real
materials (S3).
