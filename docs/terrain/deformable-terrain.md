# Deformable terrain (footprints, trenches, craters): plan note (2026-11-09)

Owner: eventually something like NMN's Dynamic Terrain Deformation (Skyrim, Nexus SE 192402, the author's original;
a Fallout 4 port exists, Nexus FO4 110136) for Starfield. Read for design only (both downloads and the Skyrim source,
GPL-3.0-only, about 10,600 lines of C++ plus embedded HLSL); nothing run.

How it works (verified from the source and the DLL strings):
* A D3D11 hook (MinHook): landscape draws are routed through hull / domain (tessellation) stages it generates
  against the game's own vertex shader signature, and their vertices displaced from a GPU height field (a clipmap,
  2 levels) that compute shaders update every frame.
* What writes into the field: actors' feet and bodies (collision shapes, range set by ActorStampDistance), objects
  resting on the ground, arrows, magic / shout / explosion impacts, heat sources melting snow (keywords fire, torch,
  forge ...), weather refilling and firming it over game hours; snow is raised and trenched, other surfaces pressed.
* Per landscape texture a surface profile (Surfaces.ini, one folder per mod, patches last): depth, radius, rim,
  decay, clearance, type (snow, ash, sand, mud ...), keyed by texture file name.
* The Fallout 4 port (source too, owner upload 2026-11-09: CommonLibF4, still D3D11, about 19,100 lines, GPL-3.0-only)
  adds what a deferred renderer needs: it hooks the world's G-buffer pass (DrawWorld::DeferredPrePass), keeps near
  terrain out of the depth pre-pass so displaced depth is not culled by flat depth, displaces the sun's shadow maps,
  pushes grass down with the ground, and adds ground decals, indoor prints, snow on objects and a winter look. Every
  engine address sits in one table (Offsets.h, per runtime, from a PDB-named Ghidra project) and engine layouts in
  GameLayouts.h, with in-game test scripts (tools/ingame). Fallout 4 and Starfield both draw terrain into a G-buffer,
  so this port is the template for a Starfield one: its renderer-side structure carries over, the D3D11 calls become
  D3D12 and the offsets / layouts are Starfield's.

For Starfield (supported plan, not started):
* Not convertible: it is renderer code tied to Skyrim's D3D11 renderer and engine offsets. Starfield is D3D12 with a
  different terrain shader and vertex layout, so it is a new SFSE plugin that ports the design (and, if code is
  reused, is GPL-3 itself; kept separate from S2SCombat for that reason).
* Our Skyrim ground is native Starfield terrain (BTD overlay, docs/terrain/skyrim-tamriel.md), so such a plugin
  would deform it the same way as vanilla planets.
* Data that carries over: the surface profiles, by the converted landscape textures' names (the converter keeps the
  Skyrim LTEX names), so Skyrim profiles and mod patches map across.
* First research step (owner's PC, later): a D3D12 frame capture (PIX or RenderDoc) of Starfield on the converted
  terrain: which draws are terrain, their shaders and vertex format, whether a hull / domain stage can be added
  there, and where the depth / shadow passes draw it.
