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
