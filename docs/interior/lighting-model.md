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

## Audit results, Riverwood (owner, 2026-11-21 12:18; ours under H1)
| cell | Skyrim lights | Skyrim light at objects p10 / med / p90 | ambient share | ours vs batch | spread in room |
|---|---|---|---|---|---|
| AlvorsHouse | 6 | 0.15 / 0.68 / 1.38 | 0.12 | +0.11 st | 2.6 st |
| FaendalsHouse | 5 | 0.21 / 0.77 / 1.24 | 0.11 | +0.71 st | 2.1 st |
| GerdursHouse | 6 | 0.42 / 0.65 / 1.28 | 0.11 | -0.23 st | 2.8 st |
| RiverwoodTrader | 5 | 0.47 / 0.78 / 1.54 | 0.10 | -0.12 st | 2.4 st |
| SleepingGiantInn | 8 | 0.11 / 0.31 / 0.84 | 0.20 | +0.15 st | 2.0 st |
| SvensHouse | 6 | 1.47 / 2.04 / 2.53 | 0.04 | -1.84 st | 3.5 st |

Read (verified from the output unless marked):
- Every room takes the same lighting template: ambient 45,48,48, the same six directional ambient colours, directional
  fade 0 (no directional light). Ambient is 4 - 20 % of the light; it does not make rooms differ.
- Every light is 512 units (7.3 m) except one 65.7 m light in Sven's house. Skyrim's brightness (colour x fade) runs
  0.85 - 2.91; ours are all 8000 lm, the 65.7 m one 64000 (the 16x cap; uncapped the rule would give 135x): Skyrim's
  differences between lights are flattened, and Sven's house is 1.8 stops darker than the rest relative to Skyrim.
- **Skyrim's own light on the inn's objects is half the houses' (median 0.31 against 0.65 - 0.78), yet the owner's
  Skyrim screenshot of the inn is bright.** Relative to Skyrim, ours puts the inn where the houses are (+0.15 st): we
  reproduce Skyrim's raw light about right (under H1), but Skyrim then brightens the dark inn and Starfield does not.
  Supported hypothesis: Skyrim's HDR eye adaptation (IMGS HNAM eye adapt strength / white; the cell's XCIM image space)
  raises a dark room's exposure more than our Starfield image space does. The audit now prints each cell's image space.
- Inside each room ours / Skyrim's spreads 2 - 3.5 stops: under H1, ours is much brighter right under a light and
  darker away from it (the owner, 11-16: "very bright right at the source").

## Skyrim's image space and eye adaptation (owner's second audit run, 12:23; Community Shaders ISHDR.hlsl)
- Every Riverwood room uses FarmInteriorIS (059B60): eye adapt speed 15, eye adapt strength 1.5, white 1.0, bloom 4;
  cinematic saturation 1.05, brightness 1.15, contrast 1.2; tint 5 % of (0.63, 0.39, 0.04) (verified, the audit).
- ISHDR.hlsl, the vanilla blend (verified): the frame is multiplied by avgValue.y / avgValue.x before the tonemap
  (avgValue.x = the eye's adapted average luminance, smoothed over time by the DOWNADAPT pass at the image space's
  adapt speeds; how the engine sets .y from eye adapt strength: unresolved). Reinhard with white point p:
  L (L p + 1) / (L + 1), which at p = 1 (FarmInteriorIS's white) is L: no highlight compression. Then saturation,
  5 % tint, x 1.15, contrast 1.2 about the average.
- Screens (owner's six pairs, 12:03; mean linear luminance of the middle of each frame, HUD cropped; framing differs
  a little between the games, so a stop or so is noise):

| scene | Skyrim geo-mean | Starfield geo-mean | Starfield vs Skyrim |
|---|---|---|---|
| inn, candle table | 0.007 | 0.0003 | -5.0 st |
| inn hall | 0.020 | 0.0008 | -4.7 st |
| inn stairs | 0.005 | 0.0002 | -4.6 st |
| basement | 0.010 | 0.0025 | -2.0 st |
| Faendal's bedroom | 0.011 | 0.006 | -0.9 st |
| a house with a hearth | 0.018 | 0.011 | -0.7 st |

- Read: on Skyrim's screens the inn is as bright as the houses although its raw light is half (mean linear 0.22 vs
  0.51 - 0.62): Skyrim's eye adaptation lifts it (supported). In Starfield the inn is 4 - 5 stops under Skyrim and the
  houses under one: Starfield does not adapt like Skyrim, and the inn loses about 2.5 stops more than the 1.3 stops
  adaptation explains - something in the big hall our model misses (the falloff at hall distances under H1, or what
  the screen sees: walls and pillars far from lights, against object tops sampled). Both need the measurements below.
