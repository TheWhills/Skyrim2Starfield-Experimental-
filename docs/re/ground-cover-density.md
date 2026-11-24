# Where Starfield grows ground cover (GCVR) and why it ignored our terrain (2026-11-24, Claude)

Starfield 1.16.244, `Starfield.exe` MD5 `0a73ecdc1d54b14a91818cddeb03aa9e`, image base 0x140000000. Analysed in the
owner's Ghidra 12.1 project (program `Starfield.exe.1`, auto-analysis with RTTI names; same MD5 as the installed exe)
with `scripts/re/ghidra_query.py` (headless, read-only; ReVa was not running). Addresses are virtual addresses in that
build. Labels: **verified** = read from the decompiled code (and, where noted, matching the owner's in-game tests);
**supported hypothesis** = inferred from the code with one step not read; **unresolved** = not traced.

## Answer in short

* **Grass does not read density maps.** The density maps (`<block>_<mask>.dds`, `BSProcGen::DensityMapDB`) are read
  by the `GetBiomeMaskValue` condition function (0x140bf45f0), not by the grass code. No function on the grass path
  touches the DensityMapDB. **verified** for every function traced (list below; the unopened callees are terrain
  height / normal and noise helpers).
* **Grass weights come from our BTD.** Per sample, the grass code reads the quadrant's texture bytes and the five
  3-bit alphas (the same data the renderer uses) and blends them. **verified**
* **Only palette entries with a GCVR grow grass, and on an overlay only the `LDefault...` mask placeholder textures
  get one.** The overlay's LTEX table is merged into the planet's terrain palette. A texture gets ground cover only if
  it is one of Starfield's per-mask placeholders (`LDefault006Base`, `LDefault005Flow`, `LDefault004FlatOut`,
  `LDefault003FlatIn`, ...). The biome under the overlay then replaces that entry's LTEX **and** GCVR with its own for
  that mask. Our Skyrim textures never get a GCVR. **verified** (code); the biome choice is a **supported hypothesis**.
* **Byte 6 is a sixth layer that only gets the leftover weight.** The grass sampler reads quadrant bytes 0, 1, 2, 3,
  4 and 6. When all of 0..4 are set, byte 6's texture is the last layer and gets `prod(1 - a_i)` over the five alphas.
  So it is 0 wherever any layer is at 7/7 and positive only where layers blend. That is exactly the owner's
  "edges only, never inside a texture at 7/7, nothing in a uniform patch at 7 or at 3" pattern. **verified**
* **Recipe:** paint the LDefault placeholders as ordinary layers (with Skyrim's alphas) where Skyrim has grassy
  ground, and set the biome's per-mask slot to {converted Skyrim texture, its GCVR}. This is data only, but limited to
  7 grass textures per overlay. The exact route with no limit is a small SFSE hook that gives each Skyrim LTEX its own
  GCVR in the overlay palette (details under Q5).

## Q1: 0x140bf45f0 and the mask-name table

`FUN_140bf45f0(ref**, u32 masks, u8 mask3, float* out)` is the **`GetBiomeMaskValue` condition function**
(**verified**: its only references are data, 0x1486187ac and a table filled by FUN_1400bfd90; its log string is
`"GetBiomeMaskValueConditionFunction : mask(%u,%u,%u), cellIndex(%i,%i) >> %0.2f"`). It is not a grass function.
What it does:
1. Takes the subject's x / y, multiplies by 0.01 (DAT_144f03eec = 0.01) and floors: a 100 m **cell index**.
2. Maps the cell to the planet grid (`FUN_14078d660` / `FUN_14078d4b0` on the planet manager `DAT_145fd9c30`;
   grid layout at +200, or +0x1c0 when `*(mgr+0x20) == 3`).
3. Looks the cell up in the planet's **procedural block grid** (`*(*(mgr+0x120)+0x10)`: origin from FUN_1409870d0,
   width/height at +0x48/+0x4c, block pointers at +0x20). A virtual call (+0x10) on the grid cell lists the
   **source blocks** covering it.
4. For each block and each of up to 3 masks (bytes of the condition parameters, index < 7): it builds the density-map
   key (`FUN_1407a7a70`, Q2), fetches it from the DensityMapDB (`FUN_1427b3930(DAT_1461e1dc0+0x10, +0x40, ...)`),
   checks size = block cells x 100 (else logs `"ERROR: Size of density map %s does not match block %s ..."`), and
   samples byte `[(x - (blockX - originX)*100) * height + (y - ...)]`. It adds `byte * DAT_144f03e90` to the result.
