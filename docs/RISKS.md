# Risks and spikes

A spike is a short, time-boxed experiment with a **go / no-go / fallback** outcome. Do them in the order
below (cheapest and most blocking first). Record each result in `docs/spikes/Sx-*.md` and `docs/JOURNAL.md`.

Legend: **Impact** = what breaks if it fails; **Fallback** = what we do instead.

| # | Question | Impact | Fallback |
|---|---|---|---|
| S1 | Can a script write a Starfield mesh (NIF BS 173/175 + external `.mesh`) that the game renders? **GO, confirmed in game** (a converted chair renders correctly in Starfield 1.16.244; [result](spikes/S1-mesh-writer.md)) | Blocks everything visual | Use the closed-source Starfield Blender extension per asset (manual), or NifSkope's own writer |
| S2 | Can Mutagen's alpha Starfield library write a plugin the game loads? **GO, confirmed in game** (Mutagen-written plugin with form version 576 loads and the record spawns; [result](spikes/S2-S4-S9-plugin-units-loading.md)) | Blocks all records | xEdit (`xSFEdit`) scripts, or raw record writer |
| S3 | Can loose `.mat` (JSON) + converted textures be loaded without the compiled material DB? **GO, confirmed in game** ([result](spikes/S3-materials.md)) | Blocks materials | Re-point to existing vanilla `.mat` files (T1 look) |
| S4 | What are Starfield's unit scale and axis convention vs Fallout 4? **GO: ~70 units per metre, confirmed in game** (chair looks natural-size; orientation and winding are correct) | Silently wrong sizes everywhere | Calibrate from matching vanilla objects (doors, chairs) |
| S5 | How are custom exterior worldspaces + terrain created and stored? | Blocks P4 | Bake terrain as static mesh tiles with a landscape material |
| S6 | How is `bhkNPCollisionObject` / hknp collision generated from a mesh? **Axis-aligned box: GO, confirmed in game** ([result](spikes/S6-collision.md)); convex/compound/mesh shapes still open | Blocks walkable interiors | Box/convex-hull approximations via templates, CoACD for decomposition |
| S7 | What is Starfield's skeleton + animation authoring path, and can FO4 rigs/animations map across? | Blocks P3 | Rebuild actors on Starfield's human skeleton; use Starfield animations |
| S8 | Can interior navmesh be generated from CK for converted geometry, and can it be scripted? | Blocks AI/walking | Manual CK navmesh per cell, then automate later |
| S9 | How does Starfield load loose files and a non-Creations plugin (`StarfieldCustom.ini`, `plugins.txt`, SFSE)? **GO, confirmed**: plugin + `- Main.ba2` + Plugins.txt, no ini needed; the game loads it | Blocks testing | Follow a known-good tutorial mod setup first |

## Known facts that shape the spikes (measured here, or from public sources)

