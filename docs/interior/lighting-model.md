# Interior lighting: Skyrim's model, Starfield's, and how the converter should map one onto the other

Started 2026-11-21. Owner, with Skyrim / Starfield screenshot pairs of the inn, its stairs, a candle table, Faendal's
and Alvor's houses and a basement: "its inconsistently lit. If we brighten or darken it everywhere it wont look like
skyrim because like, the inn is super dark but faendals room looks less dark ... Its just not being lit the same", and:
"we need to figure out skyrims lighting vs starfields, so that the converter when expanded gets the lighting right for
other rooms we haven't seen yet". Goal: a rule that lights any converted room the way Skyrim does, with one global
brightness for taste, not per-room tuning.

## What the build does now (verified, the code)
- Every Skyrim light becomes a copy of LGT_Fire_Cauldron (3197A6, 4000 lm, 8 m) with Skyrim's radius and colour and
  lumens = 4000 x clamp(LIGHT_POWER 2 x max(fade, 1) x max(1, (radius / 8 m)^2), 1, 16): a candle's light and a room
  fill light both get at least 8000 lm; the largest is capped at 64000 lm (PluginSpike SkyrimLight).
- Lights within LIGHT_MERGE_M (1 m) of an already placed one, on every axis, are dropped (PluginSpike cell loop).
- The cell: one lighting template for every room (ship interior 006658), one image space (1C6C37), and with
  CELL_AMBIENT skyrim its AmbientColor / DirectionalColor = Skyrim's single ambient / directional colours. Skyrim's six
  directional ambient colours, the directional light's rotation and fade, and per-reference fade offsets (XLIG) were
  not read before this change.

## Skyrim (vanilla SSE)
- **Point lights (verified):** Community Shaders' package/Shaders/Lighting.hlsl, the vanilla loop (without its light
  limit fix): `intensityFactor = saturate(dist / radius); if 1: skip; intensityMultiplier = 1 - intensityFactor^2;
  lightColor = PointLightColor * intensityMultiplier`, then the usual N.L. No inverse square; nothing past the radius.
- **Fade (supported):** the engine fills PointLightColor with colour x fade (the light limit fix's own path multiplies
  light.fade explicitly). The reference's XLIG "Fade 1.35+/-" offset (verified layout, xEdit) adds to it (supported).
- **Gamma space (verified for the vanilla path):** no linearisation of light or albedo; Community Shaders' linear
  lighting is an option of its own. So Skyrim's light, as seen, is light^2.2-ish in linear terms.
- **Ambient (verified that it is a 3 x 4 matrix on (N, 1)):** `DirectionalAmbient` in Lighting.hlsl. Built from the
  cell's six directional ambient colours (XCLL offsets 40 - 60, verified layout: xEdit wbDefinitionsTES5 /
  wbDefinitionsCommon wbAmbientColors; a lighting template's are in its DALC). How the six become the matrix:
  supported hypothesis, lightmodel.ambient_fit (constant = mean, N.x weight = (X+ - X-) / 2, ...).
- **Directional light:** XCLL directional colour x directional fade x N.L; its direction from the XCLL rotations
  (XY heading, Z elevation: hypothesis).
- **Inheritance:** XCLL Inherits flags (verified list, xEdit): 0x1 ambient, 0x2 directional colour, 0x20 directional
  rotation, 0x40 directional fade, ...; the six directional ambient colours follow 0x1 (supported).

## Starfield
- Physically based: lumens, metres, a falloff exponent, auto-exposure through the image space. **The falloff curve is
  unresolved.** Fallout 4's CK documents "Falloff Exponent: increases the intensity near the emitter; can achieve an
  inverse square falloff" (falloutck.uesp.net Light). Until measured, fo4sf.lightmodel uses H1, a windowed inverse
  square (E = lm / (4 pi d^2) x (1 - (d / R)^4)^2), as in other physically based engines.
- What a cell's AmbientColor does in Starfield, in what units, is unresolved too.

## First finding (worked, 2026-11-21): the falloff shape is less of the difference than it looks
Skyrim's light is gamma space. Linearised, (1 - (d / r)^2)^2.2 falls off nearly as fast as an inverse square: one
20 m light 4 m and 15 m from two objects gives near / far = 63 in Skyrim (linear) and 96 under H1, half a stop apart
(tests/test_lightmodel.py). So "bright at the source, dark further away" is not mainly the curve; the candidates for the
room-to-room difference are the parts we do not carry over: the six-colour ambient and the directional light (a big
share in a hall?), lights merged away, and the lumen rule (every light at least 8000 lm, the big ones capped). The
audit below measures each per room.

## The audit (scripts/interior/light_audit.py, read-only)
Per cell of the batch: Skyrim's lights (in use / disabled / off by default, radius, colour x fade), ambient, six
directional ambient colours, directional light, what comes from the template; the lights our build places, their
lumens, the Skyrim lights the merge drops; at the top of every placed object, Skyrim's light split into ambient /
directional / point-light shares, and ours / Skyrim's (point lights, H1) as a room median against the batch's
("vs batch", stops) and its spread inside the room (p90 / p10, stops). Output: the summary and
<work>\light_audit.json.

## Next: measure Starfield's falloff (calibration cell, designed, not built yet)
A test cell with one light of known lumens and radius over a row of identical floor tiles at 0.5 - 8 m, and, outside
its radius, a "ladder": the same tile under small lights at 0.5 m with lumens stepping by half stops around what H1
predicts for each distance. In one screenshot from above (tfc, tm), the ladder tile that matches each row tile in
brightness gives the true falloff at that distance within half a stop, whatever the tonemapping does (matching equal
brightness needs no inverse tonemap). Repeated with falloff exponent 1 and 2. Then the converter's rule: per room,
solve each light's lumens (and an ambient fill) so ours matches Skyrim's linearised light at sample points, with one
global constant tuned once against the owner's same-spot screenshot pairs.
