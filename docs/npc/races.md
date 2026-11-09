# Skyrim races in Starfield (started 2026-11-08)

Owner: "figure out each race difference ... eventually we need to have them all with sliders as well, not just static
parts ... faithfully recreate them in Starfield". So the target is a playable-quality race per Skyrim race: its
character-creation sliders, presets, skin tones, hair / eye options, proportions, and NPCs built from them; not baked
one-off heads.

## What each game has (xEdit wbDefinitionsTES5 / wbDefinitionsSF1; format: supported, contents: the survey)
Skyrim RACE: height / weight per sex, skeleton per sex, skin armor (body, hands, feet, tail addons), body parts,
behaviour graph, hairs, eyes, voices, default hair colours, and per sex Head Data: head parts (HDPT: Face, Eyes,
Hair, Facial Hair, Scar, Eyebrows, Misc; extra parts such as ears / tusks / mouth), each with .tri files (race morph,
expression / phoneme tri, CHARGEN tri = the race's sliders: NoseLong, BrowUp, ...), face morph presets (nose / brow /
eye / lip variants), race presets (NPCs), hair colours, face detail textures, default face texture, tint layers
(skin tone, lips, cheeks, eye sockets, war paint, dirt ...). Morph race, armor race. NPC sliders live in FaceGen data.
Starfield RACE: skeleton per sex (+ rig, animation root), chargen per sex: race presets, morph groups (named morph sets
from morph.dat: the head-shape presets), face morph phenotypes (male_eu_md2 ...), face dials (sliders = facial bone
regions files), skin tone files (body / hand / face) and the face custom textures path; head parts per sex and BONE
MODIFIERS (BMOD: LookAtChain / MorphDriver / PoseDeformer / SpringBone). HDPT types include Teeth, Eyelashes, Head
Rear and Creature Head / Torso / Arms / Legs / Tail / Wings; a head part can carry its own morph (MRPH).

## Questions the survey answers (scripts/npc/race_survey.py)
- Which races matter (NPC counts), and their heights / weights / skeletons per sex.
- Do elves / orcs share the Nord head topology (same vertex count and triangles)? Then how far their base head is
  from Nord's (the race shape), and which chargen sliders they add or lack (elves' ears, orcs' tusks?).
- Which head parts are race-only (ears, tusks, mouths) and their meshes.
- Tint layers per race (war paint, skin tone sets) and texture paths.
- Beast races: their head topology, skeleton, tail / feet addons.
- Starfield: which races have chargen, how morph groups / phenotypes / dials are organised, what head part types
  and bone modifiers exist (could a new race carry its own head, ears or tail as head parts with morphs?), and the
  character files in the archives (facial bone regions per sex, head NIFs, chargen morph folders).

## Survey results (owner's run 2026-11-09; verified from Skyrim.esm / Starfield.esm and the archives)
Skyrim (Skyrim.esm only; DLC races later):
- NPCs per playable race: Nord 924, Breton 456, Imperial 349, Altmer 291, Redguard 238, Dunmer 221, Orc 133,
  Khajiit 76, Bosmer 74, Argonian 65 (plus Elder 55, Dremora 25, vampire variants, children).
- ALL ten humanoid races (and Elder, Dremora) use ONE head per sex: MaleHead.nif (898 vertices) / FemaleHead.nif
  (996). The race's shape is one morph in MaleHeadRaces.tri / FemaleHeadRaces.tri (10 morphs: one per race, largest
  vertex move male: Bosmer 5.7 cm, Orc 4.7, Dunmer 4.5, Altmer 3.6, Imperial 1.5, Elder 1.3, Breton 1.1, Redguard
  1.0, Nord 0.7; female 0.8-3.7 cm). Elf ears are vertex moves of that morph, not a separate part.
- Shared on that head: 44 expression / phoneme morphs (MaleHead.tri) and the chargen tri: male 132 / female 125
  sliders = 36 continuous (NoseLong, BrowUp, JawWide, CheeksOut, VampireMorph ...) + presets NoseType 1-30,
  EyesType 1-36 (female 1-28), LipType 1-30. Every humanoid race has the same slider set.
- Race-only parts: the mouth (MaleMouthOrc1 / FemaleMouthOrc: tusks; Khajiit / Argonian mouths), eyes (HighElf
  yellow / orange, DarkElf red, Orc yellow, WoodElf brown, Khajiit, Argonian), brows, hairs.
- Khajiit and Argonian: own heads (Khajiit 1356 / 1342 vertices, Argonian 1219), own expression tri (47-48, Khajiit
  adds LookUp/Down/Left/Right, VampireMorph) and chargen tri (52: the same 36 continuous sliders + 5 nose / eye / lip
  presets), skeletonBeast.nif (others skeleton.nif), tails (MaleTailKhajiit.nif, slot 40), Argonian hands for both,
  same body mesh (MaleBody_1 / FemaleBody_1) for every race with race textures.
