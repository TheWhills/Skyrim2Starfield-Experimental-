# Skyrim races in Starfield: the whole road (2026-11-10)

Owner: "all the things we need to do to get the races as separate races in game, with their look from Skyrim, as
well as working sliders that follow what you can change in Skyrim, as well as future-proofed compatibility for things
that affect the races (racial body morphs etc.)". Background and survey numbers: races.md. Status words: **done**
(verified in game), **built** (offline, synthetic tests), **open** (not started), **research** (an unknown to settle
first).

## 1. What "a Skyrim race in Starfield" has to mean
| Part | Skyrim | Starfield target |
|---|---|---|
| Identity | RACE record; content checks GetIsRace | own RACE thin over HumanRace (armor race, subgraph template = HumanRace) |
| Head shape | one head + the race's morph (HeadRaces.tri) | the race morph baked into the race's own head model |
| Face parts | race eyes, brows, mouths (orc tusks), shared beards | race copies of every face part, baked with the shape; Skyrim mouths / eyes where they differ |
| Skin | race skin texture + skin tone presets (5-14) | race skin tone list (and textures where a tint is not enough) |
| Eyes | race eye textures (Dunmer red, Altmer gold ...) | race eye colour list, Skyrim textures remapped onto Starfield's eyeball |
| Hair | race-valid hair lists, default hair colours | converted Skyrim hairs on race lists, vanilla hair shared |
| Body | height per sex, weight slider (thin / fat body), skeleton (beast) | height (DAT2), body shape on Starfield's body sliders, proportions |
| Sliders | 36 continuous + Nose / Eyes / Lip presets, tints (war paint, dirt), complexion, age | Starfield's own sliders working on the race head, plus Skyrim's as extra sliders |
| NPCs | FaceGen per NPC on its race | each NPC on its converted race, only its own features fitted |
| Player | race menu | new game presets per race, and a way to change race later |

## 2. Workstreams, in dependency order

### A. Identity and records
- **done:** S2S_<Race>Race thin over HumanRace (RNAM / SRAC HumanRace, no subgraph entries: NPCs animate); player
  patch plugin (getisrace 1.00); head-part valid-race list fix (no crash on facial hair).
- **built:** every race at once (`--new-races all`), heights from Skyrim, race names resolved from Starfield's string
  tables, presets in RPRM / RPRF.
- **built (2026-11-10):** stable FormIDs: `race_formids.json` in the race mod folder maps every EditorID of ours to its
  object id; rebuilds reuse it, new records take ids after every id ever used (keep that file). Every form list
  holding HumanRace now holds our races too; 'GetIsRace HumanRace' conditions in CNDF / IDLE / CPTH records widened to
  our races ('is human' -> an OR group with ours, 'is not human' -> also not ours; inside an OR group left alone).
- **open:** the 14 INFO conditions of the 19 (dialogue lines; INFOs sit inside quest / topic groups, which the race
  build does not write yet); HumanRace's keywords on our races (copied with the record, to verify in game).
- **research:** vampire / child variants (Skyrim has NordRaceVampire ...): later, as their own races or a keyword.

### B. Head look
- **built:** race shape baked into a head NIF + `_facebones` twin per race and sex; race head part on the vanilla
  morph record (vanilla blends work on top).
- **open (owner test pending):** shape pads / eye shape move on the race head (the `_facebones` twin fix); row names.
- **research:** elves' eye tilt: measure Skyrim's elf eye against its human eye (sky_eyes.txt) and turn Starfield's
  eye the same way, instead of only following the socket.

