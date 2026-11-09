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
In game (owner, 2026-11-08, Orgnar selected): `getiscurrentpackage 05000E64` (our package) = 0, `getdistance` to the
bar marker 4.86 m, `getcurrentaiprocedure` = -1 (no procedure); `getcurrentaipackage` does not exist in Starfield's
console. Verified: his package does not run. The Sandbox template's Sandbox and Travel branches both read input 2
(survey PKC2), the one we fill. Next build: the vanilla package copied is preferably one located "near editor
location", and is also added unchanged after ours as an A/B (ACTOR_AB=0 to leave out): vanilla runs -> our edits break
ours; neither runs -> the NPC copy (a ChargenPreset NPC) does not run packages.
Control (owner, New Atlantis): a vanilla guard (NAGuard05Ref) reports `getcurrentaiprocedure` 11. Correction (same
day): a vanilla bartender who keeps to her bar (Nyssa Marcano) also reports -1, so -1 is not evidence of "no AI
procedure"; the earlier "verified" was wrong. `getiscurrentpackage <id>` is the check that stands. Suspect: the
NPC copied is a ChargenPreset record (flag IsCharGenFacePreset 0x4; maybe SimpleActor). PluginSpike now clears both on
the copy and prints the flags before / after, the template-actor flags and the default template.

