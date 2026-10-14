# WP-10 first light: Vault 111 in Starfield (2026-10-07)

**Result: the Fallout 4 `Vault111Cryo` interior loads in Starfield 1.16.244 as a new cell you can stand in.**
Screenshots: [entrance](../media/vault111-entrance-in-starfield.png), [stairs to the machinery](../media/vault111-stairs-in-starfield.png).

## Pipeline

1. `dotnet/Fo4Export`: reads `Fallout4.esm` with Mutagen and exports a cell's placed references (base type, base EditorID,
   model, position, rotation, scale) to JSON. `Vault111Cryo`: 3,087 references (1,034 statics, 849 lights, 540 texture-set
   decals, 371 movable statics, 63 furniture, 39 doors, ...), 268 distinct models.
2. `scripts/convert_batch.py --cell-json`: converts every model of the chosen base types straight from the FO4 archives
   (native BA2 reader). 234 converted, 12 failed (animated/skinned furniture, lockers, desks), editor markers skipped.
   Box collision for props only; architecture (`meshes/Interiors`, `meshes/Architecture`) gets none for now, because one AABB
   would fill a whole corridor.
3. `dotnet/PluginSpike` (plugin writer): one `STAT` per model plus an interior `CELL` `FO4Port_Vault111Cryo` with 1,365 placed
   references at the FO4 position **/ 70** (Starfield placements are in metres: vanilla nearest-neighbour spacing 0.91 vs 72 units
   in FO4), same rotation (radians) and scale. Lighting: vanilla `ShipInteriorLT` template and a vanilla neutral 8 m omni light
   (`LGT_ShipInterior_Omni_NS_Neutral_2k`) at each FO4 light position, merged within 3 m (132 lights). This makes `Starfield.esm`
   a master; Mutagen then needs `WithKnownMasters(new KeyedMasterStyle(Starfield.esm, MasterStyle.Full))` when writing.
4. `scripts/deploy_starfield.py`, then in game: `coc FO4Port_Vault111Cryo`.

## What it looks like

- The layout is right: entrance hoses, staircase up to the vault-door machinery, cryo-pod hall, consoles, crates; everything
  where Fallout 4 put it, at the right scale and orientation, textured.
- **Over-exposed**: too much light (132 overlapping 8 m omnis + a bright template) and a white void where there is no geometry.
- Colour looks desaturated. The vault is mostly grey concrete and steel in FO4 too; to be checked once exposure is fixed.
- Player can stand on the floor at the arrival point; elsewhere floors have no collision yet.

## Next

1. Lighting: fewer/dimmer lights matched to FO4 light radius/colour, a darker template, fill the void (skybox/fog).
2. Real collision for architecture (mesh or convex-decomposition shapes), then navmesh.
3. Doors, furniture, the 12 failed models (animated/skinned), decals (texture sets), movable statics.
4. Load doors / a way in other than `coc`.

## Architecture collision: thin boxes behind flat surfaces (2026-10-08)

Single AABBs cannot work for rooms, so `sfcollision.surface_boxes` groups each mesh's axis-aligned triangles by (axis, facing,
plane offset), splits them into connected clusters and gives each cluster a box 15 cm deep behind the surface. Each box is its
own body on a child `NiNode` (`sfnif.build_static_nif(child_collision_blobs=...)`). Vault floor tile `VltFloor01` -> one
3.66 x 3.66 x 0.15 m slab; heavy machinery hits the 48-box cap. In game the player walks across the vault floor without falling
through ([screenshot](../media/vault111-walking-on-floor.png)); stairs, sloped and curved surfaces are not covered yet
(no boxes for non-axis-aligned triangles). Lights reduced to 60 dimmer omnis + `DefaultLightingTemplate`; the scene is still
over-exposed, but FO4's own Vault 111 concrete textures are genuinely light (mean ~200-220/255), so exposure, not texture
conversion, is the cause.

## Collision v2 and cleanup (2026-10-08)

- `sfcollision.mesh_boxes`: thin boxes behind flat axis-aligned surfaces **plus voxel boxes** (0.2 m grid, greedily merged,
  coarsened to stay under the cap) for slopes, curves, rails, pipes and small parts; up to ~190 bodies on the most complex
  machinery. A user play-test of v1 found "some things have collision, some don't"; v2 covers the remainder.
- In game: the player stood at z = 0.41 m, walked 3.5 s and ended at z = 0.00 (on the vault floor, no fall-through); walking
  into the stair railings and posts stops the player.
- Fallout 4 effect meshes (fog / light volumes under `meshes\Effects`) are no longer converted; they rendered as solid grey
  shapes. 205 models, 1,003 references, 60 lights.
- Open: banded "marbled" artefacts on some surfaces (likely normal/roughness channel mapping on certain materials), exposure,
  the arrival point (no COC marker: the player lands at the cell origin inside geometry).

## Colour fixed: the material tint was replacing every texture (2026-10-08)

Play-test feedback: "weird textures". A walk-through showed white, clay-like surfaces (normal and roughness detail only) and some
surfaces with the template's marble look. Diagnosis by experiment:
- Converted colour textures were correct (decoded contact sheets) and stored in the archive in vanilla formats.
- A test chair with a pure-magenta 64x64 colour texture rendered **white** in neutral light, so no albedo was applied at all.
- Cause: `build_mat` set the material's `BSMaterial::Color` to `(1, 1, 1, 1)`. The **w component is the tint strength**:
  at 1.0 the flat tint colour replaces the albedo texture. Vanilla `MetalIronCast01` uses 0.72. Now the default tint is
  `(1, 1, 1, 0)` and the vault renders in its real colours ([catwalk](../media/vault111-color-catwalk.jpg),
  [stairs](../media/vault111-color-stairs.jpg)).

Also in this pass:
- Shapes without a `.bgsm` now use their `BSShaderTextureSet` textures (diffuse, normal, smooth-spec at index 7); effect-shader
  shapes (glass, frost, glow) are skipped instead of drawn with a placeholder; the `.bgsm` parser no longer crashes on short
  decal/label materials; the last-resort fallback is a plain grey material instead of the vanilla marble template.
  Result: 162 materials converted, 1 fallback (was 120 / 6 with 209 placeholder shapes).
- Voxel collision boxes are never coarser than ~0.5 m (coarse voxels behaved like invisible walls).
- Tooling lesson: judging colours under the bar's orange/teal lights was misleading; test colour in neutral light.

## Arrival point and lighting (2026-10-08)

The FO4 cell's `COCMarkerHeading` is now placed as Starfield's vanilla `COCMarkerHeading` (000032), so `coc FO4Port_Vault111Cryo`
lands in the cryo room where Fallout 4 puts it, and the lighting template is `KreetBase01LGTtemplate` (an underground base).
The cryo pods, tanks, gauges, corridor arches and Vault-Tec signage all show their original textures:
[cryo row](../media/vault111-cryo-row.jpg), [cryo pod](../media/vault111-cryopod.jpg), [corridor](../media/vault111-corridor.jpg).

## Skinned props (2026-10-08)

Lockers, desks, dressers, file cabinets and the oxygen-tank stand are skinned in Fallout 4 only so their doors and drawers can
animate. Taking their vertices in bind pose gives the correct resting shape (checked with `render_preview.py`), so the pipeline
now converts skinned props as static meshes. Vault 111: 215 of 217 models convert (the 2 left are pure glass/glow). A railing
blocked the player on a walk test, so prop collision holds.
