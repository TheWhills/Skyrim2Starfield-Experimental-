# Starfield voice + lip pipeline (what UNITY proved works)

Taken from UNITY's `unity_wem_gen.py` (attached), which got WAVs playing out of NPCs' mouths with lip-sync on Starfield 1.16.244. For the Skyrim-to-Starfield voice work.

## Tools (all were working)

| Tool | Version / location |
|---|---|
| WwiseConsole | **Wwise 2021.1.14.8108**: `C:\Audiokinetic\Wwise_2021.1.14.8108\Authoring\x64\Release\bin\WwiseConsole.exe` |
| Wwise project | `<Starfield>\Tools\wwise\Starfield\Starfield.wproj` (ships with the Creation Kit) |
| LipGenerator | `<Starfield>\Tools\LipGenerator\LipGenerator.exe` |
| ffxc (FaceFX compiler) | `<Starfield>\Tools\FaceFX\ffxc.exe` |
| FaceFX actors | `Tools\FaceFX\StarfieldHumanMale.facefx`, `StarfieldHumanFemale.facefx` |
| FaceFX analysis | `Tools\FaceFX\GenesisDefault.facefx` |
| Intermediate dirs | `<Starfield>\Intermediate\Slice_00` (male), `Slice_01` (female) |

## Step 1: WAV to WEM

Write a `.wsources` file:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<ExternalSourcesList SchemaVersion="1" Root="C:\path\to\wav_dir">
    <Source Path="0012ABCD.wav" Conversion="Vorbis Quality High" Destination="0012ABCD"/>
</ExternalSourcesList>
```
Then run:
```
WwiseConsole.exe convert-external-source "<Starfield>\Tools\wwise\Starfield\Starfield.wproj" --source-file x.wsources --output <outdir> --platform Windows
```
The `.wem` lands somewhere under `<outdir>` (search for it recursively). The encoding is **Vorbis Quality High**, and the platform is **Windows**.

## Step 2: lip file (.ffxanim)

1. Run LipGenerator:
   ```
   LipGenerator.exe <raw.wav> "<line text as a plain string>" <StarfieldHumanMale|Female.facefx> GenesisDefault.facefx -OutputFileName:<animset path> -AnimationGroupName:<voice folder>
   ```
2. Write a per-line `.ffxcproj` into `Intermediate\Slice_00` (male) or `Slice_01` (female):
   ```yaml
   version: 10300
   items:
    - facefx_file: <same .facefx actor>
      mount_files:
       - <animset path from step 1>
   ```
3. Run ffxc:
   ```
   ffxc.exe -o=<Starfield>\Data\Sound\Voice\<plugin>\<registered voice folder>\ -p=x86 --rebuild <that .ffxcproj>
   ```

## Traps (each one was a real bug)

- **LipGenerator takes the raw WAV, not the WEM.** Its usage banner suggests otherwise.
- **The text argument is a plain string, not a path to a .txt file.** The banner shows a .txt path, but the plain string is what worked.
- **ffxc ignores `-OutputFileName` / `-AnimationGroupName`.** It names the output after the WAV's file name, so the WAV must already be named what the final file should be called (the line's ID).
- **ffxc `-o=` must be a "registered" voice folder that already exists in the game's data.** Otherwise the output silently vanishes. UNITY used `NPCFSarahMorgan` (female) and `NPCMBarrett` (male) as compile targets, then copied the `.ffxanim` to the real folder. **For new Skyrim voice types this is the first thing to test:** whether a brand-new folder like `S2S_MaleNord` works as `-o=`, or whether you must compile into a vanilla one and copy.
- **Pick the male or female FaceFX actor per voice**, or men get women's mouth shapes.
- **Validate WAV headers before LipGenerator.** UNITY's Cartesia WAVs had bogus `data` sizes and byte rates; `parse_wav_pcm()` / `sanitize_wav_for_lipgen()` rewrite a clean header. WAVs decoded from Skyrim's `.xwm` are probably clean, but keep the check.
- **ffxc prints about 200 warnings per build.** That's normal.

## File layout and naming

- Files go in `Data\Sound\Voice\<Plugin.esm or .esp>\<VoiceTypeEditorID>\<id>.wem` with a matching `<id>.ffxanim` next to it.
- UNITY named lines with 8-hex IDs (`00666A79`...) that match INFO (dialogue response) FormIDs in its plugin. **Corrected 2026-11-05 (probe-verified):** `<id>` is the audio file ID stored in the response's TRDA subrecord (bytes 4-7, after the emotion keyword): 3,973 of genericmaleeventoned's 4,248 vanilla files are named that way, only 33 match an INFO FormID. UNITY's lines likely played through its SFSE hooks. Any unique ID works as long as TRDA and the file name agree.
- For lips, the engine reads from the NPC's actual voice-type folder. An NPC on a generic voice type only gets lips if the file is in that generic folder.

## What NOT to copy from UNITY (dynamic-only hacks)

- **The 200 rotating slots and the fixed `00666A79.ffxanim` copy:** they exist because UNITY generates lines live.
- **The SFSE path/cookie hooks:** these redirect playback at runtime. Static greetings with real INFO records and files in the right folder should play through the normal engine path, with no plugin.
- **The heartbeat / queue / bridge INI files.**

## Skyrim side (new work)

- **Unpack `.fuz`:** `FUZE` magic, a version, the lip-data size, then Skyrim's `.lip` (not usable in Starfield; regenerate it with LipGenerator), then the `.xwm` audio.
- **`.xwm` to `.wav`:** ffmpeg decodes xWMA, or use xWMAEncode.exe from the old DirectX SDK.
- **Line text** comes from the INFO response text in Skyrim.esm. Feed it to LipGenerator for word-accurate lips.

## In this repository (2026-11-05)

- `src/fo4sf/skyrimdialog.py`: Skyrim topics / responses (INFOs in each topic's child group), the response texts
  (`strings\skyrim_<language>.dlstrings`), who speaks a line (GetIsID / GetIsVoiceType conditions), the voice file
  index (`sound\voice\skyrim.esm\<voice type>\..._<INFO FormID>_<n>.fuz`) and the .fuz unpacker.
- `scripts/npc/skyrim_voice.py`: per NPC its greeting lines (or `--scope own|all`), .xwm out of the .fuz, .wav
  (`--ffmpeg`), .wem (`--wwise`, the chain above) and .ffxanim (`--lips`), named `<Skyrim INFO FormID>_<n>` until
  the plugin step writes Starfield INFO records and renames them. The lip compile goes into
  `Data\Sound\Voice\S2SVoiceBuild.esm\NPCMBarrett|NPCFSarahMorgan` (UNITY compiled into its own plugin's folder of
  those names); whether the plugin folder name matters is unverified.
- Not yet: the Starfield records (voice type, greeting topics and responses), the first in-game check.
