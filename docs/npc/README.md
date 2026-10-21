# NPCs: faces, hair, schedules (Skyrim -> Starfield)

Labels: **verified** (seen in files), **supported** (strong evidence), **unresolved** (to test on the PC).

## Plan (owner request 2026-10-21)
1. Skyrim NPC reader (`src/fo4sf/skyrimnpc.py`): race, sex, template, head parts, hair colour, face morphs, tints,
   packages, outfits, factions, FaceGen paths. **Done** (synthetic tests).
2. Face fitter (`src/fo4sf/facefit.py`, `scripts/npc/face_fit.py`): Starfield face dials fitted to each NPC's baked
   Skyrim face. **Done** to the first-run stage (synthetic tests; PC checklist step 9 runs it on the real games and
   writes a test plugin).
3. Hair: map each Skyrim hairstyle to the nearest vanilla Starfield one first; convert the meshes later (armor
   pipeline). Not started.
4. NPC placement in the converted world (no schedules): later.
5. Navmesh, then schedules (AI packages: Skyrim PACK -> Starfield PACK; both from the same engine line). Navmesh is the
   blocker: without it NPCs cannot walk.

## Faces: how Starfield stores them (verified on xEdit's wbDefinitionsSF1, format only)
* NPC_: `Face Dial Positions` (FMSI dial index u32, FMRS position f32), `Face Morphs` (FMRI phenotype index, then
  FMRG morph group name + FMRS blend intensity), `Morph Groups` (BMPN name, BMPV intensity), tints (AVMD: TNAM group,
  QNAM name, VNAM texture, NNAM colour, INTV intensity), colours by name (HCOL hair, FHCL facial hair, BCOL eyebrows,
  ECOL eyes, JCOL jewelry, TETC teeth), STON skin tone index, MRSV body morph region values (head, upper torso, arms,
  lower torso, legs), PNAM head parts.
* RACE chargen (per sex: MNAM / FNAM): NNAM, RPRM / RPRF race presets, morph groups (MPGN + MPGM morphs), face morph
  phenotypes (FMRI index, FMRU, FMRN name, FMRS ...), FDDS skin tone subtype, **Face Dials (FDSI index, FDSL label)**,
  BSTT / HSTT / FSTT skin tones, FCTP face custom textures path.
* The facial bone region files (`meshes\actors\human\characterassets\humanracefacialboneregions{male,female}.txt`,
  JSON) define each slider: an ID, a name, ZeroToOne (0..1 vs -1..1) and per bone a Minima / Maxima of position,
  rotation and scale. Region names show two kinds: 5 phenotype regions per sex (e.g. `male_eu_md2`: all ~48 face bones)
  and sculpt regions (Mouth, Ears, Eyes, Nose, Jaw, Head Shapes, Neck, Forehead, Eyebrows, Cheeks, Chin).
* **Supported, checked by the first run (faces.json):** FMSI = the regions file's slider ID (the race's FDSI list is
  compared with the file's IDs), dial value range -1..1, positions in centimetres.
* Also learned: animation entries in the race's subgraph data may start with SADD (race); SRAF = role u16 (0 MT,
  1 weapon, 2 furniture ...) + perspective u16 (0 third, 1 first). `subgraph.py` now keeps SADD (the stance plugin's
  copies would have lost it).

## Faces: the fit
* Model: dial value v moves each of its bones by v x Maxima (v > 0) or -v x Minima; vertices follow by their face-bone
  weights. Rotation / scale linearised about each bone's pivot -> bounded least squares (each dial a plus and a minus
  column in 0..1), coordinate descent with a small ridge, re-linearised twice around the solution.
* Skyrim side: an NPC's FaceGen head has the same topology as the base head (`malehead.nif` / `femalehead.nif`), so
  its shape change is a per-vertex displacement; the two base heads are aligned once (similarity ICP, matched both ways;
  rotation dropped when it does not help, since both games face +Y with Z up) and each Starfield vertex takes the
  inverse-distance average of the nearest Skyrim displacements.
* Synthetic checks: dials recovered within 0.05 from an exactly deformed head (rotations and scales included); within
  0.12 through a differently sampled, scaled (x70), turned (4 degrees) and moved copy; bounds hold.
* More Sliders (Nexus 18445, owner upload): replaces both region files (~220 extra face bones, ~25 extra sliders built
  on them) and adds them at runtime with an SFSE plugin. The fitter can use its files (`--regions`, `--head-nif`) for a
  closer likeness, at the cost of every converted NPC needing that mod. Default: vanilla files.

## First run (checklist step 9): what to look at
`Desktop\S2S Face Test`: `faces.json` and `S2SFaceTest.esm` (one test NPC per fitted Skyrim NPC, a vanilla NPC of the
same sex with its face dials replaced). In game: `help S2SFace 4` lists them; `player.placeatme <id>`.
* faces.json: `race_dials.also_slider_ids` close to `count` (dial index = slider ID), `pivots_on_head` close to
  `face_bones`, per NPC `rms_after` well below `rms_before`.
* In game: do Lydia (HousecarlWhiterun), Balgruuf, Ulfric ... look like themselves? If every face is exaggerated or
  barely changed, the units are off (`--pos-unit`).