5. Averages over the blocks found.

Mask names: the pointer table **0x144a57018** (7 entries, **verified**): 0 `Base` (0x144cb0298), 1 `Flow`
(0x144cb0f50), 2 `FlatOuter` (0x144d60328), 3 `FlatInner` (0x144d60348), 4 `Talus` (0x144d60354), 5 `Solid`
(0x144d60334), 6 `Path` (0x144c22010). Users: this function, `FUN_140794510` (slot of an LDefault texture, Q4) and
`FUN_140794170` (`Path` slot = LDirtFootprints01). The engine's 7 biome slots use this order.

## Q2: density-map names and lookup

* Key: `FUN_1407a7a70(out, block, maskName)` splits the **block's name** (`*(block+8)`, a path-like string) into
  folder and file and formats `"%s\\%s_%s.dds"` (or `"%s\\%s.dds"` without a mask), e.g. `newatlantis\
  newatlantis01_FlatOuter.dds`. `FUN_1427db100` turns it into a resource ID. The `textures\terrain\` root comes from
  the DB traits: **supported hypothesis** (it matches the vanilla archive paths; that function was not opened).
* DB: `BSResource2::DB<BSProcGen::DensityMapDB::DBTraits, DBResourceStreamPolicy>` (vtable 0x144d9a428), loaded as a
  dependency of `BGSPlanet::BaseProcGenDB` (RTTI `FunctorWithDependenciesNode<...DensityMapDB...BaseProcGenDB>`,
  0x144b3d138). Keyed by **procedural source block**, not by world, BTD or biome. **verified**
* Expected size: `blockCellsX * 100` by `blockCellsY * 100` px (block +0x28 / +0x2c are cell counts). **verified**
* Overlays have `"OverlayMasks\\%s.dds"` (0x144b3ec88), loaded by `FUN_1407a7f60` (callers FUN_14079f860,
  FUN_140b0d6c0: planet block / overlay setup) with the world's name. Not used by grass (unresolved what for).
* So our maps `textures\terrain\sky_tamriel_<mask>.dds` matched no key: SKY_Tamriel is not a procedural block. And
  no grass code would read them anyway.

## Q3: the ground-cover placement code

The grass system is `BGSGrassManager` (vtable 0x144b2e698; singleton `DAT_1461df6e0`). Despite the FO4 name, it is
what consumes GCVR. Per cell, in this order (all **verified** as code):

1. `FUN_140624bb0(mgr, x, y)` (called on cell attach: FUN_14099f2c0, FUN_140c6b910, ...) loops the cells within
   `iGrassCellRadius` (DAT_1458cf950) and queues `FUN_140626cb0` -> `BGSGrassManager::AddCellGrassTask` (an IOTask,
   vtable 0x144b2e6a8, name `"AddCellGrass [%i, %i]"`). Before that it rebuilds the terrain manager's cover table
   (`FUN_1409a8b50` clear, `FUN_1409a84d0` fill: step 3).
2. Task run (vtable slot 6 = `FUN_1406215e0`) -> **`FUN_1406235b0(mgr, cell, &cancel)`**, the per-cell generator:
   * terrain = `TES->worldspace(+0x188)->+0xe0` (`BGSTerrain::Manager`; through the parent world when WRLD +0xf2
     bit 1 "use parent land" is set);
   * the cell's **biome** = `FUN_14078efa0(planetMgr, cell)` (the planet's biome map), used only for model material
     swaps (`FUN_140625d40`);
   * a per-cell random seed `FUN_14078da00`; water height `FUN_14078e900`;
   * the cell (128 units) is walked in 16 x 16 steps of 8 units; per step `FUN_1409a8bd0` returns up to 24 grass
     entries, each with an 8 x 8 weight grid; per entry `FUN_140625d40` loads the model
     (`landscape\grass\` paths only), and `FUN_140621fc0` places the grass.
3. **Cover table.** `FUN_1409a84d0(terrain)` fills `terrain+0x260[i]` (count +0x258) with the GCVR form (type 0xA8)
   of **terrain palette entry i** (`*(DAT_145fd9c30+0x138)`, 0x38-byte entries {+0 LTEX, +4 GCVR, +8 biome, +0x10..
   +0x20 material strings, +0x28 key, +0x2c slot, +0x30 palette index}).
4. **Per-sample weights.** `FUN_1409a8bd0` -> `FUN_1409a0b50(terrain, sample)`:
   * `BGSTerrain::Manager +0xe8` -> the world's terrain grid (`BGSTerrain::UniFile::Grid` vtable 0x144b683a0);
     vfunc 0x98 `FUN_140783610` returns the quadrant (64 x 64 samples) bytes 0..6
     (`CONCAT16(byte6, bytes0..5)`); vfunc 0xa8 returns the sample's u16;
   * layers = bytes **0, 1, 2, 3, 4, 6** minus 1 (byte 5 is skipped), cut at the first empty one;
   * alphas = `(word >> 3i) & 7` times 1/7 (DAT_144f04148), layer i = bits 3i..3i+2;
   * `FUN_1409a07d0` blends: `w_i = rest * a_i` for all but the last layer, last layer = rest.
5. **Cover entries.** For each layer texture i with weight > 0: GCVR = `terrain+0x260[i]`; for each grass in it
   (hash at GCVR +0x40/+0x48: {GRAS, u16 density override, 0xFFFF = the GRAS's own}): `FUN_1409a9210` writes
   `weight = (w < GCVR+0x88) ? 0 : w * density * 0.01`, plus the GRAS fields (slopes, scale range, fit to slope,
   noise parameters; GRAS vfuncs 0x410..0x4c0, +0x11c, +0x108, +0x118). GCVR +0x88 is the cover's 0..1 threshold:
   **supported hypothesis** (a float compared with the blend weight; vanilla GC_GrassFieldDried01_Yellow has 0.44).
6. **Placement** `FUN_140621fc0`: for each of the 64 sub-samples with weight > 0, a jittered seed point is kept when a
   2D noise (`FUN_140621160` -> FUN_1422cf820, GRAS noise parameters) is below 1. Then it spreads up to 16 candidates
   per seed with spacing from `cbrt(weight)`. Per point it reads terrain height and normal (FUN_140994410 /
   FUN_1409946e0), applies the water clamps and the slope range (normal z between the GRAS min / max slope cosines),
   then scale, tilt and colour. The result is instanced per model (`FUN_14062a580`).

Nothing on this path reads a density map, a biome mask value or `GetBiomeMaskValue`.

## Q4: an overlay world (SKY_Tamriel on Nirn)

The overlay's terrain is sampled from **its own BTD** (`Data\Terrain\<world>.btd`, loaded by `FUN_1409a6ed0` from
`FUN_14099f2c0`). What makes the planet matter is the **material palette**:

1. **Planet palette** (`BGSPlanet` object at planet manager +0x138). `FUN_140794170` registers every LTEX whose
   EditorID starts with `LDefault` as a mask placeholder. `FUN_140794510` takes the name after the first 11
   characters (`LDefault006` + `Base`, `LDefault004` + `FlatOut`, ...) and matches it as a prefix of the slot names
   (Q1 table), so `FlatOut` = slot 2 FlatOuter and `FlatIn` = slot 3 FlatInner. `LDirtFootprints01` is slot 6 Path.
   These form the base list (biome 0). **verified**
2. **Biome slots.** `FUN_140796a40(palette, biome)`: a biome has 7 slots {LTEX at +0x88+16i, GCVR at +0x90+16i,
   material at +0xf8+16i}, i = slot. Each slot becomes a palette entry for that biome (`FUN_1407947b0`), keyed like the
   base placeholder of the same slot. An empty LTEX falls back to the placeholder. **verified**. How BIOM LNAM
   {mask, LTEX, GCVR} fills the 7 slots (and which entry wins when several share a mask) was not traced:
   **unresolved**. The owner's tests give LNAM mask 0 = Base, 1 = FlatIn, 2 = FlatOut (verified in game, 2026-11-24).
3. **Overlay merge.** `FUN_140795110` rebuilds the palette: base, then the biomes on the planet (`+0x2c` = position in
   the biome's list), then **each overlay** (`BGSPlanet::Overlays`, lambda -> `FUN_140795410`):
   * `FUN_1409a9570(terrain, out, ..., anchorCell)` turns the overlay BTD's LTEX table into entries {LTEX, GCVR = 0,
     biome}. The **biome** is the planet biome map's value at the overlay's anchor cell (`FUN_14078efa0`), or the
     WRLD's form at +0x2b8 when there is no anchor. That gives one biome for the whole overlay: **supported
     hypothesis** (call-site argument read from the disassembly at 0x1407955d1..0x1407955e6). For each LTEX also in
     the base list, the entry takes the base entry's GCVR and slot; then **the biome's entry for that slot replaces the
     entry's LTEX, GCVR and material** (first match). Any other LTEX keeps **GCVR 0**. **verified**
   * The entries are appended to the merged palette (`+0x30/+0x34` = palette index; `bReuseOverlayTextureIndex:
     Terrain`, DAT_145e8ffa0 / reads at 0x1407955fb, reuses an identical earlier run). If the overlay's start index
     changed, **all 8 bytes of every quadrant** in the overlay's grid are rebased (`b - old + new`, 0 stays 0).
     **verified**. Bytes are u8 and the renderer stops at 256 entries (`FUN_1409a7d60`), so planet + biomes + all
     overlays must fit in 255.
4. The renderer (`FUN_1409a7d60`) builds its texture set from the same palette, so a placeholder slot renders the
   **biome's** LTEX / material for that slot. **verified**. That fits the "re-skinned vanilla rock shows through" at
   alpha 3.
5. Switches: `bAllowProcGenOnOverlays:ProcGen` (value 0x145e90138) is read only in `FUN_14079f860` (planet block
   setup, which also loads OverlayMasks). It does not touch the grass path (**verified** by xrefs); what it enables
   there is unresolved. WRLD +0xf2 bit 1 (use parent land) only redirects to the parent's terrain. No code path reads
   density maps for a hand-made world's BTD (**verified** by the DensityMapDB users: the condition function and the
   procedural block code).

### The owner's results, explained

| Test (docs/terrain/skyrim-objects.md) | Explanation from the code |
|---|---|
| Byte 6 = 0: no grass | No layer is an LDefault placeholder: every entry has GCVR 0. |
| Byte 6 = LDefault004FlatOut / 006Base / 003FlatIn: that mask's grass | Placeholder -> biome slot -> that slot's GCVR. |
| Grass only at edges, banks, blends; never inside a texture at 7/7 | Byte 6 is the last layer: weight = prod(1 - a_i), 0 if any alpha is 7. |
| Uniform patch at alpha 7: nothing; at alpha 3: nothing, grey lumps | (4/7)^5 = 0.06, below the cover threshold; the remainder renders the biome slot's LTEX. |
| Cover on every converted texture: no change | Biome entries only fill the 7 slots; non-placeholder LTEX keep GCVR 0. |
| Uniform density maps: no change | Grass never reads density maps; the key is a procedural block name anyway. |
| "table[n - b]" / end-reading coincidences | The engine reads palette[b - 1] after rebasing; the matches were spots where the mask layer had leftover weight. |

`scripts/re/ground_cover_weights.py` reproduces the weight rule for a spot (bytes and alphas as `ground_at.py` prints
them). Assumption to check per spot: ground_at's alpha order = bit order.

## Q5: the recipe

### Route A: data only (no code), up to 7 grass textures

1. **Biome** (the planet biome at the overlay anchor; for SKY_Tamriel that is NirnOceanNoCoating, 02000801, already
   overridden by S2SGrass.esm): for each of up to 7 slots, one LNAM entry {mask, LTEX = a converted Skyrim grassy
   texture, GCVR = that texture's Skyrim grass}. One entry per mask (extra entries per mask are at best ignored).
2. **BTD LTEX table**: add the vanilla placeholders (`LDefault006Base`, `LDefault005Flow`, `LDefault004FlatOut`,
   `LDefault003FlatIn`, and the Talus / Solid ones; vanilla Starfield.esm forms so the base-list lookup by FormID
   matches) as ordinary entries.
3. **BTD layers**: wherever Skyrim paints grassy texture T assigned to slot k, write slot k's placeholder in that layer
   (bytes 0..4) **instead of T**, with Skyrim's alpha. The engine draws the slot's LTEX (= T) there, so the look stays,
   and grows the slot's GCVR with that layer's blend weight. Layer order matters: front-to-back, the last used layer
   takes the remainder.
4. **Byte 6** is optional: it adds a "whatever is left" layer, used only when bytes 0..4 are all set. Write 0 or a
   placeholder whose slot should fill gaps.
5. **GCVR threshold** low (about 0.1..0.2): weights are blend fractions, and 0.44 drops most of Skyrim's blends.
6. **No density maps** (remove `--density-maps`).

Limits: 7 (texture, cover) pairs for the whole world. Other grassy Skyrim textures must share a slot (they then render
as that slot's texture) or stay bare. The biome is shared with Nirn's procedural ground that uses it. The palette must
stay under 255 entries planet-wide. Test first on one cell around Riverwood with one slot (LFieldGrass02 -> slot 0
Base): expected grass across the field at the field's own alpha, not at its edges.

### Route B: SFSE hook (exact, every Skyrim texture its own cover)

Give our LTEX entries a GCVR in the overlay palette. Hook the call at **0x1407955e6** (in `FUN_140795410`,
BGSPlanet::Overlays add-overlay functor) to **`FUN_1409a9570`**, or that function itself. After the original returns,
walk the output array (`u32 count` at +0, entries pointer at +8, stride 0x38). For every entry whose LTEX FormID (+0)
is one of our Skyrim textures and whose GCVR (+4) is 0, write our GCVR FormID. Nothing else changes: the renderer
keeps our textures, `FUN_1409a84d0` resolves the GCVR per palette index, and each Skyrim texture grows its own grass
with its own blend weight (Skyrim's model). No placeholders, no byte 6, no biome override. The map {LTEX -> GCVR} can
come from an INI written by skyrim_grass_native.py. Needs the Address Library IDs of 0x1409a9570 / 0x140795410
(versionlib, docs/re/ghidra-ai-setup.md step 3). Alternative hook point: `FUN_1409a84d0` (fills the per-index GCVR
table); there the entry's LTEX is still at +0 of the copied palette.

Not recommended: naming our own LTEX records `LDefault...`. FUN_140794510 would turn them into extra slot
placeholders and replace the vanilla slot defaults (`FUN_140794170` overwrites the per-slot table).

## Open

* **unresolved**: BIOM LNAM -> 7 slots (loader not traced), and which of several same-mask entries wins. In game
  (owner, 2026-11-24, route A test): with a second mask-0 LNAM appended to NirnOceanNoCoating, the LDefault006Base
  layers drew the biome's FIRST mask-0 entry's ground (LSandPacked05_Gray) and grew nothing: **supported hypothesis**
  that the first LNAM per mask fills the slot. Route A therefore rewrites the biome's own first entry
  (skyrim_grass_native.py --slot-first). **Refuted for the look** (second run): with the first mask-0 LNAM naming our
  texture the layers still drew pale sand and grew nothing. Open whether the slot's ground comes from the ANAM, or
  whether the overlay entry is swapped at all for layers 0..4 (next run: --slot-alt with a vanilla cover).
* **unresolved**: the `textures\terrain\` root of density-map keys; what OverlayMasks and bAllowProcGenOnOverlays
  drive (procedural blocks / objects).
* **supported hypothesis**: GCVR +0x88 = threshold; biome per overlay from the anchor cell.

## Tooling

`scripts/re/ghidra_query.py` + `scripts/re/ghidra/QueryDump.java`: batch questions to the analysed project without the
GUI (decomp, xrefs, callers, qwords, string, sym, vtable, find, insn). About 1 minute per batch. Raw outputs were
working files and are not committed (decompiled code).

| Address | What |
|---|---|
| 0x140bf45f0 | GetBiomeMaskValue condition (density maps) |
| 0x144a57018 | mask name table Base, Flow, FlatOuter, FlatInner, Talus, Solid, Path |
| 0x1407a7a70 | density-map key `%s\%s_%s.dds` from block name |
| 0x1407a7f60 | `OverlayMasks\%s.dds` |
| 0x140624bb0 / 0x140626cb0 | grass: cells around the player / queue AddCellGrassTask |
| 0x1406235b0 | grass: one cell |
| 0x1409a8bd0 / 0x1409a0b50 / 0x1409a07d0 | grass entries per sample / layer bytes + alphas / blend |
| 0x1409a9210 | weight -> grass entry (threshold, density) |
| 0x140621fc0 / 0x140621160 | placement / noise |
| 0x1409a84d0 | terrain+0x260: GCVR per palette index |
| 0x140783610 | BTD quadrant bytes 0..6 |
| 0x140794170 / 0x140794510 | LDefault placeholders / their slot |
| 0x140796a40 / 0x1407947b0 | biome slots -> palette entries |
| 0x140795110 / 0x140795410 / 0x1409a9570 | palette rebuild / add overlay / overlay LTEX table -> entries |
| 0x1409a7d60 | renderer texture set from the palette |
