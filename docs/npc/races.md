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

## Decision (owner, 2026-11-09): separate races, thin over HumanRace
For a long-term conversion Skyrim's content checks race constantly (dialogue, quests, racial powers, vampires), so
each Skyrim race becomes its own RACE, but derived from HumanRace: armor race = HumanRace (gear fits), subgraph
template race = HumanRace (animations), morph race = HumanRace (shared head morphs / sliders; its effect in game
unverified), HumanRace's keywords (anything asking "human actor" passes). Its chargen lists only its own phenotypes;
it carries height, skin tones, eyes, voices. The phenotype work (race shapes as region-keyed head morphs) is needed
either way and comes first. To prove early: the player side (setrace + showlooksmenu on such a race).
Constraint found 2026-11-09: a morph.dat holds at most 128 keys (128-bit key mask per vertex, sfmorph). 12 humanoid
races x 9 regions = 108 keys on top of the vanilla head's would not fit; race_probe reports the vanilla head's count.
If it does not fit, the Skyrim races get a head part of their own (same mesh, own morph.dat with their phenotypes),
which fits the separate-races design; hair / brows / lashes then need the same keys in their morph.dat to follow.

## Next steps
0. scripts/npc/race_probe.py (2026-11-09): items 1 and 2 below plus HumanRace-by-name counts in Starfield.esm.
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

## race_probe results (owner's run 2026-11-09; verified from the game files)
- Starfield head morph.dat (both sexes): 15,370 vertices, 84 keys = 9 phenotypes x 9 regions (Cheeks, Chin, Ears,
  Eyes, Forehead, Jaw, Mouth, Neck, Nose) + Overweight / Thin / Strong; 44 of 128 key slots free. 12 Skyrim races x 9
  regions = 108 do not fit: as planned, the Skyrim races get a head part of their own (same mesh, own morph.dat).
  Regions overlap a lot (Eyes 6354 vertices, Cheeks & Eyes share 1395): soft regions, so a race shape is split by
  weights (how much each region's vanilla keys move a vertex), not hard masks.
- Parts carry the phenotype keys of the regions that touch them: brows (Eyes / Forehead / Nose, female + Cheeks),
  lashes (Eyes), hair (cropped_m: 54 keys; choppy_bob_f 40) plus Overweight / Thin / Strong; no chargen morph.dat for
  teeth (nor male eyes_tears) at those paths.
- Facial bone regions: 49 dials per sex = 9 phenotype dials + 40 sculpt dials (Nose 9, Mouth 4, Eyes 4, Head Shapes 4,
  Ears 3, Jaw 3, Eyebrows 3, Cheeks 3, Chin 3, Neck 2, Forehead 2).
- HumanRace (0000347D) by name in Starfield.esm: GetIsRace in only 19 conditions (14 INFO, 2 IDLE, 2 CNDF, 1 CPTH);
  armor race (RNAM) on 586 ARMA / 539 ARMO (a race with armor race = HumanRace is covered); NPC_ RNAM (their own
  race), ATKR 372; two RACE records already point at HumanRace as armor race (RNAM) and subgraph template (SRAC):
  Bethesda's own thin races. FLST 2, QUST script 1, GBFM 3. So separate races risk little (the 19 conditions and the
  2 lists can be patched to include them).