- Heights m/f: Nord 1.03/1.03, Breton 1.0/0.95, Imperial 1.0/1.0, Altmer 1.08/1.08, Redguard 1.005/1.0, Dunmer
  1.0/1.0, Orc 1.045/1.045, Bosmer 0.98/1.0, Khajiit 1.0/0.95, Argonian 1.01/1.0.
- Tints: skin tone colour presets: humans 10, elves / orcs 5, Khajiit 12, Argonian 14; war paints 6-16 per race;
  30-36 tint layers on humans. Hairs / eyes come from head parts' valid-race lists (no HNAM / ENAM on the races).
Starfield:
- HumanRace (3326 NPCs) is the only race with chargen. Per sex: 9 face morph phenotypes (male_as_md1, male_af_md1,
  male_eu_md2, male_eu_ol1, male_eu_yo1, male_af_ol1, male_af_yo1, male_as_ol1, male_as_yo1), 9 morph groups (Cheeks,
  Chin, Ears, Eyes, Forehead, Jaw, Mouth, Neck, Nose), each listing one morph per phenotype (e.g. male_eu_md2_Nose:
  keys of the head's morph.dat), 49 face dials (bone sliders from the facial bone regions files), 6 / 4 presets,
  skin tone sets by name (Male_Naked_Body_Skin_Tones, Male_Hands, FaceSkinTones), 16 bone modifiers (body: butt,
  knees, calves, elbows, deltoids). Head parts: Face, Right / Left Eye, Hair, Eyebrows, Teeth, Eyelashes. Head parts
  with their own morph.dat follow the head (hair 83 of 92, eyebrows, eyelashes, teeth, jewelry, facial hair).
- No Creature Head / Tail parts are used in Starfield.esm (the types exist).
- An NPC's face = phenotype blend (FMRI index + FMRG group + FMRS intensity, i.e. per region) + dial positions +
  colours / skin tone indexes.

## What this means (proposal, 2026-11-09)
Starfield's own "ancestry" system is the same idea as Skyrim's race morph: a phenotype = a set of head morph.dat keys
per region, blended per region in chargen. So:
1. Humanoid races (10 + Elder, Dremora) become Starfield PHENOTYPES inside HumanRace (not new RACE records: quests,
   conditions and gear check HumanRace): per Skyrim race a phenotype (e.g. male_sk_altmer) whose region keys
   (male_sk_altmer_Nose, ..._Ears ...) are the Skyrim race morph moved onto Starfield's head and split by Starfield's
   own regions (the vertices each vanilla region key moves). Elf ears come with it. Added to the RACE's face morph
   phenotypes and morph groups, and to every head part's morph.dat (hair, brows, lashes, teeth, eyes) so parts follow.
   In chargen: pick "Altmer" per region and blend like vanilla; NPCs reference it like vanilla NPCs.
2. Skyrim's chargen sliders: the 96 presets (NoseType / EyesType / LipType) the same way, as extra morphs in the Nose /
   Eyes / Mouth groups; the 36 continuous sliders as new dials in the facial bone regions files (bone moves fitted to
   each morph, as face_fit fits faces; how More Sliders adds dials), so they animate with the face.
3. Per race: height (NPC height / scale), skin tone sets (elf grey / gold / brown, orc green) as new entries in the
   skin tone lists, eye colours, war paints as face tints, orc tusks as a Teeth head part with a morph.dat.
4. Beast races: a RACE each (copy of HumanRace for gear / AI), with the Skyrim head converted as its Face part,
   skinned to Starfield's face bones (weights moved over from the human head by matching regions: mouth, jaw, eyes,
   brows) so lip sync and expressions run on bones; its own morph.dat (Skyrim's 52 chargen morphs); tail as a worn
   skin part (spring bone modifiers for sway); hands / feet from the Skyrim skin addons. Unknowns: whether chargen
   takes a non-human head (dials / regions file per race) and the beast skeleton's tail bones.

## Next steps
1. Read Starfield's head morph.dat (keys, which vertices each region key moves) and the regions files: confirms the
   phenotype = region keys model and gives the region masks.
2. Offline transfer: Skyrim race morph -> Starfield head (correspondence from face_fit's alignment), split by region;
   render Nord vs Altmer vs Orc on the Starfield head next to Skyrim's (no game needed).
3. In game: one new phenotype (Altmer) in HumanRace on one NPC, then in chargen (showlooksmenu).

## Plan before the survey (kept for the record)
1. Human races (Nord, Imperial, Breton, Redguard): per race the base head shape as Starfield morph data, height /
   build, skin tone and complexion sets, eye / hair defaults; their sliders through Starfield's own dials.
2. Elves and orcs: base head shape as above; ears / tusks as head parts that follow the head's morphs (HDPT with MRPH),
   so sliders still work; skin colours (grey, gold, green) as skin tone sets; eye textures.
3. Beast races: a Starfield race with its own head (Creature Head part, or a Face part with its own morph.dat and
   facial bone regions) and tail; research whether the chargen system takes a non-human head with dials.
