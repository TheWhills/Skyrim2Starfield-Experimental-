# Skyrim2Starfield (Experimental)

**Converters that bring The Elder Scrolls V: Skyrim Special Edition into Starfield's engine (Creation Engine 2):
Skyrim's world as native Starfield terrain, its towns, interiors, people, animations and creatures, converted from
your own game copies.** No game assets are included or distributed; every tool reads your installs and writes to
your machine.

The goal is a faithful, walkable Skyrim inside Starfield: the world as the player sees it for most of the game, then
everything else. Riverwood is the proving ground. Each piece is built as a converter rather than placed by hand, so
whatever works in Riverwood works for every town that uses the same Skyrim records
([the Riverwood checklist](docs/RIVERWOOD-COMPLETE.md)).

## Status

Working in game (each item verified by the owner on Starfield; details and dates in the linked notes):

| Area | What works | Notes |
|---|---|---|
| World | Skyrim's Tamriel terrain as a Starfield overlay on a planet, ground textures, Riverwood's river at Skyrim's level, exterior objects, grass (as static patches for now), distant-object LOD | [terrain](docs/terrain/skyrim-tamriel.md), [objects](docs/terrain/skyrim-objects.md) |
| Interiors | Riverwood's interiors with native collision, load doors both ways, lighting, hearth and candle fires | [interiors](docs/interior/skyrim-interiors.md) |
| People | Skyrim NPCs with fitted faces, their own hair, Skyrim races (skin, ears, hair) and their clothing as items | [NPCs](docs/npc/README.md), [races](docs/npc/races.md) |
| Schedules | NPC packages converted to Starfield's, in the "settled Riverwood" moment (e.g. Orgnar behind his bar) | [schedules](docs/npc/schedules.md) |
| Furniture | Sitting, leaning, beds for the player, the alchemy lab, and NPCs working the forge, armor workbench and tanning rack, all with Skyrim's own animations and props | [furniture](docs/npc/furniture.md) |
| Combat | Skyrim weapon animations on Starfield's skeleton, with root motion (swings carry the player, power attacks dash) | [animation](docs/armor/animation-port.md) |
| Creatures | **New:** the first Skyrim creature on its own skeleton. Riverwood's chicken is drawn, textured and animated on Starfield's critter graph; movement is still being tuned | [creatures](docs/npc/creatures.md) |

Built and tested offline but not yet confirmed in game: the walled cities as their own spaces, the Skyrim voice
pipeline, the remaining work animations (wood chopping, the sawmill, farming), and children.
Open: quests, dialogue and scripts; magic ([notes](docs/magic/README.md)); beast races in cities; the whole world
in one build. The [Riverwood checklist](docs/RIVERWOOD-COMPLETE.md) tracks each item as done, partial or open.

## How it works

Each converter is deterministic and resumable. It reads Skyrim's records and assets (plugins, BSAs, NIF, HKX,
behaviour graphs), translates them to Starfield's formats (`.mesh` / NIF, `.mat`, `.af` / `.afx` / `.rig`, plugin
records, terrain overlays), and writes a mod you enable in Mod Organizer 2. Claims about file formats carry evidence
labels (**verified**, **supported hypothesis**, **unresolved**), and every tool has synthetic-fixture tests.

| Path | What |
|---|---|
| [docs/RIVERWOOD-COMPLETE.md](docs/RIVERWOOD-COMPLETE.md) | What "Riverwood complete" means, item by item |
| [docs/OWNER-SETUP.md](docs/OWNER-SETUP.md) | Folders, tools and the exact commands to build and test on a PC |
| [docs/terrain/](docs/terrain/) | Tamriel, objects, grass, LOD, cities, navmesh |
| [docs/interior/](docs/interior/) | Interiors, items |
| [docs/npc/](docs/npc/) | NPCs, races, schedules, furniture, creatures, voices |
| [docs/armor/](docs/armor/) | Armor, skeletons and animation (clips, graphs, root motion, combat) |
| [docs/research/](docs/research/) | Studies of other converters (e.g. [tes4skyrim](docs/research/tes4skyrim.md)) |
| [docs/ai/decisions.md](docs/ai/decisions.md) | Architectural decisions, with reasons and alternatives |
| [src/fo4sf/](src/fo4sf/) | The conversion library (Python; package name kept from upstream) |
| [scripts/](scripts/) | Command-line converters, probes and builders, by area |
| [dotnet/](dotnet/) | Plugin writers (Mutagen-based .NET tools) |
| [tools/owner/](tools/owner/) | One-command PowerShell builds for the owner's PC |

## Quick start

```
git clone https://github.com/TheWhills/Skyrim2Starfield-Experimental-
cd Skyrim2Starfield-Experimental-
python -m unittest discover -s tests      # synthetic fixtures only, no game files needed
python scripts/guard.py                   # must pass before every commit
```

Building anything for the game needs your own Skyrim Special Edition and Starfield installs (plus the Creation Kit
for some steps). [docs/OWNER-SETUP.md](docs/OWNER-SETUP.md) lists the tools and the commands.

## Rules of the repo

- **No game data, ever.** No `.esm`, `.bsa`, `.ba2`, `.nif`, `.dds`, `.mesh`, `.hkx`, `.af`, `.wem`, executables, or
  anything derived from them beyond statistics. `scripts/guard.py` enforces it.
- Converters read your copies of the games; output stays on your machine.
- Offline / single-player only.
- AI-assisted: much of this project is written with AI coding assistance (commit subjects name the agent, e.g.
  `Claude:`). Contributions of any kind are welcome; please say if yours was AI-assisted.

## Origins

This repository started as a fork of [fo4sf/fo4-to-starfield](https://github.com/fo4sf/fo4-to-starfield) (MIT), the
Fallout 4 → Starfield toolchain by **dasscooby** and its AI collaborators (Claude, Codex, Grok), taken from its
`claude/terrain-core64-objects` branch. Its Fallout 4 work is still here and still the foundation: the `.mesh` / NIF
writer, materials, native collision, plugin generation, terrain overlays, and converted Fallout 4 interiors (Vault 111,
Hotel Rexford and more): see [docs/JOURNAL.md](docs/JOURNAL.md), [docs/PLAN.md](docs/PLAN.md),
[docs/FORMAT-GAP.md](docs/FORMAT-GAP.md) and [docs/spikes/](docs/spikes/). This fork, led by **TheWhills**, points
that toolchain at Skyrim.

## Related projects

- [fo76utils/nifskope](https://github.com/fo76utils/nifskope): NifSkope fork with Starfield `.mesh` / `.mat` support
- [Mutagen](https://github.com/Mutagen-Modding/Mutagen): .NET library with Skyrim, Fallout 4 and Starfield records
- [xEdit](https://github.com/TES5Edit/TES5Edit): plugin editor (`SSEEdit`, `xSFEdit`)
- [PyNifly](https://github.com/BadDogSkyrim/PyNifly): Blender NIF import/export
- [tes4skyrim](https://github.com/bryantmh/tes4skyrim): Oblivion / Morrowind → Skyrim converter (studied in
  [docs/research/tes4skyrim.md](docs/research/tes4skyrim.md))
- [SFSE](https://sfse.silverlock.org/): Starfield Script Extender

## Legal

The Elder Scrolls, Skyrim, Fallout, Starfield and Creation Engine are trademarks of Bethesda Softworks / ZeniMax
Media. This project is unofficial and unaffiliated. It contains no Bethesda content. You need legitimate copies of
the games. Licence: [MIT](LICENSE) (code and documentation).
