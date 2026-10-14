# Setup

You need legitimate copies of **both** games. Nothing here downloads or distributes game files.

## Pinned versions

| Thing | Version | Notes |
|---|---|---|
| Fallout 4 | **1.10.163** (pre-Next-Gen, with matching F4SE 0.6.23) | The converter only *reads* it. It doesn't need to run, only the data (`Fallout4.esm`, DLC `.esm`, `Fallout4 - *.ba2`) must be available |
| Starfield | **1.16.244** (Steam) | Not the Microsoft Store / Game Pass build (SFSE doesn't support it) |
| SFSE | 0.2.21 | Matches Starfield 1.16.244 |
| Python | 3.12+ | `python -I` for anything that reads game data |
| .NET SDK | 9.x | For the Mutagen plugin translator |
| Blender | 5.x | Optional, for artist-in-the-loop steps |
| numpy (+ Pillow for previews) | any recent | Texture conversion and `scripts/render_preview.py`; `pip install numpy pillow` (a venv outside the repo is fine) |
| `texconv` | the copy in xEdit's `Edit Scripts` | BC1/BC4/BC5/BC7 compression |

## Tools

| Tool | Get it from | Used for |
|---|---|---|
| Starfield Creation Kit | Steam, app **2722710** | The official editor; also an oracle (L2) |
| [NifSkope (fo76utils fork)](https://github.com/fo76utils/nifskope/releases) | GitHub release | Open/inspect FO4 and Starfield NIFs, `.mesh`, `.mat` (oracle L1) |
| [xEdit](https://github.com/TES5Edit/TES5Edit/releases) (`xSFEdit.exe`, `xFOEdit.exe`) | GitHub release | Inspect plugins, scripts |
| [SFSE](https://www.nexusmods.com/starfield/mods/106) | Nexus (login) | Native plugins, console |
| [PyNifly](https://github.com/BadDogSkyrim/PyNifly/releases) | GitHub release | Fallout 4 NIF import/export in Blender |
| [Starfield Blender Extension](https://www.nexusmods.com/starfield/mods/16979) | Nexus (login) | Starfield NIF/mesh/material/collision in Blender |
| [Mutagen](https://github.com/Mutagen-Modding/Mutagen) | NuGet | Plugin read/write |
| [CoACD](https://github.com/fo76utils/CoACD) | GitHub | Convex decomposition for collision |

Download each archive into **its own empty folder** (outside this repo), and don't run scripts from inside
those folders.

## Configuration

Copy `config.example.toml` to `config.toml` (git-ignored) and fill in your paths. `work_dir` and
`staging_dir` must be outside the repository.

## Extracting Fallout 4 data

If your Fallout 4 `Data` folder is mixed with mods, point `fo4.data_dirs` at a **clean copy** of the
vanilla files instead (the base game plus DLC you own). Mod plugins in the same folder are ignored but
slow scans.

## Safety

- Test in a **throwaway Starfield profile/save**. Don't test on your main save.
- Don't point any tool at a game's online services; everything here is offline/single-player.
- Run `python scripts/guard.py` before every commit.
