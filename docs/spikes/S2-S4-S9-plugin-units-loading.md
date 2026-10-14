# S2, S4, S9: plugin writing, units, and loading (2026-10-07)

Fallout 4 1.10.163, Starfield 1.16.244. Code: `dotnet/PluginSpike`, `scripts/deploy_starfield.py`,
`scripts/oracles/calibrate_units.py`. **None of this has been confirmed in the running game yet.**

## S2: plugin writing with Mutagen: offline GO

`Mutagen.Bethesda.Starfield` 0.55.0-alpha.67 (NuGet, .NET 9) writes and reads back a Starfield plugin.

```csharp
var mod = new StarfieldMod(ModKey.FromNameAndExtension("FO4Port.esm"), StarfieldRelease.Starfield);
mod.ModHeader.Flags |= StarfieldModHeader.HeaderFlag.Master;
var stat = new Static(mod) { EditorID = "FO4Port_ChairPatio01" };
mod.Statics.Add(stat);
stat.Model = new Model { File = "fo4port\\setdressing\\chairpatio01.nif" };   // written as Meshes\fo4port\...
mod.WriteToBinary(path);
```
(`mod.Statics.AddNew(...)` does not exist in this version; use `new Static(mod)` then `Add`.)

Checked with our own plugin scanner (`scripts/recon.py`): HEDR version 0.96 like vanilla, one `STAT` with
`EDID, OBND, ODTY, MODL, DNAM`, 222 bytes, no masters. Differences from vanilla `Starfield.esm`: **form version 576**
(vanilla 581) and header flags `0x1` (vanilla `0x81`, i.e. also "localized"). Whether the game accepts form version 576
is the open question; Mutagen-based mods are known to ship it, but this build must prove it.

## S4: units: strong offline support for 1 Fallout 4 unit = 1/70 m

Median Z-height of same-category vanilla props, Fallout 4 units vs Starfield metres (`calibrate_units.py`):

| category | FO4 (units) | SF (m) | units / m |
|---|---|---|---|
| chair | 70.9 | 0.98 | 72.7 |
| stool | 53.8 | 0.77 | 69.9 |
| couch | 65.3 | 0.92 | 70.9 |
| barrel | 77.8 | 1.00 | 77.6 |

The clean categories sit at 70-78. Noisy ones (bed, crate, sink, desk) mix accessories with the main prop and are
ignored. The converter default `UNIT_SCALE = 1/70` stays. Still to confirm in game by standing the converted chair
next to a vanilla one.

## S9: loading harness

- Starfield loads the loose files only with `bInvalidateOlderFiles=1` / `sResourceDataDirsFinal=` in
  `StarfieldCustom.ini` under *Documents\My Games\Starfield*. On this machine **Windows Controlled Folder Access
  blocks writes to Documents** from Python and PowerShell (the error is a misleading "file not found"). We do not
  change that security setting.
- **Workaround that needs no ini:** pack assets into `<plugin> - Main.ba2` (loaded automatically beside
  `<plugin>.esm`) with the official `Archive2.exe` that ships in `Starfield\Tools\Archive2` with the Creation Kit.
  Output is BA2 version 2, GNRL; our reader extracts both files byte-identical to the sources.
- The plugin is enabled by a line `*FO4Port.esm` in `%LOCALAPPDATA%\Starfield\Plugins.txt` (writable).
- `scripts/deploy_starfield.py install|uninstall` does this reversibly (manifest in `Data/FO4Port.deploy.json`;
  refuses to overwrite files).

## How to check it in the game (one person, about 5 minutes)

1. Launch Starfield, load any save (use a throwaway), open the console with `~`.
2. Starfield does not keep editor IDs at runtime, so `help` cannot find the chair. The FormID is `<slot>000800`, where `<slot>`
   is the plugin's load slot (it was `02` here). Try `player.placeatme 02000800`; "not found" means try another slot.
3. The chair spawns at the player's feet: close the console and step back to see it.
4. Walk into it (no collision yet, expected), and compare its size with a vanilla chair.
5. Report: renders? right size? right orientation (not mirrored/inside-out)? crash on load?
6. Remove everything with `python scripts/deploy_starfield.py uninstall --starfield <game dir>`.

## In-game result (2026-10-07)

- The game loaded `FO4Port.esm` (Mutagen, form version 576) with `FO4Port - Main.ba2`; no prompt, no crash.
- Runtime FormID of the chair: the plugin sat at **load slot 02** on this machine (`player.placeatme 02000800` succeeded;
  slots 01 and 03-0B returned "not found"). The slot depends on the load order, so probe if yours differs.
- `help <editor id> 4` finds nothing: Starfield does not keep editor IDs of statics at runtime. Use the FormID.
- Console input from automation: the game ignores `SendInput` keyboard events but accepts legacy `keybd_event` and mouse
  clicks (see journal).
- The chair rendered correctly (see S1). Screenshot: [media/fo4-chair-in-starfield.png](media/fo4-chair-in-starfield.png).
