# Riverwood complete: the checklist

Owner (2026-11-17): "for now, getting Riverwood fully completed with children, all animations, all items ... will
translate well to all other cities." Riverwood is the proving ground: everything here is done as a converter (never
hand-placed), so a solved item is solved for every town that uses the same Skyrim records. A row is done when the
converted thing works in game in a clean start (`coc SKY_TamrielRiverwoodSpawn` from the main menu) and its tool has a
synthetic test; status words: done / partial / open.

## What Riverwood does not exercise (cities need these on top)
Beast races (no Khajiit or Argonian lives here: supported, to confirm from the NPC list), guards, crime and bounty,
city walls / gates and their own worldspace (the gates are not linked yet), jarls and courts, and city scale (several
times the NPCs, interiors and objects; a whole-world build has never been run).

## Checklist

| Area | Item | Status | Notes / where |
|---|---|---|---|
| World | Exterior terrain, objects, grass, LOD, water | done | docs/terrain/skyrim-*.md |
| World | The six interiors, collision, lighting, load doors both ways | done | docs/interior/skyrim-interiors.md; 15 of 265 models fail ("no triangle geometry") |
| World | Interior and exterior navmesh | done | docs/terrain/exterior-navmesh.md |
| World | Fires, candles, forge fire | partial | flames done; outdoor lights / the forge light to check |
| World | Doors that open in place (not load doors) | open | scenery today |
| World | Sound and ambience; outdoor effects (fog, spray) | open | |
| People | The 12 adults: faces, hair, records | partial | faces in the face-test plugin; clothing / armor in game to check |
| People | Children (Dorthe, Frodnar) | open | docs/npc/races-roadmap.md I2; then DorthePlay's "near the NPC" target is exercised |
| People | Dialogue / voices | partial | Starfield generic voice types; Skyrim voice pipeline docs/npc/voice-pipeline.md |
| Creatures | Riverwood's animals (to list from the data: chickens, a dog, ...) | open | first creature conversion: skeleton, behaviour, race |
| Schedules | Converted packages, settled Riverwood moment | done | docs/npc/schedules.md, docs/ai/decisions.md |
| Schedules | Eat location, carry start | partial | INPUT_ALIAS (2026-11-17), to check in game |
| Schedules | Sandbox moves between stations (Alvor), no endless repeat (Hilde) | open | -SitAt block test pending; docs/npc/furniture.md |
| Schedules | Play-dependent conditions (Frodnar near the player, Delphine's return) | open | Starfield conditions not written |
| Schedules | Carry and drop (Faendal's firewood), multi-location days (Faendal, Gerdur), Hod at the inn | open | rebuild from Starfield procedures |
| Schedules | Patrol routes (Camilla, Embry, Hilde), bed / food / chair choice | open | Patrol Start, Sleep / Eat criteria kept vanilla |
| Furniture | Sit, lean, sweep (broom), cook, alchemy, enchant, beds | done | Skyrim's own clips |
| Furniture | Forge, grindstone, armor workbench, tanning rack | partial | clips and props done; walk-in to forge / grindstone open |
| Furniture | Idle markers (patrol, flowers, drunk, farming, lockpick, ...) | open | skipped as "stand" today |
| Work | Wood chopping (axe, wood halves) | open | next; probe done (props on state enter, 10.9 s loop) |
| Work | Woodpile pick-up / put-down, carrying firewood (arm offset) | open | |
| Work | Sawmill: log loading, the mill's own animation, its script | open | Hod's packages wait on the script |
| Work | Farming (hoe), buckets, lever | open | |
| Props | Automatic prop conversion (clip triggers and state enter events) | open | docs/npc/furniture.md 2026-11-17 |
| Items | Loose items as real items (food, wine, clutter), ownership | open | docs/interior/items.md |
| Items | Containers, merchant inventories | open | |
| Scripts | The sawmill and other scripted activators in Riverwood | open | no Papyrus translation yet |

Converting every package with its conditions (quests, scenes) stays the end goal after this (docs/ai/decisions.md).
