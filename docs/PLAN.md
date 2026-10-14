# Plan: bringing Fallout 4 into Creation Engine 2

Status: **planning + measurements complete; no converter exists yet.** This document is the long-term
method. [WORK-PACKAGES.md](WORK-PACKAGES.md) breaks it into independent tasks and
[RISKS.md](RISKS.md) lists what could stop it and how to find out cheaply.

## 1. What "Fallout 4 in Starfield's engine" means

`Starfield.exe` (Creation Engine 2) can't be modified or rebuilt: there is no source. So the goal is a
**total conversion that runs on the stock Starfield executable**: Fallout 4's content is converted into
Starfield's formats and loaded as a mod (plugin + loose files, with [SFSE](https://sfse.silverlock.org/)
plugins where Papyrus can't reach).

Fallout 4's own engine (Creation Engine 1) is not replaced; only its data is carried across.

### Non-goals
- Redistributing any Bethesda asset. The project ships **converters and documentation only**. Every user
  runs them on their own copies of both games.
- Pixel-perfect parity. Fallout 4's gameplay systems (VATS, Pip-Boy, settlements) get Starfield-native
  equivalents, not reimplementations.
- Online/multiplayer anything.

## 2. Why a pipeline, and not the alternatives

| Approach | Verdict |
|---|---|
| Rebuild the Commonwealth by hand in the Starfield Creation Kit | Years of artist time, none of it reusable or checkable. |
| Reimplement Creation Engine 1 inside Starfield via native hooks | Starfield's renderer, physics and animation can't be driven from Fallout 4 data without the same conversions below, plus a hook layer on top. |
| Run both games and pass state between them ([passthrough](https://github.com/rehan-remade/universal-modder/blob/main/skills/mashup-mods/SKILL.md)) | Fine for a cube or a creeper. Not a way to play a 200 h RPG. |
| **Automated, resumable conversion pipeline (chosen)** | Every conversion is code, so it is repeatable, testable, improvable, and can be continued by anyone, with or without an AI, in small pieces. |

## 3. Design principles

1. **Deterministic code, not generation.** Converters are ordinary programs. Re-running them on the same
   input gives byte-identical output. Nothing needs an LLM to keep going.
2. **Open intermediate representation (IR).** FO4 → neutral open formats → Starfield. Meshes via glTF/OBJ,
   textures via PNG/DDS, materials via JSON, records via JSON. Readers and writers are then independent
   tasks, each testable alone, and Blender (or any viewer) can inspect the middle.
3. **Graceful degradation (fidelity tiers).** Every asset gets the best tier available, and the build always
   completes:
   - **T0** placeholder: bounding box + a generic material
   - **T1** geometry + base colour
   - **T2** full material (normal / roughness / metal / emissive)
   - **T3** collision and physics
   - **T4** skeleton / animation
   Early demos use T0–T1 everywhere, then quality rises asset class by asset class without breaking the build.
4. **Oracles before code.** Each stage has a machine check that proves it works (see §6). A stage is not
   done until its oracle passes in an automated test.
5. **Data-driven mappings.** Keyword, material, bone, record-field and unit mappings live in versioned
   tables (JSON/TOML), not in code, so non-programmers can contribute and diffs are reviewable.
6. **Stable identity.** Each converted record gets a FormID derived deterministically from the Fallout 4
   FormKey (a fixed namespace plugin, `FO4Port_*.esm`). Re-runs are incremental and saves don't break.
7. **Loose files first.** Starfield loads loose files. Because only the converter is distributed and users
   generate their own assets, BA2 packing is just an optimisation and comes last.
8. **Interiors before exteriors.** Interior cells need no terrain. The vertical slice goes
   item → static → interior cell → actor → exterior (§5).
9. **Pin versions.** Fallout 4 **1.10.163** (pre-Next-Gen) and Starfield **1.16.244** (SFSE 0.2.21).
   Record the versions in every output manifest.
10. **Evidence journal.** `docs/JOURNAL.md` records each experiment: date, versions, command, result,
    the oracle output. Knowledge that isn't written down doesn't exist.

## 4. Architecture

```
FO4 install ──► extract ──► IR (work dir) ──► convert-* ──► Starfield staging dir ──► verify ──► Starfield/Data
 (read-only)    (BA2,ESM)   glTF/PNG/JSON      mesh, tex,     Data/ layout + FO4Port_*.esm        oracles     (loose files)
                                                mat, coll,
                                                records
```

| Layer | Language | Why |
|---|---|---|
| Archive/NIF/mesh/texture/material/collision tools | Python 3.12+ | Fast to iterate, existing readers in `scripts/` |
| Plugin read/translate/write | C# / .NET 9 with [Mutagen](https://github.com/Mutagen-Modding/Mutagen) | It has record libraries for **both** `Mutagen.Bethesda.Fallout4` and `Mutagen.Bethesda.Starfield` (the latter is alpha on NuGet, spike S2) |
| Visual inspection | [fo76utils NifSkope](https://github.com/fo76utils/nifskope), xEdit (`xSFEdit`), Starfield Creation Kit | Open source / official; double as oracles |
| Artist-in-the-loop (rigging, weight fixes) | Blender 5.x + PyNifly (FO4) + Starfield Blender extension | Only where automation can't decide |

Work and output directories live **outside the repo** (`config.toml` → `work_dir`, `staging_dir`). Nothing
derived from game files is ever committed (enforced by `scripts/guard.py`; CI template in `ci/`).

Planned repo layout (grows as work packages land):
```
src/fo4sf/        python package: readers, converters, CLI (python -m fo4sf <stage>)
dotnet/           Mutagen-based plugin translator
mappings/         data-driven tables (keywords, materials, bones, units, record fields)
tests/            synthetic fixtures only; no game data
scripts/          recon + guard + one-off research scripts (current contents)
docs/             plan, risks, format notes, spikes, journal, measurements
```

## 5. Phases and exit criteria

| Phase | Deliverable | Exit criterion (all automated or screenshot-verified) |
|---|---|---|
| **P0 Spikes** | One written go/no-go per risk (RISKS.md S1–S9) | Each spike's oracle passes or its fallback is chosen |
| **P1 Items** | A converted weapon, outfit and consumable usable in Starfield | Appears in inventory with correct mesh/material, equips, fires/animates using Starfield rigs |
| **P2 Statics + interior** | Vault 111 interior as a Starfield cell | Walkable: collision, navmesh, lights, doors/furniture placed from FO4 `REFR`s |
| **P3 Actors** | Human NPCs and one creature with working skeleton | Stands, idles, walks; faces generated |
| **P4 Exterior** | Sanctuary Hills exterior (terrain + statics) | Walk from Vault 111 elevator to Sanctuary on converted terrain |
| **P5 Systems** | Dialogue/voice, quests, Papyrus, Pip-Boy/VATS equivalents | First quest playable |
| **P6 Scale** | Bulk-run everything, dashboard shows coverage per record/asset class | Coverage % published automatically |

Each phase is useful on its own: P1 alone is a "Fallout 4 gear in Starfield" mod, P2 a "Vault 111"
location mod. Stopping after any phase leaves something working.

## 6. Verification ladder (the oracles)

| Level | Check | Automation |
|---|---|---|
| L0 | Output parses with our own reader and round-trips | unit tests (synthetic fixtures) |
| L1 | Output opens without errors in NifSkope / xSFEdit | headless where possible (`xSFEdit` scripts, NifSkope batch), else manual checklist |
| L2 | Starfield Creation Kit loads the plugin and renders the asset | CK log scrape + screenshot |
| L3 | Starfield launches, loads the cell/item, screenshot matches expected silhouette | `um win` / game-automation scripts, image diff against a golden mask |
| L4 | Gameplay check (equip, shoot, walk, trigger) | scripted via console commands and SFSE |

A per-asset **manifest** records the highest level each asset reached; the README coverage table is
generated from it.

## 7. Working on a small budget (time or money)

- Every work package is **self-contained** (inputs, outputs, acceptance test in WORK-PACKAGES.md). One
  session can finish one.
- Do **spikes first**: they are short, and each one kills or confirms an assumption before expensive work.
- Prefer **cheap compute over expensive thinking**: bulk scans, batch conversions and screenshots cost no
  tokens once the scripts exist.
- To resume with any coding agent, point it at: `docs/PLAN.md`, `docs/WORK-PACKAGES.md`,
  `docs/JOURNAL.md`, and say "do the first work package marked `ready` and update the journal".
- GitHub issues mirror the work packages; claiming one is enough to coordinate.

## 8. Quality bars for contributions

- No game data in commits (`scripts/guard.py` must pass).
- Every converter ships with a synthetic-fixture test and states which oracle level it reaches.
- Mapping changes are data edits with a short rationale in the PR.
- Disclose AI-assisted code in the PR description; the project itself was started with AI assistance.

## 9. Passive discoverability (no announcements)

The aim is that someone searching for this finds it without being told about it:
- Repo name, description and topics use the words people search: *fallout 4*, *starfield*, *creation
  engine 2*, *port*, *convert*, *nif*, *ba2*, *mesh*, *havok*, *terrain*.
- The most findable content is the **format research** (`docs/FORMAT-GAP.md`, `docs/spikes/*`): plain,
  specific answers to questions modders ask ("what replaced `LAND` in Starfield?", "what is a `.mesh`
  file?"). Each has a descriptive title and numbers.
- Regular, small, well-described commits and a visible coverage table signal a living project.
- Issues are written as standalone tasks so a visitor can act on one.