## Cause found: the schedule month (2026-11-08)
Compared with NPC Routines Expanded (ShopkeeperSchedules.esm, owner's attachment: 297 working Starfield packages on 117
vanilla NPC overrides, added to their PKID lists). Every one of its packages, the always-on ones too, has PSDT month 0,
day of week -1, date 0; the always-on ones hour -1, minute -1, duration 0 (ours had the same apart from the month).
xEdit (wbDefinitionsCommon.pas wbPackagePSDTMonthValueToStr / wbPACKDateAfterLoad) stores the month one higher in records
of form version >= 122: 0 = any month, 1 = January. Starfield records are version 582 (the mod's PACK / NPC_ headers);
Skyrim's are below 122, where -1 = any. Mutagen writes ScheduleMonth raw (Package.xml Int8). So we wrote Skyrim's -1
into Starfield packages, which is no month at all, and none of our packages could ever be picked (verified: format and
the mod; the in-game result is the next test). That fits what the owner saw: every NPC fell through to the unchanged
vanilla package appended after ours (a near-editor-location sandbox), i.e. walked around the room.
Fixed: make_schedule.sf_schedule writes month + 1 (Skyrim's kept as skyrim_schedule); PluginSpike prints the month it
wrote next to the vanilla package's. Also Energy: the mod's sandboxes use 0.1-0.8 (186 of 191), Skyrim's scale is 0-100
(vanilla 50), so Skyrim's value x 0.01 (supported).
In game: Orgnar selected, `getiscurrentpackage 05000E64` should now be 1; before the rebuild `getiscurrentpackage
0000268B` (the appended vanilla one) should be 1, which would confirm the fall-through.
Verified in game (owner, 2026-11-08 rebuild, build printed "schedule month 0"): Orgnar behind the bar,
`getiscurrentpackage 05000E64` = 1. The month was the cause. Next: furniture / idle markers (bar-lean marker, chairs,
beds) so the packages have something to use and the NPCs animate.

## Their own faces, hair, outfits and voices (2026-11-08)
Owner: "get them working like the others. with their voices, and see them in their schedules spots". face_fit.py
--test-plugin already makes each fitted NPC a real record in S2SFaceTest.esm (face dials, Skyrim hair / beard from
S2SSkyrimHairs.esm, outfit from S2SArmorTest.esm, Skyrim name, voice type with its Skyrim greetings; the greetings are
conditioned GetIsID on that record, npc_voice.py). A copy would lose the greetings (new FormID), so PluginSpike now
OVERRIDES that record (packages, AI flags as before) and places it; make_schedule.py writes "face_npc" (plugin, path,
form id from faces.json) when the NPC has its own test NPC, else notes it and the generic copy stays. ACTOR_LOOK=generic
for the old copy (A/B). FO4Port.esm then masters S2SFaceTest.esm and its masters (MO2 mods: FO4Port.esm must load after
them). face_fit numbers its NPCs by position: rebuild FO4Port.esm after every face_fit run.

## First look with their own looks (owner, 2026-11-08)
Orgnar's outfit good. Embry: shirt missing (bare chest cut where the skin piece ends), pants / boots / bracers show.
gear_fit.json (verified): his Skyrim farm clothes are one armor (farmerrobe_1.nif) with two shapes, robemorph (shirt)
and Pants, and both got that armor's Starfield slots [3, 5]; Orgnar's one-shape torso on [3, 5] showed whole.
Reading (supported): one addon per biped slot, the later one wins. gear_fit now gives each written part slots of its
own (distinct_slots: a part whose slots are taken moves to a free Vis Only slot 10-12 / 14-15).
Delphine: the dress Ysolda wears cleanly came through at the shoulders. faces.json (verified): Delphine's test NPC was
copied from CF_KlaudiaSwist (picked by skin tone), Ysolda's from ChargenPresetFemale04; outfits follow only the three
weight sliders. face_fit now gives every test NPC the body (MWGT, MRSV) of ChargenPresetFemale04_Swap (male) /
ChargenPresetFemale04 (female), the bodies the outfits were checked on (--body-npc to choose, 'none' for the
template's). In game unverified.

Second look (owner, 2026-11-09, after the fixed body): Embry's outfit good. Delphine's dress still shows skin on both
shoulders, now with the same body (MWGT of ChargenPresetFemale04) as Ysolda, so the body is ruled out (verified,
faces.json). The bare areas follow the stitched patches of the texture, not the body's shape: reading (supported, not
verified): the diffuse alpha is low in those patches and our material keeps Skyrim's alpha test, or Delphine's outfit
is a different mesh / texture variant than Ysolda's. scripts/armor/outfit_probe.py measures both (queue step 6b).
outfit_probe (owner's run, verified): both wear ClothesFarmClothes04, the same robef_1.nif, the same texture, no
alpha test, no alpha under the threshold anywhere: the texture hypothesis is dropped too. What differs is where each
was seen: Ysolda spawned from S2SFaceTest.esm, Delphine as FO4Port.esm's copy of her face-test NPC (Mutagen DeepCopy
in dotnet/PluginSpike at build time). Reading (supported): that copy is from before the body fix (Riverwood not rebuilt
after face_fit) or does not carry the body fields through. scripts/npc/npc_record_diff.py compares the two records.
npc_record_diff (owner's run, verified): FO4Port.esm's Delphine has MWGT [0.22, 0, 0] (CF_KlaudiaSwist's body) where
S2SFaceTest.esm now has [0.09, 0, 0] (ChargenPresetFemale04's), and both her and Orgnar's face dials (FMSI / FMRS)
differ: the Riverwood build is from the face_fit run before. The copy itself carries MWGT through (PKID differs as
expected: the build adds the packages). Fix: rebuild Riverwood after every face_fit run (as documented).
After the rebuild (owner, 2026-11-09, verified in game): Delphine still bare on the shoulder tops, Ysolda next to
her clean. Same Skyrim outfit (0009D5DF), mesh and texture, same body now; but each NPC has its own gear_fit
conversion in S2SArmorTest.esm (S2S_Ysolda_outfit_Outfit 03000811, S2S_Delphine_outfit_Outfit 030009C1), made in
different runs with different fit code. Next: refit Delphine's with today's gear_fit (as Embry's, which fixed his
shirt); outfit_probe now also lists each shape's openings and whether Skyrim's own body piece lies under them.
Lasting fix: step 9's clothes as items, one conversion per Skyrim outfit shared by everyone wearing it.
Refit with today's code (owner, 2026-11-09): still round bare patches on the shoulder tops. Owner: Ysolda's dress was
made before the iron-armour changes. Of those, the 2026-11-08 armpit change matches (verified in code, in game
unverified): gear_fit.armpits kept every body vertex within 8 cm of the torso / arm weight seam in the skin piece, and
that seam rings the whole shoulder, so the shoulder top was skin under a tight sleeve. Now only the lower half of each
side's seam and the body no higher than it.





## Readiness across the batch (2026-11-09; offline checks only)
scripts/npc/schedule_readiness.py runs make_schedule's own package conversion as a dry run for every NPC placed in
the batch's cells: per NPC the packages converted or left out and why (conditions / quest-owned, a location outside
the converted cells, no Starfield template, ...), the furniture kinds its packages point at (make_furniture's
kinds, "static" when there is none), whether face_fit made its face-test NPC (a faces.json `test_npc` that is a
string is the reason none was made), a status (ready / partial / blocked) and the -Actors list for
riverwood_doors.ps1. Writes readiness.json / readiness.md. To scale from three NPCs to the whole of Riverwood.