### C. Face parts
- **built:** race copies of every eye, lash, brow, beard, teeth and face-jewelry part, moved with the head (eyes as one
  piece); Orc mouth (Skyrim's teeth + tusks) with Starfield's talking morphs copied per jaw side.
- **open:** in-game check of all of it; other Skyrim race mouths only for the beast races.

### D. Skin
- **built:** look_probe (how Starfield stores skin tones: AVMD lists named by the race's BSTT / HSTT / FSTT / FDDS).
- **open:** per race skin tone lists from Skyrim's presets (Orc green, Dunmer grey-blue, Altmer gold ...), named in the
  race's own chargen strings (not overriding the human lists); face / body detail textures only where a tint cannot
  match (Skyrim's elf face textures carry more than colour: research after the tone test).

### E. Eyes
- **open:** Skyrim race eye textures remapped onto Starfield's eyeball (match the two eyeballs point by point, as the
  face textures), a race eye colour list (look_probe shows Starfield's eye colour mapping).

### F. Hair and brows
- **done / built:** Skyrim hairstyles converted (S2SSkyrimHairs.esm); vanilla hair shared with our races.
- **open:** race-valid hair lists like Skyrim's (orc hairs for orcs, ...), race default hair colours.

### G. Body
- **built:** height per race.
- **open:** Skyrim's weight slider -> Starfield's body sliders (thin / muscular / heavy): NPC weight 0-100 mapped
  onto the body triangle; the owner's race proportions test (OWNER-SETUP step 11: does a race-specific skeleton /
  helper bone scaling take effect).
- See K for how body changes stay compatible with gear and body mods.

### H. Sliders that follow Skyrim
Skyrim offers, on every humanoid race: 36 continuous sliders (NoseLong, BrowUp, JawWide, CheeksOut ...), presets
NoseType 1-30, EyesType 1-36 (female 1-28), LipType 1-30, tint layers (war paint, dirt, lips, cheeks, eye sockets),
complexion / age textures. Starfield offers phenotype blends per region (morph keys), 40 sculpt dials (face bones,
facial bone regions file), makeup layers, skin tones.
1. **open:** Starfield's own sliders working on every race (B).
2. **open:** Skyrim's 36 continuous sliders as new sculpt dials: per slider, the face-bone moves that best reproduce
   Skyrim's morph (fitted like face_fit fits faces), written as extra dials in the race's facial bone regions file
   (`s2s_<race>facialboneregions<sex>.txt`; More Sliders adds dials the same way). Bones, not morphs, so gear and
   hair follow and the 128-key morph limit is not touched.
3. **open:** Skyrim's Nose / Eyes / Lip presets: as a dial each would be too many; as morph keys they exceed 128 with
   the vanilla 84. Options: (a) the race head's own morph record with the presets of its region only for that
   race's chargen (84 + 30 nose = 114 fits; eyes and lips in other parts' files), (b) fitted bone presets stored as
   dial values (a preset = a set of dial positions: a Starfield "preset" row), (c) leave presets out and rely on the
   continuous sliders. Recommended: (b), no morph keys at all. **research:** does Starfield take a race-named
   regions file (test pending, B).
4. **open:** war paint / dirt as Starfield face makeup layers (textures remapped from Skyrim's head UVs).

### I. NPCs on their races
- **built (2026-11-10):** face_fit --races-plugin (races.md log). Earlier wording: face_fit puts each NPC on its converted race (RNAM, the race's head and face parts, its skin tone and eye
  colour) and fits only the NPC's own features: its FaceGen head minus Skyrim's base head WITH the race morph, so
  the race shape is not applied twice (owner, 2026-11-10: Faendal with the Bosmer head).

### I2. Children
Skyrim: one race, ChildRace, for every child whatever the parents' race (so no elf ears on elf children), its own
head, child body and smaller skeleton; FaceGen faces per child; children's clothes, hairs and voices (MaleChild /
FemaleChild).

What the owner's reference mod shows (Playable Children 0.4, Nexus 11014, read 2026-11-10; its records only, its
assets are not ours to ship):
- Starfield has a vanilla ChildRace (00034FB1; with HumanRace and HumanCorpseRace in the vanilla condition form
  HumanRaceORChildRaceORHumanCorpseRace) and child head parts (HeadPartsChildRace, 0001550F).
