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

