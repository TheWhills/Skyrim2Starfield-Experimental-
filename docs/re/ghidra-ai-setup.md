# Ghidra + AI setup for the left-hand weapon work

Goal: find, in Starfield 1.16.244, (1) the engine's "copy a loaded model" function (the NiObject clone virtual) and
(2) what the game does after attaching a weapon model under the `Weapon` bone so that it is drawn. With those,
S2SCombat can copy any weapon as the game built it (object mods, glow included) and hang the copy on the left hand.
Background: docs/ai/decisions.md, 2026-10-26 / 27 entries (moving an existing node did nothing visible; the game draws
the weapon from its own copy of the transforms).

The AI does the search / decompile / follow-references / rename loop through an MCP server inside Ghidra (ReVa); you
install things once, run the first analysis, and test in game.

## 1. Install (once)

1. **Pick the versions from ReVa's release page** (github.com/cyberkaida/reverse-engineering-assistant/releases): each
   release names the Ghidra version it is built for; ReVa only loads in that exact Ghidra version. As of 2026-10-27
   Ghidra 12.2 is the newest (12.1.4 the last 12.1).
   - Ghidra 12.2 or later: Java (JDK) 25. Ghidra 12.0 / 12.1: JDK 21. Adoptium Temurin is fine.
2. **Ghidra**: download the matching zip from github.com/NationalSecurityAgency/ghidra/releases, unzip to e.g.
   `C:\Tools\ghidra_12.x`. Give it memory for a 100 MB+ executable: in `support\launch.properties` set
   `MAXMEM=16G` (or about half your RAM).
3. **ReVa extension**: in Ghidra, File > Install Extensions > `+` > the ReVa release zip; restart Ghidra.
   - Project window: File > Configure > Configure all plugins > tick **ReVa Application Plugin**.
   - Code Browser (open any program once): File > Configure > Configure all plugins > tick **ReVa Plugin**, then
     File > Save Tool.
4. **Claude Code** on the PC (if not already): see docs.claude.com for the installer. Then register ReVa (Ghidra open,
   a project loaded; ReVa listens on localhost:8080):

       claude mcp add --scope user --transport http ReVa -- http://localhost:8080/mcp/message

   In Claude Code, `/mcp` should list ReVa as connected. Optional: `/permissions` -> allow `mcp__ReVa` so it does not
   ask before every tool call. Optional skills: `claude plugin marketplace add cyberkaida/reverse-engineering-assistant`.
   ReVa only listens on localhost by default; leave it that way (it can run scripts).

## 2. Load and analyse Starfield (once, takes hours)

1. Copy `D:\SteamLibrary\steamapps\common\Starfield\Starfield.exe` to a work folder (e.g.
   `C:\Modding\re\Starfield_1.16.244.exe`) and analyse the copy, never the live file.
2. Ghidra: File > New Project (non-shared) `C:\Modding\re\starfield`, then File > Import File > the copy (format PE,
   language x86:LE:64 default). Open it in the Code Browser; say **Yes** to analyse.
3. Analysis options: keep the defaults, and make sure **Windows x86 PE RTTI Analyzer** and **Demangler Microsoft** are
   on (they give class names like `NiObject`, `NiNode`, `NiAVObject` and their vtables). Turn **off** "Decompiler
   Parameter ID" and "Aggressive Instruction Finder" (slow on a binary this size). Let it finish (the progress bar at
   the bottom right); save.
4. If the program looks almost empty after analysis (few functions, no `.?AV...` RTTI names), tell Claude; don't go
   further.

## 3. Names from the Address Library (optional, makes the search much faster)

S2SCombat and CommonLibSF name functions by Address Library ID. Send Claude (here) the file
`versionlib-1-16-244-0.bin` from the Address Library mod (MO2: its SFSE\Plugins folder); a Ghidra script that labels
every ID (and the CommonLibSF names it knows) will go into `scripts/re/`. Without it the RTTI names still work.

## 4. The first session (paste into Claude Code on the PC, in the repo folder, Ghidra open)

> We're working in Skyrim2Starfield-Experimental- (read docs/re/ghidra-ai-setup.md and the 2026-10-26/27 entries of
> docs/ai/decisions.md). Using ReVa on the open Starfield 1.16.244 program:
> 1. Find the vtables of NiObject, NiAVObject and NiNode from the RTTI. In Bethesda's earlier games NiObject has a
>    CreateClone virtual (takes an NiCloningProcess) and NiNode has AttachChild / DetachChild. Identify those slots in
>    Starfield by what the functions do (clone: allocates an object of the same class and copies its fields, recursing
>    into children; attach: adds to the children array {T* data, u16, u16} at +0x138 and sets the child's parent at
>    +0x38). Compare with the slots CommonLibSF declares in include/RE/N/NiAVObject.h and NiNode.h.
> 2. Find how a weapon model is attached when a weapon is equipped: start from strings "Weapon", "WEAPON",
>    "WeaponLeft", and from callers of the AttachChild you found, around ActorEquipManager / BipedAnim. Report what
>    is called after the attach (update / culling / render registration).
> 3. For every function you identify, give: address, vtable slot, Address Library ID if known, a one-line
>    description, and how sure you are. Rename them in Ghidra. Write the results to docs/re/findings.md.

What to send back here: `docs/re/findings.md` (commit it, or paste it).

## 5. What happens with the findings

S2SCombat gets a "send this weapon to the left hand" key: the drawn right weapon's 3D (as the game built it) is
cloned and attached under `WeaponLeft` / `L_Wrist` with the left grip; the copy is dropped on unequip, sheathe and
load and rebuilt on draw. The dual moveset switch stays as it is. Spells do not depend on any of this
(docs/ai/decisions.md 2026-10-27).
