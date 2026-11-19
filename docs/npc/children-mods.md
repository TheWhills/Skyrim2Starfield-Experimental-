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

## Built 2026-11-19: step 1, Skyrim with mods over it
src/fo4sf/skyrimload.py (tests/test_skyrimload.py): LoadOrder(skyrim data, [mod folders]) reads Skyrim.esm, the
vanilla masters the mods name that are in Data, then each folder's plugins; one FormID space (top byte = index in
the order, Skyrim.esm 0), each plugin's FormIDs mapped through its masters, the last plugin's version of a record
wins (FormID fields of NPC_ / HDPT / RACE / OTFT / ARMO / ARMA rewritten: FID_FIELDS); FaceGen paths by the plugin
that defines the NPC; assets: the mods' BSAs after Skyrim's, their loose files over everything (case-insensitive).
face_fit takes `--skyrim-mods-dir <MO2 Skyrim mods> --skyrim-mod <folder>` (repeatable, in load order).
child_faces: a child's base head is its race's Face head part (child_faces.base_head_path), so RS's races use RS's
child head.
Checked on the mod files here (verified, with a stub Skyrim.esm): with RS Children Overhaul (core + Non Playable -
USSEP RSChildren.esp), Realistic RS Children 4.5 and 4.7: Dorthe and Frodnar come from RealisticRSChildren.esp on
NordRaceChild (RSChildren.esp's version: Face part 0RCOChildHeadNord, ranaline\character assets\childhead.nif from
RSChildren.bsa, 996 vertices); their FaceGen heads (loose in Realistic RS Children, under Skyrim.esm) have 996
vertices; their hair parts are KS Hairdos meshes (Mellow, Chain Reaction: not shipped, step 3); eyes and brows from
RSkyrimChildren.esm.
Next: the owner's face_fit run with Dorthe and Frodnar (OWNER-SETUP 7k), then hair from the FaceGen NIF (step 3).

Owner's first run (2026-11-19, verified from its output): load order Skyrim, Update, Dawnguard, HearthFires,
Dragonborn, RSkyrimChildren.esm, RSChildren Patch - BS Bruma.esp, RSChildren.esp, RealisticRSChildren.esp (BS
Bruma's masters and USSEP not loaded); Dorthe / Frodnar fitted on RS's child head (996 vertices). But their FaceGen
heads carry a near-identity skin transform where RS's child head carries the head bone's (120 units up), so in model
space each face sat 120 units below its base (checked on the mod files). Fixed: the FaceGen's mesh-local points go
through the BASE head's matrix (child_faces.facegen_points); the faces then differ from the base by 0.57 / 0.43 units
rms (Dorthe / Frodnar), about 9 / 7 mm. The fit cache now keys adults without the child code (a child change refits
only children).


## Built 2026-11-19: step 3, hair from the FaceGen NIF; the child skin tone by lightness
Owner's in-game check after the fix (verified): Frodnar is child-sized with his own face, but wears the template
child's curly hair and outfit, and his skin is darker than Realistic RS Children's Frodnar (owner's Skyrim
screenshot: fair skin, blue eyes, blond chin-length hair, grey tunic).

Hair (scripts/npc/child_hair.py, face_fit.add_child_hair_files; tests/test_child_hair.py). Verified on the mod
files: a FaceGen NIF holds every head part as a shape named after the part's EditorID (Frodnar:
0ChainReactionDUPLICATE001 + its HL copy + 0_HAIRLINE_Male_Human_CurlyScalpDUPLICATE002; Dorthe: 0MellowDUPLICATE001
+ HL + 0_HAIRLINE_Female_Human_StraightDUPLICATE001), in model space with an identity skin transform, in the same
space as the FaceGen face taken through the base head's matrix (hair z 115..133 units over a face at 110..132).
So a child's hair = the shapes named after its hair head part and that part's extra parts, placed by the child's
own face alignment (Skyrim model -> Starfield child model: a scale and shift; checked exact on Frodnar's NIF), then
skyrim_hairs.build_part with the vanilla Skyrim hairs' settings (no hairline lift / volume / drape: the hair was
made for this head; KS's HL copy dropped, cards outward, followed and pushed out against the child's baked head,
Starfield's hair shader, _facebones twin from the template child hair's twin), on Starfield's child skeleton
(Actors\Child\CharacterAssets\skeleton.nif). Written as S2S_ChildHair_<EditorID>, a copy of the template child's own
hair head part; the colour is the NPC's Skyrim hair colour matched to a Starfield name (as the adults). Packed as
S2SFaceTest - Main.ba2 / - Textures.ba2. Needs --texconv; without it the children keep the template's hair
(reported). Rebuilt every run (not in the fit cache).
Textures: Realistic RS Children ships only 5 KS Hairdos textures (Bourbon, Dune, Fusion, North, Sabrina; verified);
Chain Reaction, Mellow and the KS hairline scalps come from KS Hairdos (SSE: Nexus 6817; the SMP version and
retextures use the same texture paths), added with --skyrim-mod. A child whose textures are missing keeps the
template's hair and the report says which file.
Unverified until the owner's run: that the child skeleton's C_Head matches the child head mesh's space (the report
gives C_Head and each hair's fit gaps), that Starfield's child hairs have a _facebones twin to copy (reported under
child_hair.facebones), and how the hair looks.

