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

## Orgnar (survey 2026-11-08, owner's run)
One package, OrgnarWorkInn0x24, all day (no schedule), Skyrim template SandboxWorking (travel, unlock doors, sandbox),
speed Run(2), values in UNAM order [0, 14, 1, 3, 4, 5, 6, 31, 7, 25, 27, 29]: Location = near XMarker 000BD056
(in the inn) radius 256 units (3.66 m); Unlock On Arrival no; Allow Eating yes; Sleeping no; Conversation yes; Idle
Markers yes; Sitting no; Special Furniture yes; Wandering no; Preferred Path no; Ride Horse no; Energy 1.0. Placed at
(-1312.8, 18.3, 0) in RiverwoodSleepingGiantInn; owns CounterBarLeanMarker (FURN) 0006DEB4.
Starfield: 122 package templates; Sandbox (00002CB1, 577 uses) has the same procedures (Travel, UnlockDoors, Sandbox)
and inputs by name (Location at 2, Unlock on Arrival? 12, Allow Eating 5, ... Energy 18).

## Step 2 (2026-11-08): make_schedule.py + PluginSpike ACTORS
`scripts/npc/make_schedule.py` writes <work>/actors.json: Skyrim template -> Starfield (SKY_TO_SF, else same EditorID),
inputs matched by normalized name, near-reference locations with the Skyrim ref and its spot. PluginSpike (ACTORS env):
a copy of the first vanilla package using that template (all other inputs keep vanilla values), schedule / speed from
Skyrim, conditions / quest / scripts dropped; the referenced ref -> our placed copy, else a Starfield XMarker (0x3B,
assumed as in Skyrim / FO4: unverified) placed persistent at its spot; radius written as float bits (xEdit SF1 says float;
Mutagen keeps u32; PluginSpike prints the vanilla value both ways). NPC: copy of face_fit's vanilla template for that NPC
(faces.json), name, packages = ours, AI-package template flag cleared, scripts dropped; placed as a persistent ACHR.
Not yet: his face / hair / outfit (the test NPC lives in S2SFaceTest.esm, an MO2 plugin), furniture (the bar-lean
marker is a static here), dialogue / vendor. `riverwood_doors.ps1 -Actors Orgnar` runs it.

## Delphine and Embry (survey 2026-11-08) and the rules that came from them
Delphine: 14 packages, the first ones from the main quest (Sky Haven Temple practice / sandbox / sleep, return to
Riverwood) before her inn routine (DelphineInnServices6x18 SandboxAndKeepEyeOn, Eat 6 and 18, DelphineSleep0x6,
DefaultSandboxEditorLocation512NoWeapons). Embry: Sleep 0-7, Eat 7-8, Loiter 8-17 (Sandbox), inn 17-1 (Sandbox),
Patrol (default). make_schedule.py now: leaves out packages with conditions or an owner quest (their conditions are
not converted, and the first matching package wins: unconditioned quest packages would take over;
`--keep-conditioned` keeps them); leaves out packages whose location is outside the batch's interiors (Embry's daytime
loiter outside, until NPCs go outdoors); Skyrim Eat (no Starfield template) -> Sandbox with Allow Eating / Sitting on.

## First build with packages (owner's run 2026-11-08)
PluginSpike compiled and wrote Orgnar (1 package), Delphine (5: Eat 6 / 18, InnServices 6-18 SandboxAndKeepEyeOn,
Sleep 0-6, default sandbox) and Embry (4: Sleep 0-7, Eat 7-8, inn 17-1, Patrol default) into FO4Port.esm.
**Verified:** Starfield's PLDT radius is a float: the vanilla packages copied hold raw bits 40A00000 (5.0) and 40400000
(3.0). Vanilla NPC copies: ChargenPresetFemale04_Swap (030764, Ralof's face_fit template) for the men,
ChargenPresetFemale04 (050569) for Delphine. In-game behaviour: unverified.

## First in-game look (owner, 2026-11-08)
All three NPCs walked around the room; Orgnar did not keep to the bar. Reading: none of their packages ran, so each
fell back to its vanilla copy's default (an NPC wanders when no package in its list can run) (supported). Suspects:
the vanilla packages copied were the first users of each template, some owned by quests with alias inputs, made
invalid when the quest was dropped; and the XMarker 0x3B, assumed. Changed: PluginSpike copies a vanilla package with
no owner quest / scripts / conditions / alias inputs (prints which), make_schedule.py looks XMarker up in
Starfield.esm. Also: the inn's room doors were solid statics NPCs walked into (navmesh passes through); non-load doors
are now left out (open doorways; INNER_DOORS=static keeps them) until doors that open are converted.
In game check: select the NPC, `getiscurrentpackage <package id>` (ids printed by the build).
Owner, same evening: Orgnar "stood behind the bar for a second and then left". Reading (supported): his package ran,
but with wandering off and only furniture / idle markers allowed, his sandbox found nothing to use within 3.66 m (the
bar-lean marker and every chair / bed are statics here), so he left it. make_schedule.py now turns Allow Wandering on
for Starfield sandbox packages (inside their radius) until furniture is converted (`--keep-furniture-only` to keep
Skyrim's setting).
