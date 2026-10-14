# More interiors: Vault 81 and the Red Rocket cave (2026-10-08)

The pipeline is not specific to Vault 111. `dotnet/Fo4Export` exports any interior, `scripts/convert_batch.py --cell-json`
converts the union of models, and the plugin writer takes several cell files. One plugin now holds `FO4Port_Vault111Cryo`,
`FO4Port_Vault81` (3,289 refs) and `FO4Port_RedRocket01` (the mole-rat cave under Red Rocket, 590 refs): **932 models,
508/512 materials, about 2.5 minutes**. Screenshots: [Vault 81](../media/vault81-booth.jpg), [Red Rocket cave](../media/redrocket-cave.jpg).

## Fixes found by playing the cave

1. **"Snow" on rock = mirror-smooth material.** FO4 cave rock gloss maps are 255 everywhere; the `.bgsm` scales them by a
   *smoothness* scalar (0.5 here) and a *specular multiplier* (0.14-0.4). Both are read from the lighting block after the
   nine texture strings (offsets +28 / +32, verified on PatioFurniture: mult 0.8, smoothness 1.0). Roughness is now
   `255 - G * smoothness * sqrt(spec_mult)`.
2. **Black slabs = missing alpha cutouts.** Roots and foliage use alpha test. Starfield does it with an opacity texture in
   `MRTextureFile` slot 2 plus `BSMaterial::AlphaSettingsComponent {AlphaTestThreshold, HasOpacity}` on the root object (as in
   vanilla `GrassTropicalPlant01.mat`). The diffuse alpha becomes a BC4 opacity map; threshold = BGSM alpha ref (byte 41) / 255.
   73 opacity maps in these three cells.
3. **Alpha-blended overlay/decal shells** (`...Alpha.BGSM`, BGSM byte 32 set) are skipped until blending is supported.
4. **Hanging roots blocked the player** (user play-test): vegetation (`landscape\trees|plants|grass`, roots, cobwebs, vines)
   no longer gets collision. Walk test: 4 s through the roots, uphill, no fall-through.

## Vault 81 tour and doors (2026-10-08, later)

Full walk through `FO4Port_Vault81`: riveted panel walls, the security booth, shelving, crates and dirt mounds are all textured;
nothing broken stood out ([booth](../media/vault81-booth-interior.jpg), [walls](../media/vault81-walls.jpg),
[cave roots](../media/redrocket-cave-roots.jpg)). Fallout 4 doors are converted as static meshes (they cannot open yet), so they
no longer get collision: a closed door is now see-through to the player rather than a wall.

## Automated collision map (2026-10-08)

New tool `scripts/game/probe.ps1` teleports the player 1.5 m above 30 floor pieces spread over Vault 81 and reads the landing
height back by OCR. Result: **28 PASS, 2 HELD, 0 falls through** ([map](../media/vault81-collision-map.png)). The two HELD are
expected: one is the top of a stair run, the other a floor mat sitting on a higher surface (the player landed 1.2 m up on something
solid). See `scripts/game/README.md`.

## Five more interiors (2026-10-08)

Vault 114, the Prydwen (hull 01), Hotel Rexford (Goodneighbor), Boston Public Library and Parsons State asylum now load from the
same plugin (8 cells, 2,547 models, 1,001/1,007 materials, ~20,000 placed objects, ~6.5 min conversion). Toured in game:
[Prydwen](../media/prydwen.jpg), [Hotel Rexford](../media/hotel-rexford.jpg), [library](../media/boston-public-library.jpg),
[Parsons](../media/parsons-state.jpg), [Vault 114](../media/vault114.jpg).
Visible problems: Parsons' wallpaper shows black crack overlays drawn opaque (damage overlay alpha); Hotel Rexford has pink-purple
walls (likely FO4 greyscale-to-palette materials); scenes are bright overall; huge pieces (Prydwen hull, subway platforms) have
incomplete collision (box cap; see manifest `floor_dropped`).
