# Fallout 4 vs Starfield: measured format differences

Measured on 2026-10-06 with [`scripts/recon.py`](../scripts/recon.py) and
[`scripts/recon_physics.py`](../scripts/recon_physics.py), read-only, against Fallout 4 **1.10.163** and
Starfield **1.16.244**. Raw numbers: [`docs/measurements/`](measurements/). Sampling: up to 300 records per
type for the subrecord comparison.

## Plugins (`.esm`)

| | Fallout 4 `Fallout4.esm` | Starfield `Starfield.esm` |
|---|---|---|
| Header form version | 131 | 581 |
| HEDR version | 1.0 | 0.96 |
| Records | 1,549,050 | 3,829,246 |
| Record types | 137 | 180 |
| Types in common | 116 | 116 |

- **Same signature, different layout.** Sampled subrecord-signature overlap (Jaccard) between the games is
  mostly 0.25–0.6: `STAT` 0.23, `REFR` 0.25, `WEAP` 0.30, `NPC_` 0.51, `QUST` 0.58. Close matches are only
  `NAVM` 1.0, `PACK` 0.87, `MGEF`/`MATT` 0.80, `IDLE` 0.78. Each type needs a field-level translator.
- **No `LAND` records in Starfield** (Fallout 4: 37,020). Starfield terrain is `.btd` files + procedural
  planet generation. See RISKS.md S5.
- **No `SNDR` in Starfield** (Fallout 4: 5,476). Audio is Wwise: `WWED` events, `.bnk` / `.wem`.
- **Only in Fallout 4:** `AECH ASTP CMPO DLVW ECZN GDRY INGR LAND MATO MSWP NOTE PMIS RELA RFCT SCCO SCSN
  SNCT SNDR SOPM TACT TREE`.
- **Only in Starfield:** 64 types, including the planet/biome/ship family (`PNDT BIOM ATMO SUNP MRPH TMLM
  STBH ...`).

## Archives (`.ba2`)

| | Fallout 4 | Starfield |
|---|---|---|
| BA2 version | 1 (zlib) | 2 (GNRL / DX10), 3 (LZ4 textures) |
| Meshes | ~198.7k `.nif` | ~109.9k `.nif` + **~684k `.mesh`** |
| Materials | 7,077 `.bgsm` + 295 `.bgem` | 1 file: `materials/materialsbeta.cdb` (compiled), loose `.mat` JSON supported |
| Animation | 15,741 `.hkx` | `.af` 19.4k, `.afx` 19.4k, `.agx`, `.rig`, `.ffxanim` 278k (face) |
| Audio | 122,857 `.fuz` + 7,380 `.xwm` + `.wav` | 325,246 `.wem` + `.bnk` |
| Scripts | 8,369 `.pex` | 5,034 `.pex` |
| Terrain | `LAND` records, `.btr`/`.bto` LOD (13.4k) | 2,112 `.btd`, `.biom`, `.lod` |

## Meshes and physics

| | Fallout 4 | Starfield |
|---|---|---|
| NIF BS version | 130 (user version 12) | 173 (base game) and 175 (newer DLC), user version 12 |
| Geometry | inline `BSTriShape` / `BSSubIndexTriShape` | `BSGeometry` → external `.mesh` (`geometries\<hash>\<hash>.mesh`) |
| `.mesh` file | n/a | version `2`, index count, triangles (u16 x3), scale, then int16 positions, half-float UVs, packed normals/tangents, meshlets and per-meshlet bounding boxes. Fully specified and verified, see [S1](spikes/S1-mesh-writer.md) |
| Collision | Havok 2014.1.0-r1 packfile in `bhkPhysicsSystem` | Havok tagfile (`TAG0` / `SDKV`), `hknp*` shapes |
| Material reference | `.bgsm` / `.bgem` paths | `.mat` paths (many with leading `\`) |
| Facegen | `.nif` + `.tri` | `BSFaceGenNiNode` + morph `.dat` (`MRPH`) |

## What this means for the work

1. Every mesh needs re-serialising with geometry split into `.mesh` files (S1).
2. Every material needs authoring in a different shading model (S3).
3. Every collision shape needs rebuilding in a newer Havok format (S6).
4. Terrain, animation, voice and sound can't be translated record-for-record; each needs a design (S5, S7, WP-14/15).
5. Papyrus (`.pex`) is the same language in both, but the native functions differ. Sources must be
   recompiled against shims (WP-16).