- **Meshes:** Starfield NIFs are BS version 175 and hold `BSGeometry` blocks that point at external
  `geometries\<hash>\<hash>.mesh` files; FO4 NIFs are BS version 130 with inline `BSTriShape`. Mesh
  *reading* is open source: see `src/io/MeshFile.cpp`, `lib/meshlet.cpp` and `build/nif.xml` in the
  [fo76utils/nifskope](https://github.com/fo76utils/nifskope) fork. A mesh *writer* was not found, so S1 is
  the keystone: it comes from that format spec plus a round trip.
- **Materials:** Starfield `.mat` files are JSON. The game's vanilla materials ship compiled in a single
  `materialsbeta.cdb`; the Creation Kit can read loose `.mat` via `bUseCompiledDB=0` in
  `CreationKitCustom.ini` and the `materials` folder from `Starfield/Tools/ContentResources.zip`.
- **Terrain:** Starfield's CK builds *mini-worldspaces* stitched into procedurally generated planet terrain;
  there are no `LAND` records at all in `Starfield.esm` (Fallout 4 has 37,020).
  [CK guides](https://steamcommunity.com/sharedfiles/filedetails/?l=english&id=3404834557) say "New worldspace"
  is greyed out because a worldspace needs terrain. S5 finds out exactly how that works.
- **Plugins:** Mutagen has `Mutagen.Bethesda.Fallout4` and `Mutagen.Bethesda.Starfield`; the Starfield package
  is still `0.55.0-alpha.*` on NuGet.
- **Collision:** Fallout 4 uses Havok 2014.1 packfiles; Starfield uses Havok tagfiles with `hknp` shapes.
  Related open source: [fo76utils/CoACD](https://github.com/fo76utils/CoACD) (convex decomposition) and the
  NifSkope "Havok" spells.
- **Audio/voice:** Fallout 4 `.fuz` (xWMA + lip) vs Starfield Wwise `.wem` + FaceFX `.ffxanim`.

## Spike definitions

### S1: write a Starfield mesh from a script
1. Pick one trivial FO4 static (a patio chair).
2. Parse it (nifly via PyNifly's library, or our own `BSTriShape` parser).
3. Write `Starfield-style .nif` (BS 173, `BSGeometry`) and the `.mesh` it references, generating meshlets
   as NifSkope's `spGenerateMeshlets` does.
4. **Oracle:** (a) our reader round-trips it; (b) fo76utils NifSkope displays it with the right shape;
   (c) a STAT referencing it renders in the Starfield CK; (d) it appears in-game.
5. **Go** if (c) passes. **Fallback** if the writer proves too hard: use the Starfield Blender extension's
   exporter driven headless through Blender's Python (`blender --background --python`).

### S2: write a Starfield plugin from FO4 data
1. In a .NET 9 console app, read `Fallout4.esm` with `Mutagen.Bethesda.Fallout4`.
2. Write a Starfield `.esm` with one `STAT` and one `MISC` using `Mutagen.Bethesda.Starfield`.
3. **Oracle:** xSFEdit opens it with no errors; CK loads it; the game loads it and the console `help` finds
   the EditorID.
4. Also measure how much of each record type the Starfield library models (the alpha may be incomplete).

### S3: materials without the compiled database
1. Take one FO4 `.bgsm` and its textures.
2. Convert textures (BC re-encode, channel mapping: FO4 `_d` colour, `_n` normal, `_s` spec/gloss → Starfield
   colour / normal / roughness / metal).
3. Emit a `.mat` JSON modelled on a vanilla one.
4. **Oracle:** the S1 chair renders with the new material in the CK and in-game.

### S4: units and axes
Compare matching vanilla objects (door height, chair seat height, stair rise, character height) and fit one
scale + axis mapping. Verify with the S1 chair placed next to a vanilla chair.

### S5: terrain
Document how a Starfield worldspace gets terrain: which files hold heightmaps (the `.btd` terrain files, 2,112
of them in `Starfield - Terrain*.ba2`), how mini-worldspaces are authored, whether a *non-planet* worldspace
(a flat standalone map) can be created, and whether CK terrain can be driven by script.
**Fallback:** bake FO4 `LAND` heights + textures to static mesh tiles (no CK terrain), losing sculpting but
keeping the world.

### S6: collision
Find the smallest hknp tagfile that makes a box collide. Then generate boxes/convex hulls from FO4 collision
or from mesh bounds, and try [CoACD](https://github.com/fo76utils/CoACD) for decomposition.
**Oracle:** the player is blocked in-game by the S1 chair.

### S7: skeleton and animation
Inventory Starfield's human skeleton (`.rig`), animation containers (`.af`/`.afx`/`.agx`, plus `.ffxanim`
face animation) and the CK's animation import path (Havok content tools may be required: record exactly
what and where to get it). Then compare with Fallout 4's skeleton bone names to produce
`mappings/bones_fo4_to_sf.json`. **Fallback:** all actors use Starfield's rig and animations; only meshes
and outfits are converted.

### S8: navmesh
Try CK's navmesh generation on the converted S2/S6 interior; check whether it can be triggered by script.
**Fallback:** manual per cell at first.

### S9: loading and testing
Follow a known-good Starfield custom plugin tutorial end to end (loose files, `plugins.txt`, SFSE) so every
later oracle has a reliable harness. Record the exact INI keys.
