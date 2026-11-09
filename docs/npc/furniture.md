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
