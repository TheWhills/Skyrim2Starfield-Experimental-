# S3: materials and textures (2026-10-07)

**Result: GO, confirmed in game.** A Fallout 4 material and its textures convert to a Starfield `.mat` + DDS set that renders
correctly in Starfield 1.16.244. Screenshot: [media/fo4-chair-textured-in-starfield.png](../media/fo4-chair-textured-in-starfield.png).
Code: `src/fo4sf/textures.py`, `convert_material.py`, `scripts/convert_asset.py`. Fidelity tier T2 (colour, normal, roughness).

## Formats (measured)

| Map | Fallout 4 | Starfield (vanilla) | Conversion |
|---|---|---|---|
| Colour | `_d` DXT5/BC1, sRGB | `_color` **BC1_SRGB** (DX10 header) | `texconv -f BC1_UNORM_SRGB -srgbi -m 0 -dx10` |
| Normal | `_n` BC5, legacy fourCC `BC5U`, RG unorm | `_normal` **BC5_SNORM** | decode, map 0..255 to signed bytes, write R8G8_SNORM, `texconv -f BC5_SNORM` |
| Roughness | `_s` BC5 `BC5U`: R = specular, G = smoothness | `_rough` **BC4_UNORM** (1 = rough) | `255 - G` as R8, `texconv -f BC4_UNORM` |
| Metalness | (none; spec/gloss workflow) | replacement value in the `.mat` | constant per material (default 0) |

- This build of `texconv` (the one in xEdit's `Edit Scripts`) cannot read the legacy `BC5U` fourCC, so `textures.py` has its
  own BC4/BC5 decoder (numpy). Verified visually and by block tests.
- Pass `-dx10`: otherwise texconv writes legacy `BC5S`/`BC4U` headers, unlike vanilla.
- The `.bgsm` texture block is found by scanning for the first length-prefixed `.dds` string; the chair's material also
  carries a chrome environment map and spec settings that are not used yet.

## The `.mat` format

A `.mat` is JSON, but a *component database*: `Objects` with `ID`s such as `res:AF816D82:0005A5E4:A487E721`, `Edges`,
typed `Components`, plus a human-readable `Summary.Layer1` (textures, tint, `UseReplacement` flags). Writing one from scratch
is impractical, so `build_mat` **clones a vanilla single-layer PBR material** and:
1. replaces the three texture paths (in both `Objects` and `Summary`);
2. sets the tint to white and the metalness replacement;
3. gives every object the file defines a **new ID** (CRC32 of name + old ID in the first group) so it cannot clash with the
   vanilla material it was cloned from; `Parent` values (class ids and vanilla parents) are left alone;
4. renames the `CTName` entries.

The template (`Materials/Common/Metal/MetalIronCast01.mat`) is read at run time from the user's own
`Starfield\Tools\ContentResources.zip` (shipped with the Creation Kit) and is **never committed**.

The NIF links to the material by *name*: its `BSLightingShaderProperty` block is just the `.mat` path (and `MaterialID` is
the CRC32 of that path, see S1). Files go in `<plugin> - Main.ba2` (`materials/...`) and `<plugin> - Textures.ba2`
(`textures/...`, built with `Archive2 -format=DDS`).

## In-game result

The converted chair shows the original embossed floral panels, rust and paint wear and normal-mapped depth, and is lit and
shadowed by the scene. Not yet assessed: whether the green channel of the normal map needs flipping (relief looks correct
under the bar lights, `--flip-green` exists), the colour under neutral light, and metals (all converted as non-metal).

## Not covered yet

Emissive/glow maps, alpha test/blend, two-sided and decals, environment-map reflections, tint palettes, `.bgem` effect
materials, material swaps, atlas UV tiling flags (`tile_u/v` are parsed but unused), automatic metalness.
Bulk extraction note: Archive2's `-includeFilters` did not filter in our tests (it extracted entire archives), so bulk
conversion should use our own BA2 reader (`recon.py`) plus a DX10/LZ4 texture reader (next work package).
