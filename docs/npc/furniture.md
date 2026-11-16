# Furniture and idle markers: Skyrim -> Starfield (started 2026-11-08)

Why: NPC packages run (docs/npc/schedules.md, Orgnar verified 2026-11-08), but every chair, bed, bench and the bar-lean
spot in the converted interiors is a static, so sandbox / sleep / sit packages have nothing to use and NPCs only wander.

## Format (xEdit wbDefinitionsTES5 / wbDefinitionsSF1, read 2026-11-08: supported)
- Skyrim FURN: KWDA, KNAM interaction keyword, MNAM (bits 0-23 active sit points; Has Lean / Sit / Sleep Marker),
  markers (ENAM index, NAM0 disabled entry points, FNMK keyword), FNPR (type 1 Sit / 2 Sleep / 4 Lean, entry points),
  XMRK. Marker POSITIONS are only in the NIF: BSFurnitureMarkerNode (NiExtraData: u32 count, then per marker offset
  3 floats, heading, animation type u16, entry points u16; niftools nif.xml, BS 100).
- Starfield FURN: MNAM (bits 0-19 interaction points; Is Sleep Furniture ...), FNPR (1 Sit / 2 Lay / 4 Lean), and
  SNAM Marker Parameters IN THE RECORD: per marker offset x/y/z, rotation z, keyword (the animation set), entry types,
  exit types (28 bytes from record version 555; Starfield's are 582). Also XMRK marker model, NNAM marker files,
  FTMP template. Record flag 0x800000 Is Marker = invisible marker furniture.
- IDLM: Skyrim = flags, count, timer, IDLE animations, model; Starfield adds keywords, Actor Action, Animation Flavor
  (QNAM) and Animation Archetype (PNAM) keywords.

So the Skyrim positions come from the NIFs and go into Starfield's SNAM; the animation keyword has to come from a
vanilla Starfield furniture of the same kind.

## Step 1: survey (scripts/interior/furniture_survey.py, read-only)
Skyrim furniture / idle markers placed in the batch's cells (record + NIF markers) and every Starfield FURN / IDLM
(SNAM, FNPR, keywords, marker-only, how many references use it), with Starfield candidates per Skyrim base (same
marker kinds, closest name). Decides between two plans:
- A: a Starfield FURN per Skyrim furniture base: our converted model, SNAM from the Skyrim NIF markers (units -> m),
  keyword / FNPR / MNAM from the matching vanilla furniture.
- B: keep the Skyrim model as a static and place a vanilla marker-only Starfield furniture at each Skyrim marker
  (world position and heading), if Starfield has marker-only chairs / beds / lean spots.

## Survey results (owner's run 2026-11-08: Riverwood's 6 interiors; Starfield.esm)
Skyrim (verified from the files): 26 FURN bases + 4 IDLM. Chairs (CommonChair01 F/L/R/FL/FR/LR variants differ only in
disabled entry sides, WoodenChair01, NobleChair01): one Sit marker at seat height 34 units (0.486 m), heading 0. Table
benches (FarmTableBench01 2, CommonTableOneBench 3, CommonTableTwoBenches 6 markers): seats at y +-83..86 units facing
the table. Beds (CommonBed01 L/R, CommonBedDouble01 2, NobleBedSingle01): Sleep at (0, -11, 37) units. Marker-only
CounterBarLeanMarker / CounterLeanMarker / LeanTableMarker / HammerTableMarker / InvisibleChairMarker*: Sit at the
origin, the animation chosen by keywords (isBarCounter, FurnitureCounterLeanMarker, isLeanTable, isHammerTable). Crafting:
CraftingCookingPotSm, alchemy / enchanting workbenches. IDLM: SweepIdleMarker x17, WarmHands x2, CrossedArms, Browse.
Starfield (verified): 899 FURN, 18 IDLM. The animation is picked by KWDA keywords (AnimFurnChair 9174 uses, AnimFurnBench
4838, AnimFurnStanding 4118, AnimFurnBed 1239, AnimFurnSitTable, AnimFurnRailLeanHands, AnimFurnStanding_Sweep, ...);
FNPR is Sit or absent (beds use FNPR Sit + MNAM Is Sleep Furniture); SNAM has 1 marker in 762 bases, its keyword is
null in all but a few scene ones, z = 0 in every base but one. Marker-only furniture (record flag Is Marker, model
Markers\InvisibleGeneric01.nif) covers chairs (NPCInvChairSit_Free), benches (NPCInvBenchSit), leaning on rails
(NPCRailLeanHands / Front / Back, offset y -0.3 m: the rail is at the origin), sweeping (NPCSweeping), arms crossed,
window shopping, standing. Skyrim-style idles are these furniture markers, not IDLM.

## Step 2: make_furniture.py + PluginSpike FURNITURE (2026-11-08)
Per Skyrim base, a copy of a vanilla Starfield furniture (make_furniture.TEMPLATES): chair -> NPCInvChairSit_Free,
bench -> NPCInvBenchSit, bed -> FoundCanvasCot01, lean counter / lean table -> NPCRailLeanHands, hammer table ->
NPCRepair_ToolStanding_Hammer, sweep -> NPCSweeping, arms crossed / browse / warm hands -> NPCStanding flavours. Real
furniture keeps our converted model; markers from the Skyrim NIF (x / y in metres, heading, z 0 like vanilla;
--marker-z skyrim to try Skyrim's seat height) with Skyrim's entry sides. Marker-type ones keep the template's markers
and invisible model. Crafting stations and quest furniture stay statics. The furniture reference replaces the static of
the same Skyrim reference; one an NPC package names is persistent. Unverified in game: seat / bed height, the lean
stand-off, rotation sign of SNAM (Mutagen exposes degrees).

## First in-game look (owner, 2026-11-08)
- Benches on the inn's tables missing. Cause (verified from the survey: record flags 10802010 on NPCInvBenchSit /
  NPCInvChairSit_Free): the copied marker-only templates keep the record flag Is Marker (0x800000), and markers are not
  drawn. Fixed: cleared (and the marker's bounds dropped) when our model replaces the template's.
- Orgnar leaned with the rail-lean animation at the counter's end, hands on the lower shelf. Starfield has bar furniture:
  NPCBartender_Standing (AnimFurnBartender) and NPCLeaningBartopFront / Back / Left / Right (AnimFurnLeaningBartop*),
  NPCDeskLean (AnimFurnDeskLean), all marker at the origin like Skyrim's. Now: isBarCounter -> bartender,
  FurnitureCounterLeanMarker -> bartop front, isLeanTable -> desk lean.
- `set gamehour to 2` is not a Starfield console variable (Unknown variable 'gamehour'); waiting needs a seat or bed.
Open question (owner): put Skyrim's own furniture animations through the animation converter. Use Starfield's where a
close one exists (sit, bench, bed, bartender, bartop lean, sweep); convert the Skyrim-only ones (stirring the cook pot,
alchemy / enchanting, hammer at the anvil, warming hands, eating at the table) when positions and heights are right.

## Second look (owner, 2026-11-08) and the next measurements
- Benches back (Is Marker fix verified). Orgnar with NPCBartender_Standing: "not quite on the bar, closer".
- Chairs and benches could not be used by the player. Changed: chairs and benches now copy real vanilla furniture
  (FoundCanvasChair01_Free 001BF52D, Bench_UtilityA02 001E426C: record flags 10000000, drawn and used everywhere)
  instead of the marker-only ones. A/B if they still cannot be used: FURNITURE_MODEL=vanilla keeps the vanilla model (a
  problem with our NIF: collision layer, no marker nodes) vs ours.
- How far a marker stands from the counter in front of it is measured, not guessed: furniture_standoff.py casts the
  marker's facing ray against the object bounds of the references around it, on each game's own placements (Starfield
  bartenders vs Skyrim's bar-lean markers). The difference goes into make_furniture.py --shift
  (riverwood_doors.ps1 -FurnShift "bartender=0,<dy>,0"), applied in PluginSpike to the template's markers.
Measured (owner's run 2026-11-08, furniture_standoff.py; verified on each game's data): Starfield's NPCBartender_Standing
(69 refs) and NPCLeaningBartopFront (57) stand at the counter face (0.00-0.03 m on straight counters), Skyrim's
CounterBarLeanMarker (24) / CounterLeanMarker (83) 0.32 / 0.31 m back from it; counter tops 1.10 m in both games, so
Starfield's bar animations fit Skyrim's counters as they are. make_furniture.DEFAULT_SHIFT moves bartender and
lean_counter markers 0.30 m forward.
Verified in game (owner, 2026-11-08, after the shift and the real chair / bench templates): Orgnar on the bar; the player
can sit on chairs and benches and use the beds.
With -Furniture, riverwood_doors.ps1 passes make_schedule --keep-furniture-only: Skyrim's Allow Wandering kept (Orgnar's is off).

## Crafting stations (2026-11-09; offline checks only)
Riverwood's interiors hold 5 cooking pots (Sven's, Faendal's, the Trader, ...), an alchemy lab and an enchanter (the
Sleeping Giant; owner's furniture survey). make_furniture now turns crafting stations into Starfield furniture
(--no-crafting / riverwood_doors.ps1 -NoCrafting keeps the old statics):
| Skyrim | Starfield template | animation keyword |
|---|---|---|
| cooking pot / spit | Invisible_GalleyWorkbench01 000EFC6F (marker-only; our pot as its model) | AnimFurnGalleyWorkbench, WorkbenchCookingKeyword |
| alchemy lab | WorkbenchChem 002B6A61 | AnimFurnPharmaWorkbench |
| enchanter, forge, smelter | WorkbenchIndustrial 001F50AD (no script; WorkbenchResearch has one) | AnimFurnIndustrialWorkbench |
| grindstone | WorkbenchWeapon 002B6A63 | AnimFurnWeaponWorkbench |
| armor table | WorkbenchArmor 002B6A62 | AnimFurnArmorWorkbench |
| anvil | NPCRepair_ToolStanding_Hammer 0000A4B0 (as the hammer table) | AnimFurnRepair_Tool_HammerStanding |
| tanning rack | NPCStanding_WipeWall 0003C420 (marker-only) | AnimFurnStanding_WipeWall |
Markers: the Skyrim NIF's (x / y / heading, z 0), except the marker-only hammer / wall-wipe, which keep the template's.
A station whose NIF has no marker stays a static (reported). To see in game: NPCs using the pots; what E on a pot /
alchemy lab opens (the copies keep the Starfield workbench data: likely Starfield's cooking / chem menus with
Starfield's recipes; Skyrim recipes are a later step).
Owner, 2026-11-09 (in game): the Sleeping Giant's alchemy lab shows "Pharmaceutical Lab", Use (E); pressing E does
nothing, no animation. Orgnar works behind the bar (bartender marker). Open: record (copy without VMAD / workbench
data) vs model / markers (Skyrim's one marker, wall-side table) vs reach; console A/B queued: vanilla WorkbenchChem
placed in the inn, and our copy placed on open floor.
A/B result (owner, same day): Starfield's own WorkbenchChem (player.placeatme 2B6A61) on the inn's open floor also
does nothing on E, while chairs, benches and beds there work for the player (2026-11-08). So not our copy, model or
markers: workbenches in this session (verified), cause open (the cell vs the character started by coc from the main
menu). Next A/B: the same placeatme in a vanilla cell, then from a normal save.
Owner, minutes later: moved, the vanilla lab works in the inn. So the spot decides (verified): the first one stood
between the hearth's stone edge and a pillar. Reading (supported): Starfield checks room around the workbench marker
before it plays the entry; our lab's Skyrim marker faces a tabletop pushed against the wall. Next: our copy on open
floor; if it works there, give crafting markers the clearance Starfield's own labs have (measured like the bar shift).
Our copy on open floor (owner, same evening): E does nothing either; in first person E moves the camera to the lab
(just above the alembic, at table height) looking away from it, and no menu comes up. So the player does enter our
marker, but stands at the tabletop's height (the marker z is set to 0 = the reference's height, the table top for a
tabletop station) and faces away. Reading (supported, not verified): the Skyrim marker's height and / or heading do not
fit the Starfield chem bench's entry, which then never reaches its menu. Checking the vanilla bench's SNAM against ours
(npc_record_diff --type FURN --pair) and the Skyrim marker in furniture.json before changing it.
Result (owner's npc_record_diff, verified): WorkbenchChem's SNAM is offset (0, -0.728, 0), rotation 0, entry / exit all
sides; ours (0, 0, 0), entry / exit Rear only. Workbench data equal; ours lacks FLLD (01000000, Mutagen did not
write it; unknown use). The owner's furniture_survey (2026-11-08) shows every Skyrim crafting NIF with one marker at the
origin, heading 0, entry Behind (cooking pot, alchemy lab and tabletop, enchanter): Skyrim's crafting animations do the
stand-off. So crafting stations now keep the template's markers (make_furniture SPECIAL), as the bar and idle markers do.
If the lab still opens nothing, FLLD is the next suspect.
Owner, 2026-11-09 after the rebuild (verified in game): E on the alchemy lab opens Starfield's Pharmaceutical Lab menu
(Starfield's medical recipes). FLLD not needed. Next: Skyrim's own recipes (COBJ by bench type) as the menu's content.
The enchanter (WorkbenchIndustrial copy) and a cooking pot in Sven's house (galley workbench copy) open their menus too
(owner, verified). All three crafting kinds in Riverwood work.

## Outdoors (2026-11-13)
Owner (in game): Riverwood's outdoor benches cannot be sat on and Alvor's forge is missing. Verified from the owner's
skipped.json / objects.json of the installed exterior: every outdoor furniture is a plain static (161 CommonChair01,
124 FarmBench01, 44 BlacksmithWorkbench01, 26 BlacksmithAnvil ... placed), and the smithing furniture whose model
name holds "Marker" was dropped as an editor marker (CraftingBlackSmithForge, Furniture\BlacksmithForgeMarker.nif
19x; CraftingSmelterMarker1 18x; CraftingTanningRackMarker 64x). Changes:
- exterior.MARKER_RE: only a markers folder or a file name starting with marker / xmarker is an editor marker (the
  forge, smelter and tanning rack come back on the next exterior rebuild).
- The Riverwood build with -Furniture (riverwood_doors.ps1; -NoOutdoorFurniture to skip): make_skyrim_interior.py
  batch --exterior-furniture <-NavAround> --exterior-radius <-NavRadius> lists Skyrim's outdoor FURN / IDLM references
  there (not initially disabled) in exterior_furniture.json and converts their models with the interiors;
  make_furniture.py makes them the same furniture as indoors (cell "exterior", persistent); PluginSpike places them in
  the exterior world's persistent cell (ExtPos) and disables the exterior's static copy of each (an Initially Disabled
  override, as for the load doors). No exterior rebuild. Unverified in game: placement, sitting, the forge's E.
Owner, first outdoor look (2026-11-13): benches and chairs outside are ours (console: FURN refs in FO4Port.esm), NPCs
use the markers; the Sit / Sleep prompt only shows when looking at the furniture's very centre; a bench offers Sit
but sitting does nothing; one chair (against a wall, a post and the tanning rack beside it) offers nothing. Changed:
furniture with our model gets that model's object bounds (make_furniture.add_bounds from the batch's converted NIF;
before: empty bounds, a point). Open: the bench / chair entry (Skyrim's entry sides vs the wall, or the marker facing).
Owner, same day: `disable` in the console on the old exterior bench under ours, then Sit works (verified): the
Initially Disabled override had not taken in game, and the static's collision blocked the sit. PluginSpike now hides a
replaced exterior static (furniture and load doors) as xEdit's "Undelete and Disable References" does: Initially
Disabled, 1000 m lower, enable parent PlayerRef (000014) with "opposite of parent". Written without a compiler.
Riverwood's forge (owner's export of every forge / anvil / smelter in Tamriel, 2026-11-13): CraftingBlackSmithForge at
(20459, -45225) units, i.e. cell 4,-12, but listed under cell 0,0, as every persistent reference: Skyrim.esm gives the
world's persistent cell XCLC 0,0, and skyrimrefs took that as the references' cell, so a --cells / --around export
(exterior_furniture.json, skyrim_first_run --radius) left all persistent references out. Fixed: the persistent cell's
references take their cell from their position. Its fire (LightForgeFire01) is a light: exterior lights are not
translated yet, so the forge comes back unlit.
Owner's Riverwood build after the persistent-reference fix (2026-11-13, log verified): 92 outdoor references, the forge
in (CraftingBlackSmithForge -> WorkbenchIndustrial with blacksmithforgemarker.nif), 20 exterior statics hidden. But the
"Sit marker -> chair" fallback also took Skyrim's work / creature furniture: DragonPerchRockL02 x12, DragonPerchTower x4,
PickaxeMining* x5, WoodChoppingBlock x4, BucketCarry* x2, WoodPile x2, ResourceObjectSawmill, LeverPushAnimatingMetal
became FoundCanvasChair copies (with the canvas chair model where theirs did not convert). make_furniture
WORK_FURNITURE_RE now leaves those out (a real model stays the exterior's static) until Skyrim's animations are ported.

## Animations: Skyrim's own on our furniture (plan, 2026-11-13)
Owner: NPCs use the outdoor and indoor markers now, but with Starfield's animations and props (a datapad while
"standing", a rag at the tanning rack); convert Skyrim's so they look right, in the right spot.
Route (nothing new invented; both halves verified before): (1) a Skyrim clip decoded, retargeted and written as .af
plays correctly on the Starfield human rig (hkx_to_af; chair_idlearmscrossedvar1 seated correctly in game,
2026-10-19); (2) Starfield picks clip folders by keywords and an esm HumanRace entry with one keyword more than a
generated-table row wins (stances, verified in game 2026-10-23), followed by the Creation Kit's GenerateAnimInfo run.
So per furniture kind: our furniture copies get an S2S keyword; an entry cloned from the template's Furniture row(s)
with that keyword puts a folder of converted Skyrim clips first, written under the tags the template's graph already
plays (enter / idle loop / exit ...); tags our folder lacks fall back to Starfield's.
Steps:
1. Survey (scripts/armor/furniture_anim_survey.py, read-only): per template, its keywords, the matching Furniture rows,
   folders, clip tags and graph; per Skyrim base we convert, its IDLE events and the Skyrim behaviour clips.
2. Mapping table kind -> (Starfield tags, Skyrim clips): from the survey.
3. First kind end to end (sitting: bench and chair; the chair idle already converts): clips, keyword, entry, CK run.
4. Then lean, sweep, tanning rack, anvil, forge, chopping, cooking, ...; props (broom, hammer) after.
Survey result (owner's run, 2026-11-13, verified from furniture_anims.json): Starfield's furniture folders play one
tag set: EnterFromStand / Idle / Idle_Flavor01-06 / ExitToStand / QuickExitToStand (+ LookDirections), seats with
Front / Left / Right / Rear Enter / Exit variants, Camera and Talk_*; graph FurnitureHeadTracking_Wrapping.agx over
Furniture.agx. The generated table has no generic third-person chair / bench row (only AnimArchetypePirate ones):
those entries are HumanRace's own in Starfield.esm. Our races take HumanRace as subgraph template (SRAC), so a
HumanRace entry reaches our NPCs. Skyrim (mt_behavior.hkx): chair_frontentervar1 / chair_frontexit, chair_left / right
enter / exit, chair_idlebasevar1 (+ basevar2, shoulders, arms crossed / look down with transitions); benches use the
chair set; no entry from behind.
Built (first set, Sit; untested in game): stance_plugin.FURNITURE_SETS adds keyword S2S_AnimFurnSkyrimSit (fixed
FormID, index 16) and copies of every third-person chair / bench entry with it and furniture\s2s_sit first;
furniture_anim_pack.py converts the Skyrim set (one seat offset for the set: the Idle's --align-com, then --com-shift
for all; no root motion) into that folder under the chair descriptors; make_furniture --anim-plugin gives chair / bench
bases the keyword and PluginSpike adds it (FO4Port.esm then masters S2SStances.esm: it must load after it). Arms-crossed
/ look-down flavours wait for stitching their transitions; female clips use the male conversion for now.
First in-game look at the Sit set (owner, 2026-11-14, screenshots): the player sits on our bench with the Skyrim clips
playing, seat height right, but the arms are pulled back and twisted inward, hands by the hips (Skyrim's base chair
idle has them forward). Open: the clip itself (conversion) or the game after it (furniture graph layers / IK).
scripts/armor/af_pose.py prints a clip's joint world positions read back the game's way, for our Idle beside the
vanilla chair Idle. Also: one outdoor bench still has a terrain-plugin static (0400502E) under it.
Arms (2026-11-14, verified from the owner's af_pose and .afx dumps): our converted Idle has the wrists 0.15 m in front of
the spine at 0.57 m (forward on the thighs, as Skyrim), the vanilla chair Idle at 0.67 m beside the body (armrests).
Starfield's chair AND bench Idle descriptors carry bEnableHandIK over the whole clip, and we copied it: in game the
graph pulls the hands to IK targets of Starfield's furniture models (ours have none) -> arms back and twisted. Now
furniture_anim_pack leaves bEnableHandIK out of our descriptors (DROP_VARIABLES). Verified in game (owner,
2026-11-14): the hands rest forward on the thighs.
Hands in the thighs (owner, 2026-11-14, screenshot: better, but the hands clip into the legs). af_pose hands_on_thighs:
our Idle's wrists 0.047 / 0.063 m above the hip-knee line, slightly inside it; Starfield's chair Idle 0.129 / 0.136 m
above, 0.03 m outside (Starfield's thighs are thicker than Skyrim's). The pack now lifts hands resting on the thighs to
0.13 m above and 0.03 m outside (HAND_CLEARANCE, hkx_to_af --hand-clearance, retarget.lift_hands: two-bone arm IK, the
hand keeping its rotation, blended out when the hand leaves the thigh). Idle verified by af_pose: 0.130 / 0.133 above.
The first version lifted hands in the enters / exits by up to 0.196 m (owner's pack report): standing, the thigh points
down and a hanging hand counted as "over" it. Now only while seated (thigh near level), only hands on top of the thigh
line, and at most 0.10 m (Idle clips need 0.07-0.09); largest lift now 0.088 m. Verified in game (owner, 2026-11-14:
"that looks good").

Exterior statics under the outdoor furniture (2026-11-14). In game every outdoor bench / chair still had the exterior's
static under it (console on 0400502E: GetDisabled 0, original height; the game's z is the plugins' z - 200 m).
scripts/tools/ref_overrides.py on the installed plugins (verified): FO4Port.esm's copy belongs to
SkyrimTerrainTamriel.esm, is Initially Disabled, sunk to -615.12, enable parent PlayerRef with "opposite", sits in the
same world / block 0,-1 / sub-block 0,-1 / cell 001341 / temporary group as the original (cell record before it), and
FO4Port.esm loads after both terrain plugins; _Mars has no copy; staged and installed exterior identical (hash). On a
fresh `coc SKY_TamrielRiverwoodSpawn` from the main menu (no save) the static (040181E2) still stood under a chair. So the
game does not apply FO4Port.esm's overrides of those temporary references (cause unresolved). Fix:
scripts/terrain/apply_ref_overrides.py writes FO4Port.esm's hidden statics into the exterior plugin itself, in place
(Initially Disabled flag, FO4Port's sunk position; same record sizes, no FormID moves; one-time backup), into the
installed copy (correction 2026-11-14: at first also the staged copy, which put the load doors underground on the
next build; see "Doors underground" below); riverwood_doors.ps1 step 5 runs it after every install. Owner's run: 19
statics patched. Verified in game (owner, 2026-11-14): the statics are gone and the furniture can be sat on.

More sets (2026-11-14, after Sit was verified). The owner's survey of the template folders (furniture_anims.json):
leaningbartopfront, bartender, desklean, standing_sweep, standing_wipewall and the pharma / industrial / galley
workbenches all play Idle, Idle_Flavor01..NN (6 / 5 / 4 / 5 / 5 / 5 / 6 / 0), EnterFromStand, ExitToStand,
QuickExitToStand (sweep and wipe-wall also EnterInstant). furniture_anim_pack.standing_set fills them from one Skyrim idle
loop (mt_behavior's clips): RailLean (railleanidle / enter / exit), WallLean (wall_idleback*), Counter
(animobjectcounteridleloopright / enter / exit; the arms-on-counter and wiping loops are other poses, left for clip
stitching), LeanTable (idleleantable, _point as flavor, _enter / _exit), Sweep (animobjectsweepingidlebase, var1,
start; no Skyrim exit: Starfield's stays), Alchemy (craftingalchemybench stir / pound / tap, enter / exit), Enchant
(craftingenchantingbench idle / idlecircle / enter / exit, on the industrial workbench template), Cook
(craftingcookingpotstir / enter / exit), Tanning (craftingtanning idleb / idlea / enterb / exitb, wipe-wall template).
Every flavor slot is filled (a vanilla flavor would play Starfield's own pose mid-idle). make_furniture.ANIM_SET_RULES:
kind + EditorID -> set (the three lean markers share the lean_counter template but not their clips; the forge keeps
Starfield's). stance_plugin.FURNITURE_SETS: one keyword per set in this order (Sit's FormID unchanged), the set's
folder first in copies of the template keyword's entries. Offsets: COM_SHIFT keeps Sit's measured one; WallLean
(0, 0) (leaning back, while the template's actor faces a counter); the rest are aligned to their template's Idle.
Props (broom, ladle, scraper): unverified: Starfield's descriptor events are kept. Unverified in game.

Doors underground (owner, 2026-11-14, after the build with step 5: doors look wrong, none can be entered). The build
places each exterior load door at the staged exterior's static door (EXTERIOR_DIR); step 5 had also patched that staged
copy, so the rebuild read sunk statics and put the 7 load doors 1000 m down (and sank the statics again). Now step 5
patches only the installed copy, and PluginSpike stops if a staged door static is already disabled. Recovery: restore
both copies from their .before_ref_overrides backups (made on the first patch, i.e. the originals), rebuild.

Body shape (2026-11-14, owner: "the difference in body is going to cause issues with every animation, can we account
for that when we convert"). Plan: measure once how thick each body part is around its bone in both bodies
(fo4sf.bodyprofile: a radius grid per segment, by position along it and direction around it, from the skinned body in
its bind pose; scripts/armor/body_profiles.py), then in the retarget keep each hand's gap to the nearest body surface
(Skyrim's gap, on Starfield's surface) by two-bone arm IK, blended out as the hand leaves the body. Generalises
lift_hands (thighs only, tuned 0.13 m) to chest, belly, hips, the other arm.
Owner's first measurement (2026-11-14, body_profiles.json): Starfield's male body is NOT thicker. Mean radii Skyrim /
Starfield: chest 0.155 / 0.129, belly 0.142 / 0.127, thigh 0.090 / 0.083, upper arm 0.085 / 0.060, forearm 0.047 /
0.035 (Skyrim's skeleton ~8 % taller). The difference is proportion: Starfield's upper arm 0.27 m vs Skyrim's 0.33
(0.30 at Starfield's height), forearm 0.24 vs 0.23 (0.21), shoulder joint lower. Skyrim's arm rotations therefore land
the hand elsewhere relative to the body. Fixes to the measurement after that run: surfaces sampled by area (Skyrim's
body has 2453 vertices), hips measured hip joint to hip joint (Starfield's C_Hips -> C_Spine is 6 mm), points beyond
1.8x a segment's median distance dropped (armpit torso points on the upper arm), heights printed.
retarget.keep_contacts (hkx_to_af --body-profiles; furniture_anim_pack --body-profiles, which then drops
HAND_CLEARANCE): per frame and hand, each body segment near Skyrim's wrist (gap < 0.14 m, full below 0.06) pulls
Starfield's wrist to the same position along / direction around / gap from Starfield's segment surface; arm IK, hand
rotation kept. Unverified on real clips.
Owner's run with the fixed measurement and --body-profiles (2026-11-14): at equal height (Skyrim x0.896) the bodies
match within 10 % except the upper arm (Starfield 0.83x) and the pelvis (0.86x). keep_contacts: Sit 9 clips (thighs,
up to 0.156 m), WallLean 3 (forearms, belly, chest, hips; 0.139 m), Sweep 3 (0.12 m), RailLean 2 (0.092 m), the rest
under 0.04 m. Sit Idle by af_pose: hands 0.135 / 0.148 m above the hip-knee line, Starfield's chair Idle 0.129 / 0.136,
with no tuned value (lift_hands' 0.13 was set from that same chair). Unverified in game.

Shoulders and props (2026-11-15). Owner, in game: the tanner works 0.65 m from the rack holding a white cloth; seated
NPCs briefly hold the hands oddly; the wall lean's hands clip; "all animations seem to cause the shoulders to go
down". af_pose shoulders (owner's run): our sitting Idle 0.137 / 0.140 m below the neck, clavicle 10-11 deg below
level; Starfield's chair Idle 0.074 / 0.079 m, 7-9 deg above; our wall lean 0.151 m, 14 deg below; Starfield's bar
lean 0.014-0.027 m, 20-26 deg above. One systematic error: rest_alignment points Starfield's clavicle where Skyrim's
points, but the skeletons put the clavicle joint differently (37 deg apart at rest). Fix: a calibration from a pair of
clips doing the same thing (ours as converted without it, Starfield's), af_pose --calibrate-shoulders -> a body-frame
turn per clavicle (retarget.shoulder_calibration), applied in the retarget before the two-hand grip and the contacts
(apply_shoulder_offsets: the clavicle turns, its children keep their world rotations, so the shoulder joint moves and
the arm points as before); hkx_to_af / furniture_anim_pack --shoulder-calibration. First pair: Skyrim's seated idle
against Starfield's chair Idle; a neutral standing pair to check it against later. Calibrate from clips converted
WITHOUT the calibration (else it measures its own result). Tanning: COM_SHIFT (0, 0); the template's AnimObj* events
(AnimObjLoad / AnimObjDraw AnimObjectDishRag in standing_wipewall\enterfromstand.afx) are left out of every set but
Sweep (KEEP_PROPS). Unverified in game.
Owner's run with the calibration (2026-11-15): af_pose --calibrate-shoulders on our Sit Idle (converted without it)
against Starfield's chair Idle: turn 26.9 / 26.5 deg. After the pack with it: our Sit Idle's shoulders 0.085 / 0.082 m
below the neck, clavicle 5-6 deg above level (before 0.137 / 0.140 m, 10-11 deg below; Starfield's chair Idle 0.079 /
0.074, 7-9 above); the wall lean 0.089 / 0.082 m (before 0.151). Hands on the thighs unchanged (0.135 / 0.147 m), and
keep_contacts moves less (Sit up to 0.087 m, was 0.156; WallLean 0.075, was 0.139). Prop events left out: Sit 7
descriptors (Starfield's chair flavors carry props), Counter 3, Alchemy 2, Enchant 3, Cook 2, Tanning 4.

Lean spots on Skyrim's markers (2026-11-15, owner, in game with the calibrated shoulders: "leaning looks better" but
Hilde leaned facing along the walkway instead of at the rail, Hod stood ~0.3 m off the post). Their bases (SPECIAL
kinds: lean_counter, bartender, lean_table, sweep, scrape) kept the Starfield template's marker, right for Starfield's
own animations, not for Skyrim's clips (chairs and benches, on Skyrim's NIF markers, sit right). make_furniture now
stores skyrim_markers for those bases (the Skyrim NIF's furniture markers, or the reference itself for an idle
marker), and add_anim_keywords uses them when the base gets one of our animation keywords; crafting stations keep the
template's (Starfield's menu needs its marker). COM_SHIFT for RailLean / Counter / LeanTable / Sweep back to (0, 0):
Skyrim's clips at Skyrim's spots. Needs the pack for those sets and the Riverwood build. Unverified in game.
Owner's build after the switch (2026-11-15): every lean / counter / table / sweep base "1 markers from Skyrim"; model
cache "reused": 0 once more (the first build after the signature change; the next should reuse all 265).
Talking on our furniture (2026-11-15, owner: seated Hilde crossed her arms while talking, fine, then "puts them down
and they briefly go inside her body"): Starfield's own seated talk clips (furniture\common Idle_Dialogue01-07,
Talk_L01-L10, Talk_M01-M16, Talk_S01-S05) blended with our pose. The pack now writes, for every set, copies of its
own Idle under those 38 tags (TALK_SLOTS, talk_copies: descriptor with the tag and file name changed; the clip copied,
not converted again), found before Starfield's (our folder first). New files: needs the Creation Kit cache run.
Unverified in game.
Owner, in game after the talk slots (2026-11-15): seated Hilde still played Starfield's talk gesture (hand to chin, arm
across). On the owner's PC (verified): s2s_sit holds the 38 slot descriptors and clips (Idle copies, 4:54 / 4:10 PM),
and 8 AnimationFileData cache files name s2s_sit\talk_l01. So the gesture does not come through those furniture-graph
tags (supported). Suspect: a subgraph row of another role than Furniture (stance_plugin copies only Furniture rows)
that also matches chairs. scripts/armor/subgraph_rows.py lists every table row naming given keywords, any role.
Also seen: idle Hilde's shoulders low and hands sunk into her lap (a woman on the male conversion; the shoulder
calibration and body profiles are male), Hod still ~0.3 m off the post, Hilde slightly off the rail (facing now right).
Owner's checks (2026-11-15): subgraph_rows.py: "1607 rows; 5 match: Furniture 5" for AnimFurnChair / AnimFurnBench (no
other role, verified). The owner's survey (furniture_anims.json) shows the furniture graph linking NPC_IdlePartialBody
(variables iSyncPartialBodyBlend, iSyncInDialogueScene) and common\female holding IdlePartialBody, _Flavor01-04,
_Start, _Stop (common\pirate 01-02, plain common none): a woman's standing upper-body idles over our seated pose (hand to
chin, arms crossed; arms hanging into the lap = "shoulders down, hands inside her body"); men have none. So
TALK_SLOTS now also holds those 7 tags (PARTIAL_BODY_SLOTS), Idle copies like the talk ones. Supported, unverified in
game. Lean markers (owner's furniture.json): every lean / counter / table / sweep / tanning base's Skyrim marker is the
reference itself (offset 0; wall lean facing 0, rail lean 180), so Hod's remaining ~0.3 m is not the marker data.
Male player, hands into the body for a moment as he sits (owner, 2026-11-15): not the women's upper-body idles (men
have none). af_pose --gaps body_profiles.json checks each clip over all its frames: each hand's (wrist and palm)
smallest distance to the body's surface (Starfield's body profiles, posed by their joints; mean radius around the
axis) and the frames where it is inside; our sit enters against Starfield's chair EnterFromStand.
Owner's af_pose --gaps (2026-11-15): our sit enters (front / left / right) and Idle never put a hand inside the body
(closest +0.035 m); Starfield's chair EnterFromStand -0.001 m. Owner: the moment at the start of sitting looks like
the first conversion (arms back and twisted: the hand-IK pull). So a Starfield descriptor with bEnableHandIK still plays
there: the states we do not convert (Rear*, EnterInstant, LookDirections ...). The pack's copy step now copies every
such descriptor of the set's template folder and furniture\common into our folder with hand IK / prop events left out
(vanilla_leftovers; Starfield's clip with it; ones with nothing to leave out are not copied). Unverified in game.
Owner in game after the cleaned states (2026-11-15): Hod still ~a foot in front of the post, Hilde ~a foot back from
the rail; the seated player (already seated: the Wait prompt) every so often leans and drags the hands down into the
body: an idle flavor (af_pose --gaps had checked the enters and the Idle only). Suspect for the leans (supported):
Skyrim's enter clips carry root motion (to the wall / rail) that --no-root-motion drops; Hod too far forward and Hilde
too far back, each along the way they face, fits. scripts/armor/furniture_motion.py prints each set clip's root motion
end from Skyrim's animationdatasinglefile (DefaultMale, generators mapped through the behaviours).
Owner's results (2026-11-15): furniture_motion.py: Skyrim's chair front enter ends y +0.907 m turned 180 deg, rail
enter y +0.693, wall enter y +0.264 turned 180: Skyrim's marker is where the enter ENDS, so ours (no root motion, at
the marker from the start) stand where Skyrim's end; root motion does not explain the lean stand-off (corrected the
supposition above). Next suspect: the template's marker model (kept for the lean spots) and its own marker 0.3 m back;
needs the actors' getpos against the marker positions. Every Sit flavor checked by --gaps: never inside (closest
+0.050 m); test: flavors replaced by the Idle in place. The table's chair / bench rows are the pirate ones (generic
ones are HumanRace esm entries); benches read furniture\bench, women chair\female / bench\female first: the hand-IK
clean-up now scans those too (leftover_folders).
Owner's tests (2026-11-15): (1) flavors replaced by the Idle: the seated slump (arms straight, hands at the seat edge:
Starfield's chair pose made for armrests) still comes, so not our flavors. The pack now answers every template-folder
tag ours lack (chair, bench, their female folders, furniture\common) with the set's Idle unless it is an enter / exit
/ look / camera / flinch state (unanswered_tags; printed per set), those keep Starfield's clip cleaned of hand IK.
(2) Hod's getangle z 315.48 = his marker's heading 315.5 (console positions are in another frame than the plugin's, not
compared). The lean stand-off found: make_furniture.DEFAULT_SHIFT moves bartender / lean_counter markers +0.30 m along
the furniture's +y (measured 2026-11-08 for Starfield's bar-lean animation at the counter face), ahead of Hod (facing
0) and behind Hilde (facing 180): exactly the owner's "a foot". add_anim_keywords drops that default where our Skyrim
clips use Skyrim's markers (a --shift given on the command line stays). Needs the Riverwood build.
Owner's run (2026-11-15): Sit's only unanswered idle-like tag was Stand_Start (now our Idle; that is the Starfield
state behind the seated slump, supported); left to Starfield (cleaned of hand IK where it had it): Camera, EnterInstant,
LookDirections(_Head), RearEnterFromStand, RearQuickExitToStand, Flinch. Other sets: none idle-like unanswered. The
build put the lean / counter / table bases on Skyrim's markers without the 0.30 m default shift.
Owner in game (2026-11-15) after Stand_Start and the 0.30 m shift: the leans are right ("leaning on the wall
correctly", Hod and another NPC against their posts, verified). The seated arms-back moment still comes (player and
Hilde). scripts/armor/furniture_graph_probe.py: every tag the chair / bench graphs (and the graphs they link) play,
resolved through each HumanRace esm entry's and table row's folder chain against our folder, hand-IK descriptors
marked, to find what still plays Starfield's own clip.
Owner's furniture_graph_probe (2026-11-15): HumanRace's own chair / bench entries read chair\animflavor (32 tags),
chair\female\animflavor (27), bench\animflavor (18), bench\female\animflavor (23) BEFORE chair / bench; the wrapping
graph renames tags (prefix "Relaxed", suffixes PoseA / PoseB / PoseC) and plays GripOffset_LeftArm / _RightArm (no
folder answers those: nothing plays). So the seated arms-back moment: renamed states from animflavor (Starfield's
armrest pose), supported. The pack now scans the animflavor folders and answers a renamed tag whose base ours answer
with our clip of the base (base_tag: RelaxedEnterFromStand -> our EnterFromStand), other idle-like ones with the Idle.
Beds (owner, in game: NPCs sleep sideways): Skyrim's bed markers and the cot template's read alike (rotation 0, entry
left / right; Skyrim's double bed sleepers side by side along x, so the beds run along y), so Starfield's sleep
animation lies along the marker's x: make_furniture.DEFAULT_TURN bed -90 (the head pointed at the wall with the pillow
to the left: a quarter turn counter-clockwise from above; Bethesda's z is clockwise). --turn bed=90 / riverwood_doors
-FurnTurn "bed=90" if the head ends at the foot. Unverified in game.
Owner's anim_cache_clips (2026-11-15, after the CK cache run): the 8 cache files naming s2s_sit resolve 862 clips
elsewhere: 263 chair\animflavor, 181 chair\female\animflavor, 158 bench\animflavor, 136 bench\female\animflavor
(<mood>_<clip>.af: thinking, confident, crosslegs, executive, relaxed, tablet, analyzeangry, bored, depressed, fancy,
slouched, analyze, armscrossedcasual, recline, sandwich; each over idle / flavors / sit_start / stand_start / talk /
lookdirections), common (93: casting, ladders, locomotion, relaxed_idlepartialbody_<prop> incl. handsbehind,
armcrossed), common\female 7, common\pirate 5, and chair / bench EnterInstant, LookDirections(_Head),
RearEnterFromStand, furniture\common Camera / Flinch. Verified: so the brief upper-body takeover on our seat is a mood
variant (no descriptor of its own; found by file name along the chain). The pack now copies our clip of the base under
every such variant name into our folder (mood_variants); LookDirections variants stay Starfield's (no base of ours).
Verified (owner's anim_cache_clips on the regenerated CK cache, 2026-11-15): after mood_variants (Sit 352 variants,
the other sets 95-119 each, mostly the upper-body prop variants) the clips the s2s_sit cache files resolve elsewhere
fell from 862 to 121: the game does find mood variants by file name in our folder. In game unverified.
Owner's S2SCombat log (2026-11-15, player sitting on our chair): the sit-down sends LoadFurnitureGraph
'AnimTextData\Tables\Graphs\FurnitureRandomSitChair.agx' (an event our enter descriptors carry from Starfield's chair
template), then idleChairSitting, IdleFlavor (+2 s), FlavorEnd (+13 s), IdleFlavor (+14 s). So a second graph, Starfield's
random-sit chair graph, runs on our chairs with its own flavors; every earlier check covered FurnitureHeadTracking_Wrapping
only. furniture_graph_probe --graph FurnitureRandomSitChair resolves its tags.
Owner's listing of LoadFurnitureGraph payloads in Starfield's furniture descriptors (2026-11-15): FurnitureRandomSitChair
41 (bar stools, benches, chairs), FurnitureGenericSit 45 (executive chairs, character creation, console seats),
FurnitureFireWeapon 8, FurnitureSyncIdle 13. FurnitureRandomSitChair exposes one unnamed animation node and reacts to
IdleSitting (furniture_graph_probe --graph): its clips are chosen at run time. The Sit set's descriptors, ours and the
Starfield ones copied into our folder (EnterInstant: NPCs already seated when the cell loads), now load
FurnitureGenericSit instead (GRAPH_SWAP, swap_graph). Unverified in game.
Cause found (owner's search of every non-S2S mod, MO2 Overwrite and the game's Data, 2026-11-15): leftovers of the
first sitting tests replaced Starfield's own chair clips with the early (hand-IK, arms-back) conversion: MO2 mods
SkyrimChairs_replace (30 files: chair\Idle and chair\animflavor\<mood>_Idle) and SkyrimChairIdle_replace (chair and
chair\female Idle), and loose files in <Starfield>\Data\Meshes\actors\human\animations\furniture\chair (Idle.af / .afx,
female too; moved to C:\Modding\work\old_chair_test_backup). Every fall-back to a Starfield chair clip (the random-sit
graph's flavors, mood variants) played that old conversion: "the exact same way it always has". Also seen: about 25
old SkyrimMelee_* test mods each with meleeattacks.agx / player_melee.agx (the lowest enabled one wins). The Creation
Kit's DynamicIdleData (per set, the random idle lists) is now copied with the cache too. In game unverified.
Verified in game (owner, 2026-11-15): with SkyrimChairs_replace / SkyrimChairIdle_replace off and the loose chair files
moved out, the seated slump is gone ("appears fixed"). The talk / upper-body / mood-variant copies, the animflavor
answers and the FurnitureGenericSit swap stay: each keeps a Starfield clip from playing over ours, and sitting works
with them.
Owner in game (2026-11-15): Faendal now goes outside (work package verified); he still sleeps across the bed after the
-90 turn (to check: furniture.json's bed markers and the actor's vs the bed's getangle z). Embry sweeps with our Sweep
set but no broom in hand, arms placed for one. Owner's choice: convert Skyrim's broom now (not Starfield's sweep).
Needs: the broom NIF as a Starfield animation object, an ANIO record, our Sweep descriptors' AnimObjLoad / Draw naming
it, and the prop bone (Skyrim AnimObjectR -> R_AnimObject1, now in NOT_ANIMATED) keyed in the sweep clips.
scripts/armor/anim_object_probe.py gathers both games' facts first.
Skyrim's broom (2026-11-15, owner's anim_object_probe): Skyrim has no broom ANIO; its only broom mesh is
meshes\clutter\common\broom.nif (no Prn, collision). Skyrim's sweep clip (animobjectsweepingidlebase, 275 frames) holds
AnimObjectR (under NPC R Hand; rest t (0, -2.43, 7.16)) fixed at t (-24.62, -23.43, 14.21) units, q (-0.3023, -0.7091,
-0.551, -0.3199): the prop rides rigidly in the right hand ~0.53 m from the wrist (the handle held, the head below).
Starfield: AnimObjectBroom (00190D68) model AnimObjects\animobjectbroom.nif, Prn AnimObjectA (under Root); its sweep idle
keys AnimObjectA / C / D, R_AnimObject1 (under R_Wrist, identity rest) and Weapon; the template's enter / enterinstant
send AnimObjLoad / AnimObjDraw AnimObjectBroom, the exits AnimObjUnequipAll. Built: retarget.place_props (a Starfield prop
bone takes Skyrim's prop world rotation and its world offset from the hand, from the Starfield hand) via hkx_to_af
--prop AnimObjectR=R_AnimObject1 (the bone then written, not NOT_ANIMATED); furniture_anim_pack SET_PROPS (Sweep) and
PROP_SWAP (its AnimObj payloads AnimObjectBroom -> S2S_AnimObjectBroomSkyrim); stance_plugin.PROP_OBJECTS (ANIO copy of
AnimObjectBroom, model S2S\AnimObjects\BroomSkyrim.nif, FormID PROP_INDEX 48); anim_object_convert.py (Skyrim's broom
converted, root renamed, Prn R_AnimObject1, collision dropped). Assumption (supported): Skyrim's animation-object broom
had the clutter broom's geometry origin at AnimObjectR. Unverified in game.
Owner in game with the broom (2026-11-15): it appears and mostly follows the sweeping, but (1) the hands hold the
handle for seconds before it appears, and (2) at the end it detaches entirely. (1) the AnimObjLoad / AnimObjDraw frames
were Starfield's enter's; now frame 0 in our prop sets' descriptors (props_at_start). (2) Skyrim has no sweep exit, so
our set plays Starfield's exits, which key R_AnimObject1 for Starfield's setup (broom on AnimObjectA; its sweep idle holds
R_AnimObject1 1.16 m from the wrist): now, for sets with props, every non-additive Starfield clip of the template
folders is copied into ours (vanilla_leftovers force) and rewritten with the prop bone held at our Idle's hand pose
(pin_bone: CALUMI read-back, dense keys, root-motion header kept), until the exit's AnimObjUnequipAll; the mood
variants are made after that, so their exits use the pinned copies.