- **Starfield's child heads have the adult head's topology** (the mod's child_head_boy / child_head_girl: 15,370
  vertices, 29,708 triangles, as the adult head; the child head's chargen morph record points at the ADULT chargen
  morph.dat, Meshes\Morphs\Human\Female\Chargen\Head, its performance morphs at Meshes\Morphs\Child\Head_Girl\
  Performance). So everything built for adult heads (face fit, baking, face parts) works on child heads.
- The mod's playable child race HCRace is built the way ours are: a copy of HumanRace with RNAM / SRAC HumanRace placed
  after the skin tones and no subgraph entries, a child skeleton of its own (Actors\cpc\CharacterAssets\skeleton.nif
  + _facebones twin, the human .rig and animations), height 0.86, its own head parts and valid-race list, the adult
  naked body meshes on that skeleton (the child shape comes from the bones), child clothes with chargen morph.dat,
  the vanilla condition form widened to its race.

Steps:
1. **research (owner run 2026-11-12, done in part):**
   - Starfield ChildRace 002AABCD: skeleton Actors\Child\CharacterAssets\skeleton.nif (both sexes), the female
     human .rig, Human_Root graph, human animations; height (DAT2) 0.86 / 0.86; skin tone strings
     Child_Male_Body / Child_Female_Body / Child_Female_Hands / FaceSkinTones_Child; SRAC HumanRace; head parts
     Human_Child_Head_Boy (00243A73, Actors\Child\Mesh\Child_Head_Boy.nif, morph 00243A9A) / _Girl (00243A74),
     child eyes / brows / lashes / teeth / 8 child hairs (child_parts.txt).
   - **Skyrim has no single ChildRace:** NordRaceChild, ImperialRaceChild, BretonRaceChild, RedguardRaceChild
     (+ BretonRaceChildVampire). So the plan below changes: a child race per Skyrim child race.
   - Vanilla child outfits are their own ARMA on ChildRace (AA_Clothes_Child_CoraCoe: Clothes\Outfit_Child_CoraCoe\
     Outfit_Child_CoraCoe.nif); child or adult size still to measure (model_bounds).
   - Next: Skyrim's NordRaceChild record (head parts, base head) and a child NPC's (Dorthe's) record.
2. **S2S_<Race>ChildRace** per Skyrim child race (Nord, Imperial, Breton, Redguard), thin over Starfield's ChildRace
   (as our adult races over HumanRace), so content asking GetIsRace NordRaceChild works.
3. **Faces:** each child's own head, baked: Skyrim FaceGen child head minus Skyrim's child base head, moved onto
   Starfield's child head (the adult correspondence after a child-to-child alignment), written as that NPC's own head
   part (headbake). No sliders needed for NPCs, and it works whether or not the child skeleton has face bones.
4. **Body:** Starfield's child skeleton and body (vanilla ChildRace's), height from Skyrim's ChildRace.
5. **Clothes:** in the Playable Children MOD a child's outfit is an ADULT-sized mesh on the normal human bones, shrunk
   by its child skeleton; whether vanilla Starfield's children are built that way is **unverified** (the mod remade
   the vanilla child outfits under clothes\cpc, which hints that vanilla's are not; owner's model_bounds run on a
   vanilla child outfit settles it) (Cora Coe outfit, read 2026-11-10: 11,470 vertices, 1.52 m tall, z -1.632..-0.114 m,
   the same space and +1.632 m lift as the vanilla adult outfits; its addon lists ChildRace 00034FB1 among its races;
   the child skin is the adult Naked_M / Naked_F on that skeleton). So gear_fit's output already is the right kind of
   mesh if vanilla works the same; if vanilla child outfits are child-sized, the target is the vanilla child body
   instead: Skyrim's children's clothes are fitted with Skyrim's CHILD body as the source and Starfield's adult body as
   the target, and their addons list ChildRace / S2S_ChildRace. Hairs through the hair converter onto the child head.
   (The owner's second mod, Cora Coe Outfits, is one recoloured texture: nothing about the mechanics.)
6. **Voices:** MaleChild / FemaleChild lines through the voice pipeline (start-of-game filter included), a child voice
   type as template.
7. **AI:** their packages through the schedule converter; Starfield's human animations on the child skeleton (as
   vanilla children and the mod).
