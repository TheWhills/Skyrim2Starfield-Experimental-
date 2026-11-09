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

## Plan after the survey (to be decided on its results)
1. Human races (Nord, Imperial, Breton, Redguard): per race the base head shape as Starfield morph data, height /
   build, skin tone and complexion sets, eye / hair defaults; their sliders through Starfield's own dials.
2. Elves and orcs: base head shape as above; ears / tusks as head parts that follow the head's morphs (HDPT with MRPH),
   so sliders still work; skin colours (grey, gold, green) as skin tone sets; eye textures.
3. Beast races: a Starfield race with its own head (Creature Head part, or a Face part with its own morph.dat and
   facial bone regions) and tail; research whether the chargen system takes a non-human head with dials.