- Starfield's image spaces are reflection blobs (Mutagen: IMGS = REFL / RFDP / RDIF), so their exposure settings are
  unresolved: SfInspect imgsdump writes them out for reading.

## Starfield's image space settings (owner's imgsdump, 12:30; names verified from the blobs' string tables)
TESImageSpace -> ImageSpaceSettings: OverallBlendAmount, UseOutdoorExposure; ExposureSettings: CameraExposureMode
(the strings AutoExposure, FixedValue, CameraExposure appear: three modes), AutoExposureSettings (EnableCompensationCurve,
ExposureCompensationCurve as a BSFloatCurve, ExposureMin, ExposureMax, AdaptSpeedDown, AdaptSpeedUp,
LuminanceHistogramSettings: IgnoredDarksPercentile, IgnoredBrightsPercentile), FixedValue (Exposure),
CameraExposureSettings (Aperture, Time, ...); SunAndSkySettings (IndirectLightingSkyTargetEv100, SkyLightingMultiplier,
...); BloomSettings; CinematicSettings (Saturation, Brightness, Contrast, TintColorValue, FadeColorValue, UseOutdoorLUT,
ColorGradingTexture, ColorGradingAmount); DepthOfFieldSettings. 10489 cells use DefaultImagespacePackin (06AD68, an
RDIF diff on DefaultImageSpace 000167); LGT_NoLut (ours) is a full REFL, used by 25 vanilla cells.
Values (verified, the owner's 15 blobs decoded by scripts/interior/sf_imagespace.py, every OBJT read to its last byte):
| image space | exposure mode | fixed EV | auto min / max | tone map | LUT |
|---|---|---|---|---|---|
| LGT_NoLut 1C6C37 (ours) | FIXED | 5.0 | 4 / 6 | ACESReference | ColorLUT |
| LGT_LUT_Int_Gen_v01..v05_curve (vanilla interiors) | FIXED | 3.5 | 4 / 6 | Hable (override) | LGT_LUT_Int_Generic_0x_curve |
| LGT_LUT_Int_AkilaCity_curve | FIXED | 3.5 | 5 / 7 | Hable | its own |
| DefaultImageSpace 000167 | AUTO | (5.0) | 4 / 6 | Hable | - |
| DefaultImageSpaceGenLUT 24A02A | AUTO | (15) | 13 / 15 | ACESReference | NaturalColorLUT |
**Our rooms' exposure is fixed: Starfield never brightens the dark inn** (verified). Vanilla interiors are fixed too,
at EV 3.5 (1.5 stops brighter than ours) with a Hable curve and a LUT.

## The rule now (2026-11-21): Skyrim's eye adaptation baked into each room's lights
- fo4sf.lightmodel.room_mean_linear: the room's mean Skyrim light (ambient + directional + point lights, luma, clipped
  at 1, linearised) at every placed object; adaptation_scale = (ADAPT_REF 0.55 / mean)^ADAPT_STRENGTH 1, within 1/8 - 8.
  ADAPT_REF: the Riverwood houses' mean (0.51 - 0.62), which sit within a stop of Skyrim's screens as built.
- skyriminterior.plugin_cell writes it to the cell JSON ("light_scale", "skyrim_mean_light"); PluginSpike multiplies
  the room's lumens by it (LIGHT_ADAPT 0 in lighting.json turns it off), one light base per room scale.
