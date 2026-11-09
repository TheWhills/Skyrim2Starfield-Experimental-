# NPC schedules: Skyrim AI packages -> Starfield (started 2026-11-08)

Owner: "I'd like to go ahead and try an NPC with their schedule". First NPC: Orgnar (Sleeping Giant Inn), whose day
stays inside the inn. Prerequisites done: the inn converted with its navmesh, registered in NAVI, load doors with
XNDP (docs/terrain/exterior-navmesh.md); Ralof paths through Riverwood in game.

## Format (xEdit wbDefinitionsTES5 / wbDefinitionsSF1, read 2026-11-08: supported)
Both games' PACK records have the same shape: PKDT flags / type (18 package, 19 template), PSDT schedule (month, day
of week, date, hour, minute, duration in minutes), PKCU (input count, template, version), data inputs (ANAM type +
CNAM / PLDT / PTDA / STSC value, UNAM index + BNAM name), XNAM group, a template's procedure tree. Differences: PLDT
radius int (Skyrim) vs float + collection index (Starfield); Starfield adds FLAV. An NPC's PKID list runs top-down:
the first package whose schedule and conditions fit wins.

## Plan
1. `scripts/npc/package_survey.py` (this step): Orgnar's packages, templates, inputs (references resolved to base
   object / cell), where he stands, what he owns in the inn; Starfield's package templates with their inputs and use
   counts, matched to Skyrim's by EditorID.
2. Translate: each package -> Starfield PACK with the same schedule, the matched Starfield template, inputs remapped
   (Skyrim cell -> our cell, Skyrim reference -> our placed reference via source_map.json).
3. Place Orgnar in the converted inn (ACHR in FO4Port.esm, his face / outfit from the test NPC pipeline).
4. Furniture: the inn's beds / chairs / counter are statics in our conversion; sleeping, sitting and leaning need
   Starfield furniture (FURN with markers) or idle markers. Sandbox alone works without them.