Skin tone: Frodnar's Skyrim skin (tint 183,156,145) gives STON 2 on the adult scale, child tone 0 (the lightest of
three), and Dorthe's 0 too; but Starfield's adult tone slots are not in brightness order (races.md 2026-11-11), so
slot 0 need not be the lightest child tone (supported hypothesis for the darker skin). face_fit now orders
ChildRace's body tone group's textures by median lightness (child_hair.child_tone_slots, the BSTT string of the
sex -> its AVMD's VNAM textures) and gives each child the slot of its rank; faces.json: child_skin_tones and each
child's child_tone.
Owner's run 2026-11-19 (verified from faces.json): load order with KS Hairdos SMP, the Salt and Wind retextures and
Realistic RS Children 4.5 from C:\Modding\work\child mods. Dorthe's hair built (Mellow + its straight hairline, the
HL copy dropped; Skyrim HairColor06Auburn -> Starfield "Amber"; median gap to her baked head 8-16 mm by region,
Skyrim's own 13-20 mm). The template hair whose _facebones twin was copied is Human_Female_Hair_Bob (Bob_F, an adult
hair worn by the template child COM_Quest_Sona); Starfield's child skeleton has C_Head where the adult one has it
(0, -0.0018, 1.6323 m), so the adult face-bone frames fit. Frodnar's was skipped: KS Hairdos SMP has no
textures\ks hairdo's\hairline\scalp.dds (his scalp layer). Now a layer whose texture is missing is left out
(faces.json hair.left_out) and the hair built without it; only a missing hair texture keeps the template's hair.
Skin tones: ChildRace's body groups (Child_Male_Body_Skin_Tones / Child_Female_Body_Skin_Tones, the same three
textures) by median: slot 1 (164,126,103), slot 0 (139,109,82), slot 2 (79,65,49), so slot 0 was the middle one
(the darker skin seen on Frodnar); both children now STON 1.
Correction (owner, 2026-11-19): that run's KS textures came from KS Hairdos SMP plus the Salt and Wind retextures
(and VIGILANT - Alessia Replacer), which the search took because they hold textures\KS Hairdo's - not asked for.
Realistic RS Children is made against the regular KS Hairdos SSE; the search now takes only that, its .7z unpacked
in C:\Modding\work\child mods and found by its plugin (no retextures, no SMP repack).
Owner, 2026-11-19 (in game, KS Hairdos SSE build): "Is Frodnar using a black ethnic template? His features seem
that way." His test NPC copied EncChild01Template, picked by EditorID alone; the face skin (Dermaesthetic layer)
comes from the template, and the adults' templates have been picked by face skin ethnicity since 2026-11-12, the
children's not. Now child_faces.pick_child_template prefers (owner, same day: "all children should get the european
face style because skyrim's sliders work on the default european looking base"; every race, Redguard too) templates whose face layers name european, then ones naming none; faces.json lists
every child template with its face skin (child_templates) and each child's (test_npc.face_skin). Unverified: how
Starfield's child face textures are named (the regex looks for european / african / asian anywhere in them). The
rest of the look is the head: Starfield's Child_Head_Boy plus only Frodnar's difference from RS's base child head.
Owner's faces.json after that (2026-11-19, verified): none of the 22 vanilla child templates (11 per sex:
EncChildFaceM01-06 / F01-06, EncChild01Template, HT_GenericKid_M01 ...) has a face layer at all, so the template's
face skin is not what made Frodnar look African; the template pick by ethnicity stays (harmless) but decides
nothing. What a child's face is made of is then its head part (ours: Child_Head_Boy + his own difference), its STON
and the race's face tone textures. faces.json now lists each child template's STON, hair colour and head parts
(how vanilla children differ from each other: perhaps a face head part of their own) and ChildRace's face tone group
(FSTT) next to the body one (the face's slots may run another way than the body's). Frodnar's hair colour came out
HairColor01PlatinumBlond -> "Platinum" (same name), measured (117, 90, 61), a light blond; in game his hair read
grey-white: unresolved (Dorthe's "Amber" shows whether a child's hair takes its colour at all).
Owner's childlooks (2026-11-19, verified): the 22 vanilla child templates carry no face head part, no face layer
and no face field at all (only MRSV on the two audio-only ones); they differ ONLY by STON (0 / 1 / 2), hair head
part and hair colour (e.g. EncChildFaceM01 / HT_GenericKid_M01: STON 2, Afro_Curls, Brown; EncChildFaceF03 / F06:
STON 1, Bob, Platinum). So every vanilla child wears the race's one child head, and its ethnic look is the face
tone of its STON plus its hair. ChildRace's FSTT string (SimpleGroup_FaceSkinTones_Child_Female) matched no AVMD by
EditorID / TNAM / YNAM: the lookup now tries every text field and else lists the child AVMD EditorIDs.
--child-controls: each child also as copies with Starfield's own child head (our Face part left out) and with its
head at STON 0 / 1 / 2, to tell in game what the head shape does from what the tone does.
Owner's survey of every ChildRace NPC (2026-11-19, verified, 45 listed): the generic children (EncChildFace*,
LvlChild*, colonist / tourist kids) have no face head part and no face layer - only STON, hair and hair colour.
Cora Coe has head parts of her own (Human_Child_Head_CoraCoe, her own brows and lashes). Three children carry a face
skin layer, all with ADULT Dermaesthetic textures: UC_NA_BobbyKatz (European_Male_Md1_Sk1, STON 0),
UC_NH_SylvieMunich (European_Female_md1_Sk1 + ComplexionMask1 Blemishes_FullFace2, STON 0) and UC_CY_TayeImani
(European_Male_yo1_Sk3, STON 2); with it come MNAM / NNAM / VNAM, which the others lack. So a generic child shows the
race's default face skin, and a child can wear an adult European face skin. Built: our children take Bobby Katz's /
Sylvie Munich's face layer block (child_faces.FACE_DONORS, with_face_block: TNAM QNAM INTV MNAM NNAM VNAM, placed
where the donor has it); --child-controls adds NoFaceSkin (without it) next to VanillaHead / Tone0-2. ChildRace's
FSTT names a complex group listing SimpleGroup_FaceSkinTones_Child_Female: the tone report now follows it.
Unverified: what MNAM / NNAM / VNAM hold, and whether the layer changes a child's face in game.
Child face tones (owner's run 2026-11-19, verified): ChildRace's FSTT -> SimpleGroup_FaceSkinTones_Child_Male /
_Female, textures female_child_01_head(_sk2 / _sk3)_color.dds for both sexes, medians slot 0 (189,143,115), 1
(172,126,98), 2 (106,74,57): the face's slots run lightest-first, the body's do not (1, 0, 2). One STON picks both:
STON 1 gives face (172,126,98) with body (164,126,103), a match; STON 0 a much lighter face (189,143,115) on a
darker body (139,109,82). So the lightest child stays STON 1 (as vanilla's blonde girls EncChildFaceF03 / F06).

## 2026-11-19: the face transfer is what distorts the children (owner, in game)
Owner's control NPCs: only "VanillaHead" (Starfield's child head with the European face skin, Frodnar's hair) looked
decent; with Frodnar's transferred face (any tone) he read African - broad nose, wide cheeks, heavy features. So the
transfer, not the template / skin / tone. Rendered here from the mod files (verified): RS Children Overhaul's base
child head has ADULT proportions (adult nose and jaw; it is Skyrim's adult female head layout), and Realistic RS's
Frodnar is a real child's face, so "FaceGen minus base" is mostly "make an adult face a child's" (front mean 5 mm,
max 17 mm); added onto Starfield's head, which is already a child's, and with the two heads 8.5 mm rms apart after
the alignment, the moves land beside the features they belong to (supported hypothesis for the distortion).
Owner's choice: option 2 for the long run - line the features up (eyes, nose, mouth, chin) and carry the child's own
shape over rather than its difference from an adult-proportioned base.
Tool: --preview-npc <EditorID> (or --preview) on a child writes faces_preview/<EditorID>_child.png (solid renders,
facepreview.render: the Skyrim FaceGen head placed by the alignment, Starfield's child head, ours; front /
three-quarter / side; the moves as heat) and <EditorID>_child.npz (Starfield's head mesh-local + node + triangles,
Skyrim's base and FaceGen heads in Skyrim model units + triangles, the alignment, the moves), so fitting changes can
be tried and drawn outside the game.

## 2026-11-19: option 2 built - the child's own shape, feature by feature (fo4sf.childshape)
`face_fit --child-shape-npc Frodnar` (repeatable; other children keep the difference transfer; Dorthe not yet,
owner). Tried and drawn here on the owner's Frodnar shapes (faces_preview .npz, kept out of the repository) before
use, each version judged on renders (Skyrim face / Starfield head / old transfer / new):
- landmarks (verified on the shapes): Starfield's eye openings and lip loop are open-edge loops of its head
  (unwelded: 58-vertex eye loops at x +-0.04, z 1.684; lip loop z 1.608); the FaceGen eyes come from its eyes shape
  (stored in the head bone's frame, identity bind), the mouth from its welded open loops; nose tip, nasion, chin and
  forehead on the midline. Before: eyes 7 mm apart from Starfield's, chin 13 mm, nasion 10 mm.
- prealign: move + scale (no turn), eyes weighted 4x (scale 1.09 for Frodnar): the eyeballs are head parts placed
  for Starfield's sockets.
- fit: coarse-to-fine closest-point pulls smoothed over the mesh (400..100 passes), only where the Skyrim surface
  faces the same way; then three rounds along the normals of a smoothed copy, around the nose only; the moves
  Taubin-smoothed at the end. Eye sockets and the socket walls behind them locked; lips and the mouth's inside do not
  pull; the ears take part in the coarsest round only (size / place, not their folds); the face fades out before
  the ears, the crown and the neck. Target: the FaceGen head welded, subdivided twice, Taubin-smoothed.
- what the tries showed: fine rounds everywhere copied Realistic RS's sculpted creases (frown line, eye bags) as a
  bumpy texture; sliding sideways made lumps; a 14 + 12 mm eye lock left the lids Starfield's ("the eyes are
  unchanged", owner) - now 10 + 12 mm; locking only the opening let the socket walls behind it be pulled forward.
- result on Frodnar: within about +-2 mm of his Skyrim face over most of it (p5 / p95 -2.4 / +2.3 mm), chin tip
  1 mm, the under-chin still ~3.6 mm fuller; nose 31 / 42 mm wide at 10 / 14 mm behind the tip (his 30 / 34,
  Starfield's 35 / 44). 15-50 s per child.
Owner's notes on the first new version (12:04): not smooth, nose too wide, eyes unchanged, chin bold, ears
different - all addressed above except the last few mm of nose wing and under-chin. In-game check pending.
Owner in game on that (12:46): "that nose is still big and he's not quite white skinned".
- Nose: the fit left the wings and the cheek beside them at Starfield's width (38 / 46 / 49 mm across at 12 / 16 /
  20 mm behind the tip; his 32 / 36 / 41). childshape.narrow_nose now scales the nose region across to his widths
  at those depths (smoothly by depth, feathered 6 mm; only narrowing): 33 / 37 / 40 mm. VERSION 7.
- Skin: Starfield's child tones are only three and the lightest face tone is (172,126,98); the face skin layer is
  Bobby Katz's European_Male_Md1_Sk1 (an adult tone name). --child-controls now also writes one copy per European
  face skin the game's NPCs use for the sex (young yo1 phenotype first, else md1; lowest Sk numbers first:
  faces.json child_skin_choices) to pick the lightest in game. Which Sk is lightest is unverified.
- Owner asked whether face sliders work on children: no vanilla child uses them (no dials, blends or baked faces on
  any of the 51), but the child head has the adult layout and its chargen morph points at the adult morph.dat
  (races-roadmap), so they may; untested. The baked head stays (exact shape).
Owner (12:59): "the hands look lighter than the face, all those faces came out the same color" - the European face
skin copies changed nothing, so the face skin layer does nothing on a child NPC (as on adult NPCs: a non-player
face is its pre-built face textures; a new NPC has none and the game draws a default one). Now each child's test NPC
gets baked face textures as the adults do (face_fit.child_baked_face): a European HumanRace template with a baked
face picked by skin (pick_template), its textures copied under the child's FormID (the child head has the adult
head's layout), the colour texture matched to the median of the child's own body tone (the hands'). faces.json:
test_npc.baked_face. Unverified: that the game uses baked face textures on a ChildRace NPC, and that the adult
face textures sit right on the child head's UVs.
- child_skin_preview.py (owner's run): the adult template picked for Frodnar (ChargenPresetMale16) has light
  stubble painted into its face texture; Starfield's own child face tone textures are a painted child face in the
  child head's layout (a possible face source later).
**Verified in game (owner, 13:09-13:16):** the baked face shows on a ChildRace NPC and sits right on the child head
(eyes, nose, lips line up), so child and adult heads share the face UV layout. The feature-matched shape reads as
him.
Owner: "his skin is too dark, he needs to be nord looking ... those hands are pale white and the face isn't". The
body / hands (STON 1, Starfield's lightest child body) are pale; the face, matched to that body texture's median
(164,126,103), came out tan-orange. Measured on the owner's daylight screenshot: the face about 2-3x darker than the
hands in linear light and more saturated (blue / red about half the hands'). Guess: the game multiplies a child's
baked face colour by the face tone texture of its STON (vanilla child face tones run lighter than the body ones:
slot 0 face (189,143,115) vs body (139,109,82)), so the face colour should be the body tone divided by the face
tone. Tried (commit 7edd96e, never run): the face colour = body tone / face tone, with lighter copies to compare.
Owner (13:23): "why isnt it following how our npcs faces are done" - right: the adult test NPCs' faces are the
European template nearest their Skyrim skin tone with its baked face as it is, recoloured (human_face_colour, to the
adult body tone of their STON) only when the template's tone is 3 or more steps away. The child baked face had
instead always been recoloured to the child body texture's median, which is what made it tan-orange. Now
child_baked_face does exactly what the adults get: template by the child's adult-scale tone (target_skin), the
same human_face_colour rule; the divide mode and its controls are gone. faces.json: test_npc.baked_face
{template, adult_ston, recoloured}. The child body stays Starfield's child tone of the matching rank (STON 1, the
lightest, for Frodnar). Unverified in game; the adult template may carry light stubble (ChargenPresetMale16).