8. **Player children (optional):** with Playable Children installed its HCRace already gives that; not ours to rebuild.
Built so far: face_fit skips ChildRace NPCs (they would come out adult-sized on an adult template).

### J. Beast races (Khajiit, Argonian)
- **open:** own heads (1356 / 1219 vertices) converted as the race's Face part, skinned to Starfield's face bones
  (weights carried over by region: mouth, jaw, eyes, brows) for lip sync; their 52 chargen morphs in their own
  morph.dat; tails as a worn part with spring bones; Argonian hands / feet; skeletonBeast (digitigrade legs) is the
  hard part (research: whether Starfield's human animations run on it or a retarget is needed).

### K. Compatibility, future-proofing
- **Build from the user's load order, not from Starfield.esm alone.** Today the race builder copies HumanRace,
  the head, the regions files and morphs from the vanilla files. Any mod that changes those (body mods' bone
  modifiers on HumanRace, More Sliders' dials, a hair mod's head-part lists) is not inherited. Plan: read the MO2
  profile's plugin order and loose files, take the WINNING HumanRace / head parts / regions files, and rebuild the
  races from those (rerun after installing such a mod). This is how racial body morph mods keep working.
- **Proportions through bones, not new morph keys.** Race body differences (Orc broader, Altmer taller) as bone
  modifiers / skeleton scaling: every worn mesh skinned to those bones follows without per-armour work; a morph-key
  route would need every armour's morph.dat to carry the race keys.
- **Gear:** armor race HumanRace (all HumanRace gear fits, verified for NPCs); our converted gear's morph.dat follow
  Starfield's body sliders, so a race's body shape set on those sliders is covered.
- **Few overrides of vanilla records:** today the race plugin overrides HeadPartsHumanRace (adds our races for shared
  hair) and the vanilla face parts (humans only). Both are conflict points with other mods: keep them in a small
  separate patch plugin, regenerated from the load order (so it merges other mods' additions instead of dropping
  them).
- **Keywords over race checks:** our races carry HumanRace's keywords; new content of ours should test keywords
  (e.g. a Skyrim race keyword) rather than race records, so later race variants pass too.
- **Stable FormIDs** (A) for save compatibility.

### L. Player
- **done:** player patch (play as the race on an existing save).
- **open:** new game: each race's presets in the Biometric ID screen (built: RPRM / RPRF), check in game.
- **research:** changing race in game without the patch (Papyrus Actor.SetRace from a genetics terminal or an item;
  the console setrace on the player did not stick).

## 3. Suggested order
1. Owner tests of what is built (B, C, the Orc rerun).
2. A: stable FormIDs and the GetIsRace / list patch (cheap, protects saves).
3. I: NPCs on their races (Riverwood: Nords + Faendal) - the visible win.
4. D, E: skin tones and eye colours (look_probe first).
5. H2: Skyrim's continuous sliders as dials (after the regions-file test).
6. K: build from the load order (before body mods are installed).
7. G, H3, H4, F; then J (beast races) as its own project.

Children research, owner's runs 2026-11-12 (step 1, continued): a vanilla child outfit (Outfit_Child_CoraCoe.nif)
is adult-sized (1.52 m tall, the adult outfits' +1.632 m lift; the child skeleton shrinks it), so outfits converted
for adults fit children too once their addons name the child races. Skyrim's NordRaceChild uses the ADULT skeletons
(skeleton.nif / skeleton_female.nif), height 0.8, head parts male 0001C22E / female 0001C558 (+ 00051401, 000511CA,
000511CB); Dorthe is NordRaceChild with her own head part 0001C559. scripts/npc/child_probe.py (read-only) next:
whether a Skyrim child head is its own mesh, Dorthe's / Frodnar's FaceGen heads, and how Starfield's child NPCs are
built (dials, blends, baked faces) and how its child heads compare with the adult heads.