- The lumen cap goes from 16x to LIGHT_MAX_SCALE 256x (Sven's 65.7 m light: 135x by the rule).
- Expected (the audit's model): the inn's lights x2.5 (+1.3 stops), Sven's house x0.55 with its big light uncapped,
  the other houses within 0.2 stops of today. On the owner's screens the inn is about 3.9 stops darker than the houses
  relative to Skyrim: this explains 1.3 of them (supported hypothesis: full adaptation). The rest waits on the falloff
  measurement. The audit prints "before" (cap 16, no adaptation) and "now" per room against Skyrim's adapted screen.
- Owner's build (12:52, verified from its log): Alvor x1.086, Faendal x0.966, Gerdur x1.044, Trader x0.888, inn x2.498,
  Sven x0.552; 14 Starfield light bases.
- Owner's screens after it (12:58; same measure as the 12:03 table, framing close):

| scene | before | after | dark end (p10) | bright end (p90) |
|---|---|---|---|---|
| inn hall | -4.7 st | -2.6 st | -5.8 st | -1.1 st |
| bedroom (the house with the 65.7 m light: Sven's, supported) | -0.9 st | +1.1 st | -1.0 st | +2.1 st |
| inn stairs | -4.6 st | -4.5 st | -4.7 st | -1.6 st |
| basement | -2.0 st | -1.9 st | -5.1 st | +0.7 st |

  Read: the inn came up 2.1 stops (1.3 expected); the bedroom moved +2.0 (the model: +2.2 from the uncapped big light x
  the 0.55 adaptation) and now overshoots by a stop at its bright end. What stays: **places our lights do not reach at
  all** - the stairs, the dark end of every room (5 - 6 stops under Skyrim), while bright ends are within 1 - 2 stops.
- Why (verified for Skyrim, Lighting.hlsl's vanilla loop): `if (lightIndex < numShadowLights) lightShadow *=
  shadowColor[...]` - only the few shadow-casting lights are blocked by geometry; every other Skyrim light shines through
  walls, floors and pillars to its radius. Skyrim's stairwell is lit by the hall's lights through its walls. Whether our
  Starfield lights cast shadows (and so stop at walls) is unresolved: SfInspect lightstats shows how Starfield's lights
  are set (type Omnidirectional / ShadowSpotlight / NonShadowSpotlight, flags incl. DisableDistanceAttenuation,
  UseAdaptiveLighting with its EV100 range, RadiusFalloutExponent).
- A Skyrim light whose radius dwarfs its room (Sven's 65.7 m) acts as an even fill there; as a Starfield point light it
  floods the area near its position. Candidate: such lights become ambient / fill instead.

## Starfield's lights (owner's SfInspect lightstats, 13:03; field layout verified against xEdit wbDefinitionsSF1 LIGH DAT2)
- 1575 LIGH: types Omnidirectional / Shadow Spotlight / NonShadow Spotlight only. Omni "shadow" lights carry the
  undocumented flag 0x400 (xEdit "Unknown 10": GenLightOrangeShadow1) while the "_NS_" (non-shadow) omnis and our base
  LGT_Fire_Cauldron (3197A6: Omnidirectional, flags 0x1, 4000 lm, 8 m, falloff 2, radius falloff exponent 4, not
  adaptive) do not: supported hypothesis that our lights are non-shadow omnis, so not blocked by walls - the shadow
  question does not explain the unlit corners.
- Every vanilla light has RadiusFalloutExponent 4 (fits H1's (1 - (d / R)^4) window, supported). 3197A4
  LGT_Fire_Candle_Interior: 3000 lm, 2.5 m. Adaptive lights (UseAdaptiveLighting, the space-station / ship sets) pin
  EV100 3.5; ours (Cauldron) are not adaptive: their lumens are absolute.
- So the remaining candidate for the unlit corners: **ambient**. Skyrim's ambient lights every surface; our cells give
  Starfield a black environment cube (PluginSpike: a default sky "washed everything out" - so the cube does light the
  room, supported) and the cell's AmbientColor, whose effect in Starfield is unresolved.

## Skyrim's ambient as the cell's environment cube (2026-11-21)
- make_skyrim_interior batch writes <work>/convert/textures/skyrim/interiorambient/<cell>.dds (packed by the install):
  a cube map, R16G16B16A16_FLOAT, full mips, every face one colour = Skyrim's six directional ambient colours
  averaged, linearised, x the room's adaptation (light_scale), x ENV_AMBIENT_SCALE (38 = 1.2 x 2^5: what EV100 5 maps
  to white; a first guess, riverwood_doors -AmbientScale). PluginSpike sets the cell's environment map to it (ENV_AMBIENT
  0 in lighting.json keeps the black cube). One colour on every face until the D3D face order against Skyrim's
  X+ .. Z- is checked (Riverwood: Z+ 21 vs Z- 68, the sides 40 - 50).
- To check in game: the stairs and the dark corners lift, the lit parts stay; if nothing changes, the cube does not
  give diffuse light (then: fill lights).

## Next: measure Starfield's falloff (calibration cell, designed, not built yet)
A test cell with one light of known lumens and radius over a row of identical floor tiles at 0.5 - 8 m, and, outside
its radius, a "ladder": the same tile under small lights at 0.5 m with lumens stepping by half stops around what H1
predicts for each distance. In one screenshot from above (tfc, tm), the ladder tile that matches each row tile in
brightness gives the true falloff at that distance within half a stop, whatever the tonemapping does (matching equal
brightness needs no inverse tonemap). Repeated with falloff exponent 1 and 2. Then the converter's rule: per room,
solve each light's lumens (and an ambient fill) so ours matches Skyrim's linearised light at sample points, with one
global constant tuned once against the owner's same-spot screenshot pairs.

## Owner's screens with the ambient cube (13:17, all in the inn; same measure, vs Skyrim)
| scene | after the bake | with the cube | dark end | bright end |
|---|---|---|---|---|
| inn hall | -2.6 st | -1.7 st | -4.2 | -0.7 |
| inn side room | - | +0.4 st | -1.0 | +2.2 |
| inn bedroom | +1.1 st | +1.2 st | -0.1 | +2.1 |
| inn stairs | -4.5 st | -1.7 st | -4.8 | -0.2 |
| inn basement | -1.9 st | -0.6 st | -5.2 | +1.7 |
- Verified: the environment cube lights diffuse surfaces (the stairs +2.8 stops, the hall +0.9, the basement +1.3).
- The owner: the "bedroom" is the inn's, not Sven's (correcting the 12:58 reading). So inside one cell the small rooms
  are 1 - 2 stops over Skyrim and the hall / stairs under: no per-cell factor can fix that. Skyrim adapts to what the
  camera sees (ISHDR: the frame's own average), so its inn bedroom is darkened and its hall brightened per view.
- Vanilla image spaces all use AmbientOcclusion 7 and indirect diffuse 1 (not ours to change yet).

## Per-view exposure (2026-11-21): Starfield's auto exposure in a copy of LGT_NoLut
- sf_imagespace.patch rewrites leaf fields of a reflection blob (enum strings may change length; OBJT size follows;
  tested on a synthetic blob, checked on the owner's LGT_NoLut: only the three fields change). make_skyrim_interior
  batch --exposure auto reads LGT_NoLut's REFL from Starfield.esm, sets EXPOSURE_MODE_AUTO and ExposureMin / Max (EV100,
  default 3 .. 6.5: up to 2 stops brighter or 1.5 darker than the fixed 5), writes <work>/convert/
  imagespace_skyrim_adapt.bin; PluginSpike adds it as FO4Port_IS_SkyrimAdapt and every cell uses it. The per-room
  light scale is then 1 (skyrim_mean_light still recorded). riverwood_doors -Exposure auto (default) / fixed.
- Unresolved: Starfield's auto-exposure key (where it puts a room's average) and what its compensation curve does; the
  range limits bound it either way. Expected: inn hall / stairs up, inn bedroom / side room down, houses near today.
- Still open: the bright ends right under lights (+1.7 - 2.2 stops: inverse square near a light against Skyrim's flat
  (1 - (d/r)^2)), the falloff measurement.

## Owner's screens with auto exposure EV100 3 .. 6.5, compensation 0 (13:28; vs Skyrim; "fish on the wall" = Faendal's)
| scene | fixed + bake | auto | dark end | bright end | contrast (sd of log2 luminance) Skyrim / ours |
|---|---|---|---|---|---|
| inn hall | -1.7 | -0.5 | -2.0 | +0.6 | 1.5 / 2.6 |
| inn bedroom | +1.2 | +2.4 | +1.0 | +3.2 | 1.8 / 3.0 |
| inn stairs | -1.7 | +0.3 | -1.2 | +3.2 | 1.2 / 2.5 |
| inn basement | -0.6 | +0.7 | -1.2 | +2.7 | 1.4 / 2.9 |
| inn side room | +0.4 | +0.4 | -1.0 | +2.2 | 1.7 / 2.8 |
| Faendal's house | - | +2.5 | +1.9 | +2.8 | 1.6 / 2.0 |
- Read: every inn view moved by about the same amount (+1.2 .. +1.3 after the bake's -1.3 is taken out: +2.5 stops of
  exposure), the hall-to-bedroom gap unchanged (2.9 stops): **the auto exposure sat at its brightest limit (EV 3) in
  every view**, so no per-view adaptation happened; its key is brighter than Skyrim's.
- The compensation curve (USER chunk, a BSFloatCurve: input -3 .. 11, value -3 .. 3; LGT_NoLut has no controls, so its
  DefaultValue 0 applies; DefaultImageSpace has two controls at +0.5): sf_imagespace.patch now edits USER fields.
  Next build: compensation -3 (supported hypothesis: EV offset, negative = darker), range EV100 1 .. 8.
- Contrast: ours 2.0 - 3.0 against Skyrim's 1.2 - 1.8 in every view: hot spots under lights, darker corners (inverse
  square near a light; Starfield's AO 7). Colour: ours redder in the inn (r share 0.47 - 0.53 vs 0.35 - 0.47): the 95
  mired warm shift on lights already warm. Both next after the exposure.

## Owner's screens with compensation -3, range EV100 1 .. 8 (13:39)
| scene | comp 0, range 3 .. 6.5 | comp -3, range 1 .. 8 | change |
|---|---|---|---|
| inn hall | -0.5 | +2.2 | +2.7 |
| inn bedroom | +2.4 | +3.2 | +0.8 |
| inn stairs | +0.3 | +2.8 | +2.5 |
| inn basement | +0.7 | +3.5 | +2.8 |
| Faendal's house | +2.5 | +2.8 | +0.3 |
- Verified: compensation -3 brightened, so it is an EV100 offset (negative = lower EV = brighter), as EV100 itself.
- The views now moved by different amounts: the dark ones +2.5 - 2.8, the bright ones +0.3 - 0.8; the spread across
  views fell from 3.0 stops to 1.3 (Skyrim's per-view adaptation evens views the same way). Level: 2.9 stops over.
- Next: compensation 0, range 1 .. 8 (expected about 2.9 stops darker if the offset is linear: near Skyrim).

## Owner's screens with compensation 0, range 1 .. 8 (13:47; vs Skyrim)
| scene | comp -3 | comp 0 | dark end | bright end | contrast Skyrim / ours |
|---|---|---|---|---|---|
| inn hall | +2.2 | +2.1 | +0.9 | +2.8 | 1.5 / 2.1 |
| inn side room | - | +3.7 | +2.4 | +3.8 | 1.7 / 2.2 |
| inn bedroom | +3.2 | +2.8 | +1.6 | +3.4 | 1.8 / 2.8 |
| inn stairs | +2.8 | +2.4 | +1.4 | +3.7 | 1.2 / 1.7 |
| inn basement | +3.5 | +3.1 | +2.0 | +3.9 | 1.4 / 2.2 |
- Correction to the 13:39 reading: compensation -3 vs 0 differ by 0.3 stops at most - the curve's DefaultValue has no
  real effect (it has no controls; supported). What brightened the 13:39 build was the range: ExposureMin 3 -> 1.
- Supported hypothesis: Starfield's auto-exposure key is brighter than these rooms, so dark views sit at ExposureMin;
  brighter views partly adapt (hall-to-bedroom gap 0.7 stops now against 2.9 with the fixed exposure and per-room
  bake). ExposureMin is the level: next 4 (3 stops darker for views at the limit).
- Colour now close to Skyrim in the hall, bedroom, basement (red shares within 0.03); contrast still higher than
  Skyrim's everywhere (the falloff / hot spots near lights, next).
- One light base per Skyrim light kind now (4, was 14): with light_scale 1 the cells share bases.

## Owner's screens with ExposureMin 4, max 8 (13:56; vs Skyrim, all well framed)
| scene | EV min 3 (13:28) | EV min 4 | dark end | bright end | contrast Skyrim / ours |
|---|---|---|---|---|---|
| inn hall | -0.5 | -2.4 | -5.7 | -1.0 | 1.5 / 2.9 |
| inn bedroom | +2.4 | +0.8 | +0.1 | +1.3 | 1.8 / 2.5 |
| inn stairs | +0.3 | -2.5 | -4.8 | -0.8 | 1.2 / 2.6 |
| inn basement | +0.7 | -0.5 | -5.2 | +1.3 | 1.4 / 3.1 |
- Level: mean -1.2 stops (an ExposureMin near 3.4 would centre it). The real gap now is contrast: bright ends within
  -1 .. +1.3, dark ends 5 - 6 stops under. At the darker exposure ACES's toe crushes the shadows further (supported;
  Skyrim's Reinhard at white 1 has no toe) and the red share rises (hall 0.57 vs 0.47).
- Next: the fill (environment cube) x4: ENV_AMBIENT_SCALE / -AmbientScale 38 -> 150, ExposureMin kept at 4.

## Owner's screens with the fill x4 (AmbientScale 150, ExposureMin 4; 14:06; vs Skyrim)
| scene | overall | dark end | bright end | contrast Skyrim / ours | red share Skyrim / ours |
|---|---|---|---|---|---|
| inn hall | -0.6 | -1.0 | -0.2 | 1.5 / 1.8 | 0.47 / 0.50 |
| inn bedroom (two angles) | +1.4 .. +1.9 | +0.7 .. +1.2 | +1.8 | 1.8 - 2.2 / 2.2 | 0.45 / 0.47 |
| inn stairs | +0.7 | 0.0 | +1.8 | 1.2 / 1.6 | 0.35 / 0.36 |
| inn basement | +0.8 | +0.3 | +1.6 | 1.4 / 2.0 | 0.45 / 0.43 |
| inn side room (framing differs) | +1.8 | +1.3 | +2.3 | 1.7 / 1.9 | 0.37 / 0.44 |
- Verified: the fill closed the dark-end gap (5 - 6 stops -> within about 1) and contrast is within 0.1 - 0.6 of
  Skyrim's; colour within 0.03 red share except the side room.
- Left: small candle-lit rooms 1.5 - 2 stops over at their bright end while the big hall is at -0.2: light near a
  source too strong against far light (the falloff shape: H1 inverse square vs Skyrim's flat (1 - (d/r)^2)), the
  calibration cell's job. Defaults stand: AmbientScale 150, ExposureMin 4.
- Faendal's house, same build (owner 14:07): +1.8 overall, dark end +1.4, bright end +2.1, contrast 1.6 / 1.8, red
  share 0.43 / 0.48. The pattern across views: small rooms whose walls are 1 - 3 m from their lights (Faendal's, the
  inn bedroom, side room) +1.4 .. +1.9 everywhere in the view, the big hall -0.6. Supported: at short range our
  inverse-square lights are much stronger than Skyrim's flat (1 - (d/r)^2) curve relative to their light at 5 - 10 m,
  so the auto exposure (clamped at ExposureMin in every view, supported: views never darkened on their own) cannot even
  it out. The falloff calibration cell decides the per-light correction.

## The calibration cell (built 2026-11-21: scripts/interior/light_calib.py, riverwood_doors -LightCalib)
FO4Port_S2SLightCalib: 30 tiles of one converted Skyrim floor model (scaled to about 1.6 m), 10 m apart in a black
cell (fixed exposure LGT_NoLut EV 5, no environment light, no adaptation, template ambient only), each under its own
light (LGT_Fire_Cauldron copy, radius 8 m, white, no flicker, exact lumens via the cell JSON's calib_lumens). Rows 0 - 2:
the ladder, 2 m above, 4000 lm x 2^(k/2), k = -11 .. 6. Row 3: 4000 lm at 1, 1.5, 2, 3, 4, 6 m, falloff exponent 1
(ours); row 4: the same with exponent 2 (vanilla). analyze finds the 30 tiles in a straight-down screenshot, reads each
test tile's brightness off the ladder (equal brightness = equal light, whatever the tone curve) and prints
falloff(d) / falloff(2 m) against H1 and Skyrim. Known limits: specular highlights (light and camera both above),
the tile surface a few cm off the model origin (light heights measured from the origin).

## Calibration results (owner 2026-11-21 14:25 - 14:29; verified, three screenshots, one looking back from the north)
light_calib analyze on each (it finds the arrival tile and turns a view looking south round); falloff relative to 2 m:

| d (m) | shot 1 | shot 2 | shot 3 | model lm (1 - (d/8)^4) / (d^2 + 1.8) | Skyrim seen ((1 - (d/7.3)^2)^2.2, r 7.3) |
|---|---|---|---|---|---|
| 1 | 2.26 - 2.46 | 2.02 - 2.07 | 2.00 - 2.08 | 2.07 | 1.12 |
| 1.5 | 1.37 - 1.43 | 1.46 - 1.51 | 1.42 - 1.51 | 1.43 | 1.08 |
| 2 (self-check) | 1.03 - 1.08 | 1.02 - 1.04 | 1.04 - 1.09 | 1 | 1 |
| 3 | 0.58 - 0.62 | 0.50 - 0.53 | 0.47 - 0.49 | 0.53 | 0.73 |
| 4 | 0.32 - 0.35 | 0.28 - 0.30 | 0.27 - 0.30 | 0.31 | 0.50 |
| 6 | 0.13 | 0.10 - 0.11 | 0.11 - 0.12 | 0.105 | 0.10 |

- Starfield: E ~ lumens x (1 - (d / R)^4) / (d^2 + 1.8 m^2) (lightmodel.starfield_falloff). FalloffExponent 1 and 2 gave
  the same values (verified: rows 3 and 4 agree within the shots' spread).
- Against Skyrim's seen falloff, a Starfield light is about 2x too strong at 1 m relative to 4 m, matching the small
  rooms' +1.4 .. +1.9 stops against the hall.
- Fix (2026-11-21): per-light distance fit (lightmodel.distance_fit): lumens x g(D) / g(4 m), D = the median distance from
  the light to the room's objects in its radius, g = Skyrim's seen falloff / Starfield's. A light whose objects sit
  1.5 m away gets x0.41 (-1.3 stops); a hall light at 4 m x1. Clamped 0.25 .. 2; LIGHT_DISTANCE_FIT 0 in lighting.json
  turns it off; plugin_cell writes fit_scale / fit_distance_m per light. Expected: small rooms -1 .. -1.3 stops, the
  hall about unchanged. In game: pending.

## Distance fit in game (owner 2026-11-21 14:42, Faendal's house, same spot before / after)
- Before +1.8 stops vs Skyrim, after +1.5 (dark end +1.4 -> +1.2, bright end +2.1 -> +1.8). The fit lowered Faendal's
  lights by about 0.8 (median distances near 3 m: g(3) / g(4) = 0.83 for a 7.3 m light), and the view moved by about
  that: the exposure did not compensate, i.e. this view too sits at ExposureMin 4 (supported).
- Read across all runs: from ExposureMin 3 to 1 (13:28 -> 13:39) the bright views (Faendal, the inn bedroom) moved only
  0.3 - 0.8 stops while dark ones moved 2.5 - 2.8: the bright views were adapting, at about EV 2 - 2.6, and there sat
  about 2.5 stops over Skyrim. Starfield's auto exposure aims about 2.5 stops brighter than Skyrim's look, so with a
  minimum high enough to hold that down, every view is pinned and nothing adapts.
- The lever is the compensation curve. LGT_NoLut's curve has no controls (its DefaultValue changed nothing, verified);
  DefaultImageSpace 000167's has two (+0.5, verified). Now: our image space is a copy of DefaultImageSpace (AUTO), made to
  look like LGT_NoLut (no tone-map override, ColorLUT, bloom 4 / 4, grey tint), every curve control and the default set to
  ExposureCompensation (-2 first try; sign unresolved), range EV100 0 .. 10 so views adapt. sf_imagespace.patch edits
  LIST chunk entries ("LIST:BSFloatCurve::Control.Value").

## Auto exposure on DefaultImageSpace, compensation -2, range EV 0 .. 10 (owner 2026-11-21 14:51; vs Skyrim)
| view | before (EV min 4, LGT_NoLut) | now | dark end | bright end | contrast Skyrim / ours |
|---|---|---|---|---|---|
| inn hall | -0.6 | +2.2 | +2.5 | +1.9 | 1.5 / 1.2 |
| inn bedroom | +1.4 | +2.9 | +3.0 | +2.5 | 1.8 / 1.4 |
| Faendal's house | +1.5 | +2.4 | +2.8 | +2.2 | 1.6 / 1.3 |
- Verified: the views now adapt - their spread fell from 2.1 stops to 0.7 (the dark hall rose 2.8, Faendal 0.9).
- Level about 2.5 stops too bright. Either -2 pushed the wrong way (positive = darker) or the curve still does nothing
  and this is Starfield's own target; next build compensation +0.5 tells which (expected near Skyrim if a unit is a
  stop with positive = darker; unchanged if the curve is ignored - then Cinematic Brightness is the lever).
- Contrast now under Skyrim's (1.2 - 1.4): the fill (AmbientScale 150) is strong for adapted views; after the level.

## Compensation +0.5 (owner 14:55; vs Skyrim): the curve does nothing
| view | comp -2 | comp +0.5 | contrast Skyrim / ours |
|---|---|---|---|
| Faendal's house | +2.4 | +2.5 | 1.6 / 1.4 |
| inn hall | +2.2 | +2.1 | 1.5 / 1.2 |
| inn bedroom | +2.4 | +2.2 | 2.2 / 1.5 |
- Verified: the compensation curve has no visible effect (changes within 0.12 stops). The views adapt (spread 0.4 stops),
  2.1 - 2.5 over Skyrim: Starfield's own target. Next: Cinematic Brightness 0.25 (-2 stops if it scales linear light;
  sf_imagespace patches it; riverwood_doors -ExposureBrightness) and the fill 150 -> 75 (contrast under Skyrim's).

## Cinematic brightness 0.25, fill 75 (owner 16:12; vs the owner's Skyrim shots of the same spots)
| view | overall | dark end | bright end | contrast Skyrim / ours | red share Skyrim / ours |
|---|---|---|---|---|---|
| inn hall | -0.03 | +0.14 | -0.30 | 1.44 / 1.20 | 0.46 / 0.43 |
| inn bedroom (Skyrim from the doorway, a dark post in view) | +0.62 | +0.85 | +0.16 | 1.70 / 1.48 | 0.44 / 0.44 |
- Verified: Cinematic Brightness works as the level; with the auto exposure adapting per view the inn hall now matches
  Skyrim's level. These are the defaults (ExposureBrightness 0.25, AmbientScale 75, auto EV 0 .. 10).
- Left: contrast 0.2 - 0.25 under Skyrim's, the hall a little less warm, and the hot spots next to lights near walls
  (the near-field: next, the area-light test in the calibration cell).

## "Devoid of color and contrast" (owner 16:14): Brightness acts after the tone map
Measured (display values, middle of the frame): our brightest pixels stop at 0.48 (99.9th percentile; Skyrim 0.99), the
darkest sit higher (1st percentile 0.03 - 0.04 vs 0.016 - 0.027), the most saturated parts duller (90th percentile
saturation 0.39 - 0.47 vs 0.56 - 0.61). Verified reading: Cinematic Brightness scales the tone-mapped image, so 0.25
turns white into grey. Next: Brightness 1.0, the level from the auto exposure's metering instead (IgnoredDarksPercentile
85, IgnoredBrightsPercentile 5: it meters the 85 - 95 % band, about 2 stops above the middle in these scenes, so it
exposes about 2 stops darker before the tone map; vanilla 20 / 20). Supported hypothesis until the owner's screens.

## "Colors overall are different" (owner 16:17): Skyrim's final grade carried over
- Skyrim's interiors end with their image space's cinematic grade; Riverwood's FarmInteriorIS (verified, the audit):
  saturation 1.05, contrast 1.2, brightness 1.15, tint 5 % of (0.63, 0.39, 0.04) orange. We carried none of it, and our
  background light is Skyrim's ambient colour (45, 48, 48: cool grey), which Skyrim's orange tint warms.
- Starfield's image spaces (verified, 15 read): saturation / contrast / brightness 1 = neutral, tint w = amount (0 in
  all but LGT_LUT_Int_StarbornTemple, 0.26). make_skyrim_interior.grading_changes copies saturation, contrast and the
  tint (colour xyz, amount w) of the batch's most used Skyrim image space into our image space; not the brightness
  (after the tone map in Starfield). --no-skyrim-grading leaves it out. One image space for the batch for now; cells with
  other Skyrim image spaces (caves, castles) will want their own copies (open).
- Owner, 16:28: the grade is a filter on everything inside (a character's red hair changes walking in), not lighting.
  Decision: no screen filter by default (--skyrim-grading opts in). Interiors should share the exterior's colour
  pipeline (tone map, LUT, cinematic) and differ only in exposure; warmth comes from the lights' own colours (open:
  base our image space on the exterior's).

## Hot spots right at a light: light size (open, 2026-11-21)
- Owner: the wall behind a candle stand, the map under the chandelier: far too bright right at the light, the rest of
  the room right. Supported hypothesis: the shape of the falloff, not the level. Skyrim (1 - (d/r)^2) is nearly flat near
  a light (1 m vs 4 m, r 6 m: about 1.7x); Starfield's measured lm / (d^2 + 1.8 m^2) gives 6.4x. No single scale fixes
  both distances, and the distance fit (relative to 4 m) only moves the level.
- Test: the calibration cell's exponent-2 row (the exponent had no effect) became two rows of sphere lights (FLAD
  AreaLight, Type Sphere, radius 0.5 and 1.5 m; units supported hypothesis: metres). If a size flattens the curve near
  the light, the converter sizes each light from Skyrim's data by rule; if not (unresolved), the alternatives are a
  near-field cap by splitting a light, or moving its origin.
- Exposure is unchanged by owner's choice ("leave it like this for now", 16:53).
