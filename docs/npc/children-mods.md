# Children: which Skyrim child mod to convert from (2026-11-17)

Owner: "skyrims children are quite ugly, if we were gonna convert children in game it should be based on one of
these". Read here, for the format only (files unpacked outside the repo, nothing run from them): SkyChild 3.1
(Nexus 128779), RS Children Overhaul 1.1.3 + hotfix 1 (Nexus 2650), Realistic RS Children 4.5 + 4.7 update
(Nexus 39359). Facts below are **verified** from their files (our BSA / NIF / plugin readers) unless labelled.

| | RS Children Overhaul | Realistic RS Children | SkyChild |
|---|---|---|---|
| What it is | Skyrim's child races rebuilt: kids' skeletons (per sex), own head, hairs, eyes, brows, face marks, children's clothes; NPC faces | face-only overhaul ON TOP of RS Children Overhaul: a new face per child (freckles, moles, red noses), hair colours from the parents | standalone: four child races of its own (SkyChildNordRace ...), own skeletons, bodies, high-detail heads, clothes |
| Files | RSkyrimChildren.esm (8 RACE, 96 HDPT, 27 ARMO / 31 ARMA, 13 OTFT), RSChildren.esp (4 variants), 2 BSAs | RealisticRSChildren.esp (45 NPC_, 42 HDPT), 50 FaceGen meshes, 47 face textures, hair textures | SkyChild.esp (5 RACE, 43 NPC_, 17 HDPT, 19 ARMO / 24 ARMA), one BSA (457 MB unpacked, 454 textures) |
| Needs | Skyrim + Hearthfires + Dragonborn | Skyrim + DLC, USSEP, RS Children Overhaul, KS Hairdos (its hair head parts point at `KS Hairdo's\*.nif`, not shipped) | Skyrim + DLC only |
| Children with baked FaceGen | 44 (39 Skyrim, 4 Hearthfires, 1 Dragonborn) | 46 (41 / 4 / 1) | 44 (39 / 4 / 1) |
| Dorthe 013477 / Frodnar 01347E | both | both (race NordRaceChild 02C65B, height 1.0) | both (race SkyChildNordRace, skin ARMO of its own, no head parts: head from the race / FaceGen) |
| Head mesh (base for our face fit) | `ranaline\character assets\childhead.nif`: shape 'FemaleHead', 996 vertices / 1,706 triangles = Skyrim's adult female head topology | the same RS head | `skychild\malehead.nif` / `femalehead.nif`: 3,832 / 3,662 vertices (custom) |
| Races | overrides of the vanilla child races (Nord / Imperial / Redguard / Breton + vampires), skeletons `skeletonkids.nif` / `skeleton_female_kids.nif`, height 0.8 | the RS ones | new races, `skychild\skeleton.nif` / `skeleton_female.nif`, height 0.8 |

## What it means for our converter
* Faces: facefit takes FaceGen head minus the NPC's base head (same topology) and carries the difference onto
  Starfield's head through a geometric alignment (nearest vertices), so any of the three works once its base head is
  read. RS's base IS Skyrim's adult female head layout, the case the adult pipeline already handles; SkyChild's
  custom heads need nothing new in principle (supported), only a first check of the alignment.
* Starfield's child heads share the adult head's topology (races-roadmap I2), so the transfer target is known either
  way; body and skeleton come from Starfield's ChildRace (the mods' skeletons only matter for fitting their clothes).
* Hair: npc_hair converts each NPC's hair head-part MODL. Realistic RS Children's hair parts point into KS Hairdos
  (not in the mod: needs KS Hairdos installed, or the hair shapes taken from the FaceGen NIF, where they are baked in
  verified: e.g. Dorthe's 'MellowDUPLICATE001', 23,628 vertices). SkyChild's NPCs have no hair head parts: hair is
  only in the FaceGen NIF (SkyChildHairFemale ...), so the same FaceGen route is needed there.
* Load order: our Skyrim side reads Skyrim.esm (+ --skyrim-overrides for loose hair files). Any of these needs the
  mod's plugins (overrides over Skyrim.esm, later wins), BSAs and loose files read too: races-roadmap K ("build from
  the user's load order") for the Skyrim side.
* Clothes: RS Children Overhaul and SkyChild both bring children's clothes (outfits on the child body); Realistic
  RS Children uses RS's.

## Decision (owner, 2026-11-17): Realistic RS Children
Converted children take Realistic RS Children's faces over RS Children Overhaul's heads, races and clothes.
Plan, in order:
1. Skyrim load order on our Skyrim side: `--skyrim-mod <folder>` (repeatable, in load order): each folder's plugins
   override Skyrim.esm's records (later wins, FormIDs through each plugin's master list), its BSAs and loose files
   win over Skyrim's archives (as --skyrim-overrides does for loose files). Here: RS Children Overhaul (core +
   "Non Playable - USSEP" RSChildren.esp, the variant Realistic RS Children is made against: it lists USSEP as a
   master), then Realistic RS Children 4.5, then its 4.7 update. USSEP and KS Hairdos need not be read: no record we
   convert needs them (supported; the hair comes from the FaceGen NIF, step 3).
2. S2S_<Race>ChildRace per Skyrim child race over Starfield's ChildRace (races-roadmap I2 step 2), and face_fit for
   child NPCs: base head = the RS child head (Skyrim's adult female layout), FaceGen = Realistic RS Children's.
3. Hair from the FaceGen NIF's hair shapes (not the KS Hairdos head-part meshes).
4. Children's clothes from RS Children Overhaul's outfits; then voices and packages (races-roadmap I2 steps 5-7).
First target: Dorthe and Frodnar in Riverwood.