- The transfer of this run is NOT usable: the Skyrim head was aligned 90 degrees off (rms 2.3 cm male / 1.7 female;
  the viewer showed the heads crossed). Cause (verified on the run's data): Starfield's head .mesh is stored in
  C_Head's rotated frame (x up; hair_pack.game_mesh_of already applies the shape node for that), and the ICP started
  from the identity. face_fit used the same alignment, so every fitted face so far was fitted through it.
  Fixed: facefit.align_to_local (Skyrim model space, Starfield through the head shape's node transform, scale + shift
  without rotation, the longer Starfield neck left out); face_fit and race_probe use it (--legacy-alignment for the
  old one). To check: the probe's new rms (skyrimhair measured 6.7 mm on the cranium this way) and the faces after a
  face_fit rerun.

## Second probe run (owner, 2026-11-09): alignment fixed; transfer reworked
- Alignment (verified): rms 0.82 cm male / 0.80 cm female in model space (was 2.3 / 1.7 cm); the viewer shows both
  heads upright and facing; elf ears and the orc jaw land on Starfield's ears and jaw.
- Three faults in the transferred shapes (owner's screenshots; measured on the run's race_view.html data, which holds
  both aligned heads and every race's deltas):
  1. Cracks on the scalp: 464 vertex pairs of Starfield's head sit at the same spot (split along UV seams); the
     smoothing treated them as unrelated and moved them apart by up to 6.4 mm (orc male).
  2. A white strip behind the ears and folds on the cheeks: the 4-nearest-vertex average cannot tell the front of an
     ear from its back, and jumps where the set of 4 nearest changes (move field up to 3.9x as steep as the surface).
  3. The orc's mouth closed: Starfield lip vertices averaged Skyrim's upper and lower lip, losing the underbite.
- Topology (verified): Skyrim's head has a mouth hole (12 vertices male, 20 female); the female head also has 37 loose
  single triangles inside the lips. Starfield's head has one open edge only (the bust): its mouth is a closed pocket,
  the lips joined through the inner mouth, so the mouth opens without tearing.
- New transfer, fo4sf/headcorr.py: each Starfield vertex takes one point on the Skyrim surface (triangle +
  barycentrics) out of its 8 nearest triangles facing the same way, chosen so that mesh neighbours' points are close
  along the Skyrim surface (edge geodesics) and the lip side matches (surface distance to a point above vs below the
  mouth, the same measure on both heads); moves are averaged over seam-split vertices and smoothed on the welded mesh.
  Checked on the owner's data: identical to the prototype; seam splits 0; the orc's open underbite and the elf / orc
  ears come out whole (renders compared side by side with Skyrim's). The "fold" at the mouth corners
  (measured on the owner's data, female orc): the stretched edges (tiny 0.1-0.3 mm edges stretched up to 15x, to ~2 mm)
  lie 2-9 mm behind the lip front with normals facing sideways / back: Starfield's inner-mouth pocket, which the
  opened lips expose at the corners (the viewer draws it in skin colour; in game it carries the mouth's own texture
  and the teeth sit in front). Tighter neighbour settings (slack 0.3-1.5, mu 1-4) and easing the moves toward Skyrim's
  corner within 4-8 mm changed nothing visible: not a transfer fault (supported; to see in game with the orc mouth). About 20 s per sex.
- Measured, all races, old -> new (male; female similar): seam split max 8.3 mm -> 0; distance from the moved
  Starfield head to the moved Skyrim head, change vs the base heads, p95: about halved (Nord 0.55 -> 0.25 mm, Imperial
  0.68 -> 0.37, Orc 2.60 -> 1.60); the bust edge (where the head meets the body) moved up to 1.2 mm under the old
  average (elves), 0 now. Steepest local change rises (orc 3.9 -> 28.7 x the edge length): the lips separating, which is
  the open underbite, wanted. Female DremoraRace's morph equals HighElfRace's to the digit (in FemaleHeadRaces.tri as
  read; unresolved whether Skyrim shares it on purpose).
- race_probe and face_fit use it by default (--transfer nearest for the old average). face_fit's faces change with it
  (and with the alignment); a rerun and a look in game are needed.

## Race heads test (2026-11-09; offline checks only)
- How vanilla NPCs name head morph keys (verified on the owner's npc_dump of vanilla NPCs): BMPN (blend name) =
  a morph.dat key such as male_eu_ol1_Mouth, BMPV its intensity; FMRI (the race's phenotype index, e.g. 12 =
  male_eu_md2) + FMRG / FMRS is the chargen's record per phenotype and region, and does not always match the blends
  (Ralof's template: male_af_ol1_Nose 0.25 only in BMPN, male_eu_ol1_Mouth 0.62 vs 0.34). So BMPN looks like what
  the head is built from (supported).
- A head part names its morph record (HDPT MNAM -> MRPH); the MRPH's TCMP is the folder holding morph.dat (xEdit;
  verified for armor 2026-11-06).
- scripts/npc/race_heads.py: per sex one morph.dat = the vanilla head's 84 keys + 9 region keys per Skyrim race
  (<sex>_sk_<code>_<Region>; 4 races fit in 128 keys), a race's shape split over the regions by how far the vanilla
  phenotype keys move each vertex (normalised; unmoved vertices take their neighbours' weights; seams welded), so the
  9 keys at 1.0 add up to the whole shape. A frame check (vanilla Overweight must point outward along the head's
  normals) guards the assumption that morph.dat deltas are in the head mesh's frame. S2SRaceTest.esm: MRPH + HDPT
  copies of the vanilla head's, one NPC per race and sex with our head part (PNAM) and the race's keys as BMPN 1.0, a
  control NPC; --race-head adds a HumanRace override (our head part as its Face part, our keys in its morph groups).
- To learn in game: (1) the control NPC looks plain (our head part and morph.dat load); (2) the race NPCs show the
  race (BMPN applies new keys from an NPC's own head part); else (3) with --race-head. Then setrace /
  showlooksmenu with a thin race (step 4 of the decision).

### Owner's race heads run (2026-11-09, in game)
Control NPCs: a plain light face (our head part and morph.dat load). Altmer, Bosmer, Dunmer (and the others): the face
dark red with the nose, lips and eyelids light, ears not visibly pointed in the front shots. Reading (supported, not
verified): with no pre-built face textures the game builds the face texture at runtime, and it follows the morph
blends (BMPN); our new keys name no textures, the vanilla ones do (the control, with no blends, came out plain).
race_heads now copies the template's pre-built face textures under each test NPC's FormID, as face_fit does for its
NPCs (bake_faces). Next look: the shape (side view: ears, brow, cheekbones), now that the colour is the template's.
The males' long hair hid the ears and the sides of the face (owner): the test NPCs now have no hair or beard
(--keep-hair keeps the template's).
Rerun with baked textures and no hair (owner, same evening): still dark red with a light nose and lips, so the
texture reading was wrong (the hair came off; a short race-default hair came back). New cause (verified in the
format, in game unverified): each morph.dat record carries a colour word and packed normal / tangent deltas
(10:10:10:2, 511 = zero; 0x5FF7FDFF = no change, colour 0xC618 on every record of a modded outfit's 238 keys). Our new
race keys were written with zeros there, i.e. a normal delta of -511 on every axis wherever a race key moves the
face, which lights it black-red (the nose and lips, mostly unmoved, stayed light). sfmorph.build now writes the
no-change words by default; race_heads uses the vanilla head's own colour word for its new keys.
Third run (owner, same evening, verified in game): skin colour right on every race. Pointed ears show on the Orc,
Bosmer and Dunmer; the Orc's mouth hangs open as a dark hole (the race shape opens the lips; Starfield's teeth and
mouth do not follow: the mouth converter, "Mouths and tusks"). The race-default hair still hides the ears and the
head's outline, so the test NPCs now get the closest-cropped vanilla hair (EditorID with bald / shaved / buzz).
Fourth run (owner, verified in game): cropped hair (a vanilla mohawk), ears and head outline visible on every race.
The ears differ left / right: on the females the viewer's-left ear looks better, on the males the right. Skyrim's
race heads are symmetric, so this is the transfer's left / right noise; race_heads now averages each race shape with
its mirror image across the head mesh's own lateral axis (facefit.lateral_axis: the .mesh is in C_Head's frame, so
X is not always across; --no-symmetry keeps the raw transfer).
Fifth run (owner): with the mean the females' good, pointed ear came out rounded: the transfer had the point on one
side and had lost it on the other, and the mean halved it. Now per vertex pair the side that moved more is kept and
mirrored (--symmetry stronger, the default; mean / none). The lost side points at the correspondence (headcorr)
around one ear: to look at if other parts show one-sided losses.
Owner, 2026-11-09 after that run: the females look better now (verified in game).

### First Skyrim race of its own: Orc (2026-11-09, owner: "yes"; offline checks only)
race_heads --new-races Orc adds S2S_OrcRace to S2SRaceTest.esm: a copy of HumanRace (skeleton, behaviour graphs,
chargen, dials, bone modifiers, keywords: anything asking for a human passes) named "Orc", armor race (RNAM)
HumanRace so every HumanRace gear piece fits, subgraph race (SRAC) HumanRace placed where MannequinRace has it
(MannequinRace and HumanCorpseRace are vanilla thin races over HumanRace: RNAM + SRAC, owner's race_probe). Per sex:
our head part as its Face part, a chargen phenotype of its own (a copy of the eu_md entry, FMRU <sex>_sk_or1, the
next FMRI index) and the Orc keys added to the morph groups; plus an Orc NPC per sex of that race (RNAM). Not yet:
height (Skyrim Orc 1.045), skin tones, eyes, the mouth. To learn in game: setrace on the player (no crash, gear on,
animations), showlooksmenu (does the Orc phenotype show in each region's blend, does it apply), the Orc NPCs.
Owner's first look (2026-11-09, verified in game): the race exists (getisrace names S2S_OrcRace); its two NPCs show
the Orc head but stand in the reference pose, arms out, no animation; player.setrace 1600080F left the player
HumanRace (getisrace 0). Change: the copy no longer carries HumanRace's own subgraph entries (SADD / SAKD / STKD /
SGNM / SAPT / SRAF) and takes them through SRAC alone, as MannequinRace does. Setrace on the player to retry after.
Second look (owner): no change: both NPCs still in the reference pose (and a hand shows at the groin), the player
still not the race. So the subgraph entries were not it. Next: the whole record of MannequinRace and HumanCorpseRace
(vanilla thin races whose NPCs animate) against HumanRace and ours (npc_record_diff --show) before changing more.
Record dump (owner's run, verified): S2S_OrcRace = HumanRace exactly, plus RNAM at the top, our phenotype (FMRI /
FMRU / FMRN / FMRS) and group entries; the second build was the same as the first (MannequinRace has no SRAC, so the
code added none and dropped nothing). MannequinRace: its own root graph, rig and one subgraph entry, RNAM (HumanRace)
after the last BSTT / HSTT right before the subgraph entries. HumanCorpseRace: HumanRace's graph and rig, RNAM in the
same place, no subgraph entries. Reading (supported, Fallout 4's rule: a race's animation data is precomputed per race
from its subgraph entries, so a new race reuses another's with SRAC "subgraph template race"): ours now has RNAM +
SRAC (both HumanRace) where HumanRace's 400 entries began, and none of the entries; the phenotype's name (FMRN, a
string id in vanilla) is "Orc".
Third build (owner, 2026-11-09, verified in game): both S2S_OrcRace NPCs stand in a normal idle, arms down: the race
animates through SRAC. Player setrace / chargen still to check.
The player (2026-11-09): setrace on the player left getisrace 0, and no Starfield race mod found uses it; the Exo
Race mod (Nexus 7992) ships a player patch (ExoRacePlayer.esm edits the Player record) plus an item for existing
saves that strips the old human head parts. Same route here: race_heads --player-race Orc writes S2SOrcPlayer.esm,
the Player record (00000007) with RNAM = S2S_OrcRace and our head part, masters Starfield.esm + S2SRaceTest.esm.
A face's recipe (blends, sliders) stays human after any race change, so the race now also lists its two Orc NPCs as
chargen face presets (FDSI / FDSL after each sex's vanilla presets): one pick gives the whole Orc face.
Owner, 2026-11-10 (verified in game): with S2SOrcPlayer.esm on, an existing save's player is S2S_OrcRace
(getisrace 1.00), still looks and animates as before (the face recipe is unchanged). Chargen next.

## Mouths and tusks (2026-11-09; offline checks only)
- Skyrim (verified, race_survey): teeth / tongue / tusks are a head part of their own (Misc type): MouthHuman.nif /
  MouthHumanF.NIF (141 vertices) for humans and elves, MouthOrc.nif / MouthOrcFemale.nif (348) for orcs, Khajiit and
  Argonian mouths; each with an expression tri (Aah, BigAah, phonemes, moods) and no race morph (the orc mouth is made
  for the orc head). Starfield: teeth are a head part too (HDPT type Teeth: Human_Male_Teeth -> Teeth.nif), skinned to
  face bones, so a Skyrim race can get its own Teeth part.
- scripts/npc/mouth_probe.py: places the Skyrim mouths with the head alignment, marks the jaw part by Aah (vertices
  that drop when the mouth opens), copies bone weights from the nearest Starfield tooth on the same side (Starfield's
  side from its bone names: unverified which bone the lower teeth use; the report lists them), and compares each
  mouth vertex's distance to the head surface in Skyrim (orc head) and Starfield (head + transferred orc shape):
  the tusks should stand out of the lips by the same amount. Viewer: mouth_view.html. Next, if it checks out: the
  orc Teeth head part (converted mesh + weights, textures from the mouth's material) for the orc race.

## Beast races: plan and probe (owner 2026-11-09: "yes"; offline checks only)
Skyrim (verified, race_survey): own heads (Khajiit 1356 / 1342 vertices, Argonian 1219) with expression tris of the
same names as the human head's (Aah, Blink, Brow, Squint, Look, phonemes, moods) and chargen tris of 52 sliders (36
continuous + nose / eye / lip presets); the mouth and eyes have chargen tris too (they follow the sliders);
skeletonBeast.nif; tails (slot 40); the human body with beast hands / feet and textures.
Plan: (1) probe; (2) the beast head as its own Face head part on Starfield's face bones, weights from Starfield's
head through a landmark warp (beast -> Skyrim human head) and the existing human -> Starfield matching, checked
against the beast's own Aah; (3) all sliders as keys in the head's own morph.dat (fits 128), presets as morph-group
entries, continuous sliders as bone dials (as face_fit fits faces) if the chargen takes a per-head dial file
(MRPH BMPP "Bone Morph Definition File": the probe lists what vanilla puts there); (4) a separate RACE over HumanRace
with its skin tones, eyes, hair / horns (hair converter), mouths; (5) tails: fixed to the pelvis first, sway later
(tail bones in the skeleton or spring bones: unknown).
scripts/npc/beast_probe.py does (1): landmarks (eye centres, mouth-hole corners, nose tip, crown, back, sides), a
thin-plate warp onto Skyrim's human head (distance to its surface reported), face-bone weights from Starfield's head
(nearest compatible point; headcorr with mu 0, which now skips the surface-distance table), the Aah check (jaw
weight on the vertices Aah drops vs those it leaves), slider counts, the tail's bones, the beast skeleton's extra
nodes, Starfield's MRPH BMPP values. Viewer: beast_view.html.

## Race proportions from per-race skeletons (2026-11-09, Racial Body Morphs - Extreme, Nexus 65047)
Owner: will a mod like this work with our races? What it is (verified from its files): 21 XPMSE-style skeletons, one
per race and sex, and a plugin overriding 26 RACE records' ANAM (skeleton per sex); no body or armour meshes. Between
a bone and its child bone XPMSE has helper nodes no clip animates ("CME ..."); the mod scales / moves the inner one
(Orc male: hips and upper body x1.106, clavicles x1.08, forearms x0.94, head x0.9; Altmer male: upper body x0.92, hips
8.6 cm up, calves 8.7 cm further down the thigh). Everything skinned below follows, bodies and armour alike, which is
why the mod needs no clothes of its own.
* Starfield's human skeleton has no such helpers (skeleton_probe.py on an extracted copy, 2026-11-09: rig 97 bones,
  82 animated + 15 twist; of the 57-58 NIF nodes outside the rig only HumanExportRoot sits above animated bones, the
  rest are leaves: CalfMass, Deltoid, Butt, Pecs ... the chargen bone modifiers). So the proportions need helpers
  inserted as XPMSE did: `fo4sf/racebones.py` reads the CME values (composed helper chain per bone, in the parent
  bone's frame), maps them onto Starfield bones (skeletonmap; offsets through character space, both games Z up / +Y
  forward / +X left, checked on hands, feet, head) and inserts S2S_RB_<bone> NiNodes (scale, offset; the bone's own
  local transform unchanged).
* `scripts/npc/skeleton_probe.py` writes the per-race table and, with --test-pack RACE, a loose override of the human
  skeleton.nif (male and female) with that race's helpers: every human then has those proportions. Unresolved, the
  test answers it: whether Starfield's animation keeps a non-rig parent node's scale / offset (as Skyrim does). If yes:
  per race a skeleton copy on its RACE (the separate-races design above); if not: an SFSE step re-applying the scales
  after animation. Tails (Khajiit / Argonian) and rotations in helper chains are left out for now.

## Owner's run of the probes, 2026-11-09 evening
* **Race probe (surface transfer): verified good.** Alignment rms 8.2 / 8.0 mm, correspondence settles in 16 / 18
  iterations, mouth hole found (12 / 20 vertices). Orc male on Starfield's head (race_view, rendered here): ears,
  brow, underbite and open jaw all come through. Largest moves where expected: elf / orc ears 3-5.6 cm; outside the
  region masks at most 3.1 cm (Bosmer / Dunmer / Altmer male, 4-6 % of the total), fine for the region split.
* **Mouth probe: two frame faults, fixed.** (1) Starfield's teeth came out 1.59 m from the mouths: their .mesh
  points are in the teeth shape's frame and need its node transform (as the head). (2) Some Skyrim shapes have an
  identity NiSkinData overall transform while their vertices are in bone space (checked on vanilla eyesmale.nif
  and maleheadargonian.nif: 120 units low); facefit.skyrim_model_matrix now goes through the most-weighted bone
  (bone world x skin->bone), equal to the old route on human heads (0.0 difference on malehead.nif). Found too:
  **Starfield's teeth are weighted to C_Head only** (no jaw bone), so they open with the face through morphs, not
  bones; the probe now reports the teeth morph record's performance / chargen morph.dat keys and which drop the
  lower teeth (the jaw keys a Skyrim mouth would need).
* **Beast probe:** the same bone-space fault put the eye landmarks (and the whole male Argonian head) 120 units
  low, so the male Argonian warp failed (median 128 units); fixed with the head / eye model matrix above. Khajiit
  jaw weights already separated (moving 0.29 / 0.22 vs still 0.01 / 0.002). Rerun needed.
* **Rerun, same evening.** Beast probe fixed: Argonian male warp median ~0.9 units (was 128); Khajiit jaw moving
  0.31 / 0.28 vs still 0.02; Argonian jaw weaker (0.088 / 0.035 vs 0.013 / 0.024). Mouth probe: the Skyrim mouths
  now sit right (orc mouth vs head surface difference p95 3.9 cm, was 9.9 cm) but Starfield's teeth stayed 1.58 m
  off: the teeth's own node was the wrong fix. Their .mesh is in C_Head's frame (x up) and the probe placed only the
  head through the head's node. Now teeth -> head mesh through the two C_Head binds (inv(B_head) B_teeth), then the
  head's node (mouth_probe.teeth_placement; candidates reported, the first inside the head's box used). The teeth
  morph deltas are in the same frame: jawLeft / jawRight showed on z and jawOpen ~0, so the drops are now measured
  after that rotation. Rerun needed.


- 2026-11-10 showlooksmenu as the Orc player (S2SOrcPlayer.esm on an existing save) crashed when hovering facial
  hair. Owner's dump (`npc_record_diff.py --type HDPT --find beard --show beard`): the 19 vanilla beards each name
  `RNAM 0024A024` = FLST HeadPartsHumanRace, their valid races; S2S_OrcRace was not in it. race_heads now writes an
  override of that list (each head-part race list holding HumanRace) with the new races added
  (`head_part_race_lists` in race_heads.json). Rerun needed. If it still crashes: the beard's own morph
  (MNAM 00160B9E) may lack the Orc phenotype keys.

- 2026-11-10 Rerun after the list fix: no crash on facial hair (owner). But the player did not look Orc (a race
  change keeps the face recipe; the Orc shape was only an extra blend option), and "many of the sliders cant be
  changed now" (screenshot: the Face tab's head-shape row had no name). Owner: "Why arent we adding the changes we
  made to this race". Changed: the race shape is now baked into the race's own head (race_heads --race-shape baked,
  the default): `meshes\s2s\races\orc\<sex>head.nif` + its meshes under `geometries\`, head parts
  S2S_OrcRace_<sex>_Head, the race's chargen lists left as HumanRace's (no Orc phenotype or extra morph-group
  entries). The S2SRace_OrcRace_* NPCs use that head without blends; the player patch gives the player that head.
  Rerun needed. Open: whether an existing save's player takes the new head part from the patch (the save may keep
  its own head part list), skin tone, tusks, eyes.

- 2026-11-10 First look at the baked Orc head (owner, screenshots): the preset gives the Orc head (the owner added a
  green skin tone from a Star Wars aliens mod). Open: the face rows read "U", "Z" or a single mark, their region
  shape pads and the eye shape do not move (colours do), vanilla eyebrows clip into the Orc brow, the mouth hangs
  open over human teeth. No "More Sliders" plugin or head morph.dat override found in the owner's MO2 mods.
  Found (xEdit wbDefinitionsSF1, RACE "Chargen and Skintones"): per sex NAM0, NNAM, RPRM / RPRF "Race Presets" (NPC
  FormIDs), morph groups, phenotypes (FMRN localized), FDDS, then FDSI / FDSL "Face Dials" (index + localized
  label). So (1) copied localized labels in our non-localized plugin are read as text: the garbled row names; (2)
  race_heads' presets went in as FDSI / FDSL, i.e. extra face dials labelled with NPC FormIDs. Fixed: copies get
  their text from Starfield's string tables (race_heads.load_lstrings / delocalize: FULL, DESC, FMRN, FDSL, MPPN),
  presets go in RPRM / RPRF, and the baked race head part is the vanilla head part with only its model changed
  (vanilla morph record), so the race's chargen is the human one. Whether the locked pads came from (2) or from
  elsewhere: rerun and look.

- 2026-11-10 Face parts follow the race head (owner: "hard to test ... without the eyebrows, eyes, beards, and teeth
  with baking"). race_heads (--race-shape baked) now bakes every face head part HumanRace offers (HDPT types right /
  left eye, eyelashes, eyebrows, facial hair, teeth, jewelry, per xEdit's SF1 enum; plus their extra parts) per sex
  and race: `meshes\s2s\races\<race>\parts\<part>_M|F.nif` + meshes. Each part's frame is found through its skin
  binds (inv(B_head) B_part for a shared bone, C_Head first, both conventions, the one closest to the head surface;
  identity if unskinned), every part point moves like its nearest head vertex, LODs by nearest LOD 0 vertex; shapes
  more than 0.25 m (median) from the head are left. Records: copies S2S_<Race>Race_<part>_M|F (this sex only) on the
  list S2S_HeadParts<Race>Race; the race's default head parts and its NPCs / the player patch use the copies; the
  vanilla face parts now name S2S_HeadPartsHumanOnly (HeadPartsHumanRace's vanilla entries) so our race offers only
  its copies; hair and the other types stay shared (HeadPartsHumanRace with our race added). Per-part frame and
  distance in race_heads.json (baked_heads.<race>.<sex>.parts). Not yet: eye textures / colours per race, tusks.
  Note: races of other mods added to HeadPartsHumanRace lose the vanilla face parts while this plugin is loaded.

- 2026-11-10 Two more from the baked-head look:
  * Sculpt pads (thin / round ...) did nothing on the Orc head. Our race head had no `_facebones` twin: actors with
    face bones (the player, named NPCs) are drawn from `<model>_facebones.nif` (hair_pack's finding; HDPT model flag
    "Has FaceBones Model" in xEdit's SF1 defs), and the sculpt dials move face bones. race_heads now bakes the twin
    of the head and of each face part (when vanilla has one), and copies the facial bone regions file under the
    race's name (`s2s_orcracefacialboneregions<sex>.txt` next to `humanrace...`; hypothesis: looked up by race
    EditorID, unverified). race_heads.json: baked_heads.<race>.<sex>.facebones_twin.
  * Eyes (owner: Skyrim's elf eyes tilt more than the lids): eyes are now moved as one piece with their socket: a
    similarity (turn, scale, move) fitted from the head vertices within 1 cm of the eye before -> after the race
    shape (headbake.rigid_displacement; turn_deg / scale per eye in race_heads.json), instead of per-vertex moves
    that bend the eyeball. Next: compare with Skyrim's own race eyes (its eye models' race morph, if any) and the
    eye textures per race.

- 2026-11-10 (owner away): race_heads --new-races takes any known race with the baked shape (no need to be in
  --races, which only picks the morph keys and the test NPCs), short names too (Orc, HighElf, Altmer) or `all` (the
  ten: Nord, Imperial, Breton, Redguard, Altmer, Bosmer, Dunmer, Orc, Elder, Dremora). Each new race's height (RACE
  DAT2 male / female, xEdit SF1) = HumanRace's x Skyrim's height for the race / Skyrim's ImperialRace
  (race_heads.skyrim_heights reads Skyrim.esm's RACE DATA at 16 / 20 like race_survey; --race-height human to keep
  HumanRace's). race_heads.json: skyrim_heights, new_races.<race>.height_factor.

- 2026-11-10 Orc teeth and tusks (owner: "yes" to the tusks; races plan step 3; plan from the 2026-11-09 mouth probe
  run in decisions.md). scripts/npc/race_mouths.py: Skyrim's MouthOrc.nif / MouthOrcFemale.nif shapes merged into one
  (one morph record drives one shape), placed with race_heads' head alignment (the Skyrim orc mouth belongs to the
  Skyrim orc head, which our race head carries), taken into the vanilla teeth's mesh frame through the C_Head binds
  (headbake.part_to_head), jaw / upper per vertex from Skyrim's Aah; every key of the vanilla teeth's performance
  (TMPP) and chargen (TCMP) morph.dat copied from the nearest vanilla tooth vertex on the same side (jaw -> the
  vertices jawOpen moves), so the lower teeth and tusks drop when the mouth opens. NIF like the vanilla teeth (C_Head
  with its bind and node), material from Skyrim's texture set (SkyrimConverter: needs texconv and the Creation Kit's
  ContentResources.zip; else the vanilla teeth material, which will not fit the orc UVs). race_heads (--race-shape
  baked, races in race_mouths.RACE_MOUTHS = Orc) writes `meshes\s2s\races\orc\mouth_m|f.nif`, morphs under
  `meshes\morphs\s2s\races\orc\mouth_m|f\performance`, a copy of the vanilla teeth's MRPH (TMPP / TCMP ours, MOBC
  vertex count ours) and of the teeth part (S2S_OrcRace_Mouth_M|F) on the race's list; every vanilla teeth part of
  that sex maps to it (race defaults, NPCs, player patch); the baked teeth copies are skipped for that race / sex.
  race_heads.json: mouths. Unverified in game (does the game take a performance morph.dat of our own for teeth?).

- 2026-11-10 scripts/npc/look_probe.py (read-only, owner away): how Starfield stores skin tones and eye colours, for
  per-race tones (Orc green, Dunmer grey ...) and eyes (Dunmer red, Altmer gold). HumanRace's per-sex chargen strings
  (FDDS skin tone AVMS subtype, BSTT / HSTT / FSTT, FCTP; xEdit SF1), the AVMD ("AVMS Data") records they name,
  followed through their LNAM / VNAM entries; every eye head part on HeadPartsHumanRace with its NAM2 colour mapping
  (AVMD) and TNAM texture set; the same for each --plugin (the Star Wars aliens mod with the green skin the owner used:
  how a mod adds tones). Unverified which names resolve; the run shows it.

- 2026-11-10 Races roadmap A (docs/npc/races-roadmap.md): race_heads keeps a FormID ledger (`race_formids.json` in
  --out, EditorID -> object id; rebuilds reuse it, so S2S_OrcRace and the rest keep their FormIDs for saved games;
  the first ledger run allocates in the same order as before). Every FLST holding HumanRace gets our races (was:
  only the head parts' valid-race lists). GetIsRace(69) HumanRace conditions in CNDF / IDLE / CPTH overridden to take
  our races (race_condition_patches; race_heads.json: race_condition_patches). The 14 INFO conditions remain.

- 2026-11-10 NPCs on their converted race (races roadmap I; owner: Faendal with the Bosmer head). face_fit
  `--races-plugin "$mods\S2S Race Test\S2SRaceTest.esm"` (race_heads.json beside it; race_heads now writes each new
  race's EditorID there): an NPC whose Skyrim race was converted is fitted against Skyrim's base head WITH its race
  morph (Maleheadraces.tri / Femaleheadraces.tri, .tri vertices matched to the NIF's by position), so only its own
  features go into the dials; in S2SFaceTest.esm it gets RNAM = S2S_<Race>Race and its head parts swapped for the
  race's (head, baked face parts by vanilla EditorID, the race mouth for teeth); S2SRaceTest.esm becomes a master.
  faces.json: per NPC `race`. Unverified: the Riverwood build (PluginSpike) with NPCs whose race is in another plugin.
- 2026-11-10, owner's first Orc run stopped printing after the two mouth lines (no error): the face-part baking came
  next with no progress output, and every vanilla file read (hkx_to_af.vanilla_file) reopened and searched every
  mesh archive's name table - thousands of reads for the parts, their `_facebones` twins and LODs. Archives are now
  opened once per run (exact-name lookup in the archive's own index), and the baking prints "baking N face parts"
  and a count every 25.
- 2026-11-10, owner's first in-game look at the baked Orc: the player (setrace) has the baked head (pointed ears,
  wider jaw) and the converted tusks; the Orc NPCs (S2SRace_OrcRace_male / female) had a plain human head, the mouth
  standing in front of their lips. Cause: the race NPCs are copies of the blend test NPCs, whose Face part is our own
  S2S_SkyrimRaces_<sex>_Head; with_head_part only knew vanilla parts' types, so the copy kept that head ahead of the
  race's. Our head parts are now Face-typed too (the end-to-end test checks a single Face part). Open, to look at
  after the rebuild: on the player the inner lips look pulled into vertical strands around the teeth (the bake's lip
  area or the mouth mesh), the tusks are pink in the looks menu and dark in the world (material).
- 2026-11-10, owner's race_view comparison (race_probe): the male Orc's open underbite matches Skyrim's (Skyrim's
  Orc race shape itself parts the lips; the teeth fill it in game). The female's does not: Skyrim's female Orc lips
  barely part from the front, ours gape. New: headcorr.Correspondence.fit_lip_edges (race_transfer, so race_probe and
  race_heads both use it; --no-lip-edges to compare): the lips' meeting rows on Starfield's head (per 2 mm column
  the upper lip's lowest vertex and the lower lip's highest, near Skyrim's mouth edge, not in the pocket) get the move
  of Skyrim's mouth edge on their side, the change fading over their own lip within 15 mm. Reported per race:
  "lips open <before> -> <after> mm (Skyrim <edges>)". Unverified on the owner's heads (synthetic test only).
- 2026-11-10, owner's rerun: the female Orc still gaped; by the report Starfield's meeting rows opened 3.6 mm where
  Skyrim's mouth EDGES part 5.0 mm, yet Skyrim's female looks closed from the front: its upper lip's front comes down
  over the lower. So the target is now the VISIBLE edges: per column the upper lip's lowest point and the lower lip's
  highest, on Skyrim before / after the race shape (6 mm columns over its lip vertices near the mouth) and on
  Starfield (2 mm columns); Starfield's rows get the vertical move of Skyrim's visible edges (forward moves stay).
  Report: visible_opening_m {skyrim_before, skyrim_after, starfield_base, before, after}.
- 2026-11-10, owner: "the female ear difference": in race_view the female Orc's Starfield ear is a flat blade
  straight out (one side in the raw transfer; race_heads' symmetry copies it), Skyrim's keeps an ear's shape. The
  heads are aligned as a whole (~8 mm rms), so the ear is where they are furthest apart and Starfield's ear can take
  the Skyrim scalp's move. New: race_probe.ear_fit, per side an ICP similarity (scale within 10 %, nearest pairs both
  ways) of the Skyrim vertices near Starfield's ear (the head morph's Ears region, off the side of the head) onto
  it, Skyrim's vertices warped by it within 35 mm of its ear (fading over 20 mm) and the race field turned with them,
  before the correspondence. Reported per side: gap before / after, move, turn, scale (--no-ear-fit to compare).
  Both unverified on the owner's heads.
- 2026-11-10, owner's run with both fixes: lips: the female Orc's visible opening now 0.6 mm (was 3.2; Skyrim's
  lips overlap by 1.0 mm), the male's 13.6 mm (Skyrim 11.0: open, as it should be). Ears: ear_fit reported a 25 mm
  gap on both sides, 4 cm moves, 21-34 degree turns, scale at its 0.9 limit: it matched the sides of the heads (the
  Ears region off the side of the head is mostly side of the head; 266-321 of Skyrim's 898 vertices) - no visible
  change. ear_fit is now opt-in (--ear-fit). The viewer also shows the female's other ear sinking into the head
  while one becomes a blade (both ears moving the same way sideways?). Next: race_probe --dump-geometry
  (race_geom_<sex>.npz: both heads, alignment, deltas, regions, transfer; game-derived, never committed) so the ear
  can be examined offline instead of from screenshots.
- 2026-11-11, from the owner's geometry dump (race_geom_<sex>.npz, looked at offline; the first time the heads were
  examined directly instead of through screenshots):
  - race_view.html's label was wrong: the camera looks from +Y, so the Starfield head (placed at x -0.13) showed on
    the RIGHT. The blue, low-poly head both of us had been reading as ours was Skyrim's own: its flat "blade" ear and
    its see-through mouth slit are Skyrim's 898-vertex mesh. Fixed: Starfield on the left, the label names each head
    by colour (tan: Starfield, blue: Skyrim). The 2026-11-10 viewer readings above (blade ear, gaping female lips)
    were of Skyrim's head.
  - The in-game "strands" across the male Orc's mouth: race_heads' --symmetry stronger. Starfield's lips meet with
    their surfaces interleaved, so a lip vertex's mirror partner can lie on the other lip (123 of 1,224 mouth
    vertices on the male); taking the partner's larger move tore the lips into vertical spikes. The raw transfer is
    clean. facefit.symmetrize(faces=...) now keeps a vertex's own move when its partner's mirrored surface faces
    another way (normals' dot < 0.5); the ears still get the stronger side (both 45.6 mm male, 34.2 mm female).
    A few stretched faces remain at the mouth corners (from the transfer itself).
  - The ears are fine in the game build: the raw transfer gives one ear its point (34 mm) and the other less (23 mm),
    and the symmetry gives both the 34 mm one; Skyrim's tip moves 38 mm.
- 2026-11-11, owner's rebuild: the strands are gone (looks menu, front and side); the tusks still pink in the looks
  menu, the mouth dark on the NPCs. Suspect: write_mouths converts only the FIRST Skyrim mouth shape's material
  (skinned_shapes(...)[0]) and the merged mouth uses it for every shape, so the tusks may be sampling the gum /
  tongue texture. New read-only check: python -I scripts\npc\race_mouths.py --skyrim-data <Skyrim Data> prints each
  mouth shape's textures and UV range.
- 2026-11-11, the Orc mouth's colours, from the owner's dump (MouthOrc.nif / .dds, looked at offline): one shape, one
  texture; our converted colour texture is Skyrim's exactly (same mean). Skyrim's texture is very dark (mean sRGB
  (30, 19, 18); the brightest teeth ~(99, 97, 82)), which explains the near-black mouth under Starfield's light; the
  tusks sample the ivory blocks of the lower-teeth row (UVs kept through build_mouth, checked). The converted
  colour is now times race_mouths.MOUTH_ALBEDO_GAIN = 2.5 (--mouth-brightness; 1 = as Skyrim's). Unexplained: the
  tusks drew PINK in the looks menu; rendered with V flipped, the tusks land on the gum / tongue area and come out
  pink, but nothing in our path flips V. --mouth-uv-test replaces the mouth colour with four coloured quarters (red
  top-left, green top-right, blue bottom-left, yellow bottom-right) to settle it in game: red / green tusks = read as
  is, blue / yellow = flipped.
- 2026-11-11, the player's teeth: the records are right (Player PNAM and S2S_OrcRace's default HEAD both name
  S2S_OrcRace_Mouth_M; its HNAM extra part is the tongue, our copy on the player), yet in the looks menu, on new
  games too, the player shows Starfield's teeth (the --mouth-uv-test colours on the NPC, not on the player). Starfield
  has one teeth part per sex (Human_Male_Teeth, Human_Female_Teeth, Human_Child_Teeth); the menu's TEETH row (4
  options) looks like teeth colour (NPC TETC). Starfield's chargen part lists HeadPartsChargenOptionsMale / Female
  hold only vanilla parts. build_plugin now overrides them with every race copy of their entries added
  (chargen_option_lists); human_only_parts already makes the vanilla ones invalid for our races. Unverified.
- 2026-11-11, owner: on a coc'd new game the Orc player already shows the human teeth (and the pink corners) before
  any menu. The player's face on a new game is the first chargen preset's (RPRM / RPRF: HumanRace's vanilla
  ChargenPresetMale02.. NPCs, copied into our race), whose PNAM has Human_Male_Teeth and the human brows / eyes; only
  the head comes from the race. build_plugin now replaces the race's presets with copies on the race
  (race_preset_copies: RNAM ours, Face = the race head, the other parts = the race copies). Unverified.
- 2026-11-11, preset copies in (10) and the chargen lists extended: the player still showed no test colours, NPCs
  did. Difference: the teeth part is flagged "Has FaceBones Model" (FLLD 1, copied onto our mouth part), and actors
  with face bones (the player) are drawn from <model>_facebones.nif, which we never wrote for the mouth (the head and
  face parts got their twins). convert_mouth now writes mouth_<sex>_facebones.nif (the same NIF). Unverified.
- 2026-11-11, --mouth-on-head: the player still showed no Orc mouth. nif_parts on the owner's game: the vanilla
  malehead_facebones.nif holds only the head (53 faceBone_* bones; no teeth inside), teeth.nif is skinned to C_Head
  and teeth_facebones.nif to faceBone_C_TopTeeth / faceBone_C_BottomTeeth. Our mouth's twin was a copy of the
  C_Head NIF: the player's face-bone rig (what the twins are drawn on) would have nothing to bind it to. The twin is
  now skinned like vanilla's (race_mouths.facebones_mouth: jaw vertices on BottomTeeth, the rest on TopTeeth, the
  vanilla twin's binds); the build prints "_facebones: teeth bones". Unverified.
- 2026-11-11, the facebones twin skinned to the teeth bones: no change on the player. Re-read of the screenshots: the
  player's "pink tusks" have our mouth's shape (tusks rising at the corners, the gapped upper row) - the player draws
  OUR geometry, in white teeth / pink gums: the human teeth texture on our UVs (the tusks sample a gum area of it).
  So the player's mouth material is replaced; suspect: the looks menu's TEETH row (four teeth colours, NPC TETC)
  swaps a Teeth-type part's material on the player. Test: --mouth-type 0 gives the race mouth another HDPT type.
- 2026-11-11, **verified in game:** with --mouth-type 0 the player's looks menu shows the Orc mouth in the UV-test
  colours (red / green tusks): the player had drawn our mouth all along, in the human teeth material, because it was
  a Teeth part (the looks menu's teeth colour swaps a Teeth part's material). The race mouth is now type 0 by
  default (MOUTH_PART_TYPE). To check next: the mouth moves when talking (its morph record is the vanilla teeth's,
  copied), and the looks menu's TEETH row with no Teeth part.
- 2026-11-11, **verified in game (owner):** the Orc mouth as a misc part shows ivory tusks / teeth on the player
  (looks menu) and NPCs, and drops with the jaw when the NPC talks (its morph record, the vanilla teeth's copy, still
  drives it). The looks menu's TEETH row now changes nothing (no Teeth part on the race; harmless).
- 2026-11-11, owner: test the Orc's skin tone before building every race. Plan: Skyrim's skin tones are tint presets
  (RACE tint mask type 6, colours from CLFM records); Starfield's are AVMD groups of 9 colour textures (body / hands /
  per-phenotype face). An Orc race of ours would name its own groups (BSTT / HSTT / FSTT strings) holding recoloured
  copies of the vanilla tone textures, tinted to Skyrim's Orc presets. First: scripts/npc/skin_tone_probe.py
  (read-only) lists Skyrim's presets per race and Starfield's tone groups with their texture sizes / formats.
- 2026-11-11, skin_tone_probe on the owner's game: Orc presets male (89,113,92) .. (41,47,36), female (94,138,124) ..
  (61,82,73); Starfield's tone groups name 9 textures sk0..sk8 each: body / hands 1024 BC1 sRGB with mips, faces
  1024 uncompressed RGBA8 sRGB, one mip; HumanRace's strings name the groups by TNAM (BSTT
  Male_Naked_Body_Skin_Tones, HSTT Male_Hands, FSTT FaceSkinTones = ComplexGroup_FaceSkinTones, which lists the
  per-phenotype face groups). race_heads --skin-tones OrcRace (src/fo4sf/skintone.py): the race gets copies of the
  adult tone groups (S2S_Orc_..., children's and the mannequin's left out) and its BSTT / HSTT / FSTT renamed to
  them; each copy's textures are the vanilla ones recoloured (per pixel: the slot's colour times the pixel's
  luminance over the texture's median, in linear light; alpha kept), the slot's colour from a 9-step ramp through
  Skyrim's presets, given to the slots in order of the vanilla textures' brightness. Size: 54 textures (body and
  hands 9 per sex, BC1 via texconv when found, else uncompressed; faces 9 per sex shared by every phenotype, made
  from <sex>_default's: the phenotypes' age detail is lost on the Orc). The complex group's layout is unread; the copy
  points every string / FormID naming a copied group at the copy (the build prints how many). Unverified.
- 2026-11-11, **in game (owner):** with the textures installed, --skin-tones takes effect: the Orc player's hands are
  green (tone 3); the face (tone 1) is very dark, brownish rather than green, with orange specks. Not yet known why
  the face differs (its tone textures may be blended with something, e.g. by their alpha, or be more than a colour
  map). scripts/npc/skin_tone_preview.py: vanilla vs our tone textures side by side with numbers (median colour,
  brightness spread, alpha range) to find out.
- 2026-11-11, skin_tone_preview on the owner's game: every tone texture's alpha is 255 (no blend mask); our face
  textures hold the intended colours (male face sk0 median (89,113,92), as the hands). So the face's dark brown look
  in game is not in our texture: the game does something more with the face tone texture (e.g. multiplies it with
  another, human-coloured map) - unverified. Two changes: --skin-tone-mode relative (new default): each vanilla tone
  texture times race / human Skyrim preset colour of the same rank (human = NordRace's presets; Skyrim lays both over
  the same kind of base skin), per channel in linear light, so Starfield's brightness and colour variation stay
  (measured medians: male face sk0 (240,192,153) -> (109,124,83), sk4 (182,144,104) -> (141,147,107); absolute gave
  (89,113,92) / (80,92,82)). --skin-tone-test: slots sk0 / sk1 / sk2 solid green / white / grey on body, hands and
  face, to see in game what the face does with a tone texture's colour (white shows the extra factor directly).
- 2026-11-11, **in game (owner), --skin-tone-test with our own groups:** the face stayed the same dark brown-black on
  every tone, the test colours (green / white / grey) included: the face drew none of our face textures (the
  race_heads report shows the face complex group copied right: 22 entries, LNAM phenotype key -> VNAM our simple
  group's EditorID). look_probe with the Star Wars alien mods (whose green faces work): they add no adult race; they
  override HumanRace's own tone groups (body, hands, every face phenotype) with 18 entries instead of vanilla's 9,
  the new ones named like vanilla's (male_eu_md1_sk9_color ...). race_heads --skin-tone-method append (new default):
  the same for our race, the Orc's 9 tones appended to the vanilla groups (textures under our folder; the race
  keeps HumanRace's strings; every phenotype's face entries share one set per sex). Collides with the alien mods
  (both override the same records; the later plugin wins): test with them off. Unverified.
- 2026-11-11, **verified in game (owner), --skin-tone-method append:** the skin tone row has 18 tones; the face
  follows ours exactly (test tones 10 / 11 / 12: flat green / white / grey face, so the face tone texture is used as
  it is), and tones 13-17 (relative mode) give an olive-to-deep-green Orc face. The menu counts from 1 (tone 10 = the
  first appended, index 9). Follow-ups made: slot k now takes the k-th lightest vanilla texture (vanilla's slots are
  not in brightness order, so 15 came out lighter than 13 / 14), and the race's test NPCs and the player patch get
  STON = first appended index + 4 (a middle Orc tone). Known: the Star Wars alien mods append to the same groups
  (whichever plugin loads last wins); every phenotype shares one face set per sex.
- 2026-11-12, **in game (owner):** the Orc test NPCs' bodies and hands are green, their faces human (each copies
  its template's baked face textures). bake_faces now recolours the colour texture of the new race's NPCs (not the
  HumanRace blend NPCs) like the tones (skintone.relative at the NPCs' tone, STON first + 4), written uncompressed
  (formats other than RGBA8 / BC1 decoded through texconv). Also seen: the female Orc player's tusks stick out
  through her closed lips (her mouth opens 0.6 mm; male 13.7) - open.
- 2026-11-12, **owner:** every preset has the tusks, but only one male preset looks Orc (our NPC, which has no
  morph blends); the female body type is a normal human preset face with tusks. The preset copies kept their human
  morph blends (BMPN / BMPV), which reshape our baked head back to a human face. race_preset_copies now drops them
  when the race's shape is baked (face dials kept, so presets still differ by their dials and colours). Unverified.
- 2026-11-12, **owner, after the blend fix:** Orc NPC faces now green but lighter / yellower than the body; the new
  game's profiles (Personnel record) and the female body type still show a plain human head with our tusks; only
  the player's own (patched) preset is Orc. So the menu's presets are not the race's RPRM / RPRF copies, and a
  preset's own Face part wins over the race's head. Changes: the vanilla Face parts valid for HumanRace's part list
  (human_faces) join human_only_parts (valid for HumanRace's list without our races; expected: the game falls back
  to the race's head part, unverified - risk: no head at all); the NPCs' baked face colour is now matched to the
  median colour of the race's face tone texture at their tone (skintone.match_median) instead of Skyrim's preset
  ratio. The chargen profiles' human eyes / brows are already race-only through the part copies.
- 2026-11-12, **owner:** with the human Face parts made human-only, Body Type 2 on the (Orc) player still gives a
  human female head (round ears) with our tusks: the menu does not swap an invalid Face for the race's. The only
  preset that looks Orc is the player's own record (the player patch puts our head on it), so the body-type switch
  likely picks the Face for the new sex from the player record's parts: the patch now lists both sexes' race heads
  (head parts carry a male / female flag). Unverified.
