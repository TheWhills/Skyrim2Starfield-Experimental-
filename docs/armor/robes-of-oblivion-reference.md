# Reference: a community-made worn outfit that works in Starfield (Robes of Oblivion)

Read 2026-10-14 from "Robes of Oblivion" (Nexus Starfield mod 12121, v1.5, by the Starblivion team), which the owner
downloaded. Nothing from the mod is in Git; this records its structure only. Labels: **verified** = read from the
files here (read-only, with this repo's ba2 / nif / sfmesh readers); **supported** = the mod is published and used,
so its layout renders in game (not tested in game by us).

## Files (verified)
* `Robes_of_Oblivion.esm` (master: Starfield.esm only; TES4 flags 0x101), `- Main.ba2` (9 NIFs), `- Textures.ba2`
  (5 `.mat` + 10 DDS: diffuse + normal per robe; the DDS names are Oblivion's, e.g. `robemagearch.dds`).
* **No `geometries/` folder: the mesh data is embedded in the NIF.** The BSGeometry's NiAVObject flags are `0x20E`
  (bit 0x200 set; this repo writes `0xE` with external `.mesh` files), and after each LOD's `(index count, vertex
  count, flags 0x40)` the bytes are a complete `.mesh` stream that `sfmesh.parse` reads unchanged (version 2).
  `sfnif.parse_bsgeometry` does not support this yet (it misreads it as a path and raises).
* Only 3 distinct meshes: two robe bodies (13,366 / 13,515 vertices) and one hood (813 vertices); the 9 NIFs are
  retextures. Hand-made, not converted (the author: "custom models that are recreated").

## Worn NIF layout (verified): 8 blocks
`NiNode` (root) -> `BSGeometry` (skin -> `BSSkin::Instance`, shader -> `BSLightingShaderProperty`) +
`BSXFlags` + `NiIntegerExtraData` ("MaterialID") + `SkinAttach` + `BSSkin::Instance` + `BSSkin::BoneData`.
NIF BS version 172, user version 12 (this repo's static NIFs use the same header).
* **SkinAttach**: the bone NAMES the mesh binds to. Robe: 50 bones; hood: 9.
* **BSSkin::BoneData**: per bone 68 bytes = 17 floats (bounding sphere 4, 3 x 3 rotation 9, translation 3, scale 1).
  The rotation rows have length ~1.22, not 1 (bone 0: rows 1.224 / 1.215 / 1.225, scale field 1.0): unresolved
  whether vanilla binds do the same; compare with a vanilla outfit before writing our own.
* **BSSkin::Instance** begins `(0, 7, 50, -1)`: plausibly (skeleton root ref, bone data block 7, bone count, ...);
  supported hypothesis, to check against a vanilla outfit.
* **Mesh**: 8 bone weights per vertex (`weights_per_vertex = 8`, (bone index, u16 weight) pairs), UVs, normals,
  tangents and vertex colours on every vertex; no extra LODs; no `morph.dat` (the robes do not follow body sliders).
* Leftover strings show the starting point was a vanilla NIF: `Outfit_UCPolice_Helmet_Back_M:0` and
  `Materials\Clothes\Outfit_UCPolice\Outfit_UCPolice_Helmet_01.mat` (a UC police outfit).

### The Starfield bones a robe uses (verified: SkinAttach of the robe; the hood uses the 9 marked *)
`C_Hips C_Spine C_Spine1 C_Spine2* C_Chest* C_Neck_Twist* C_Neck1* C_Head*`;
per side (`L_` / `R_`): `Clavicle* Deltoid* Biceps Biceps_Twist1 Elbow Forearm Wrist_Twist Wrist_Twist1 Wrist_Twist2
Wrist Thumb Cup Butt Thigh Thigh_Twist Thigh_Twist1 Knee Calf CalfMass Foot Toe`.
These are the target names for a Skyrim -> Starfield bone map (Skyrim: `NPC Spine2 [Spn2]`, `NPC L UpperArm
[LUar]`, ...). Fingers are absent (Cup / Thumb only): sleeves stop at the wrist.

## Records (verified): copies of vanilla nightwear
* 15 ARMO + 15 ARMA + 1 KYWD. One robe ARMO is literally `Clothes_Nightwear_01COPY0000`: every record is a copy of
  vanilla `Clothes_Nightwear_01` with the model paths changed.
* **ARMA**: `MOD2` (male) and `MOD3` (female) point at the SAME NIF (one mesh for both bodies); `MOD4` / `MOD5`
  (first person) keep vanilla `Outfit_Nightwear_UpperBody_01_M_1st.nif` / `_F_1st.nif`; `RNAM` 0x0000347D (the
  vanilla race every ARMA here names); further subrecords copied unchanged (BFCB, BO64, DNAM, NAM4, NAM6, MODL x2,
  MNAM, TNAM, SNAM, VNAM, BSMP x2).
* **ARMO**: ground / world models are vanilla (`SetDressing\OutfitContainer01.nif` for robes,
  `Clothes\outfit_ucnavy\Outfit_UCNavy_Hat_GO.nif` for hoods): no converted ground models.

## What it means for the Skyrim armor plan
* **Supported**: a hand-made skinned mesh, embedded in the NIF, bound by bone name to Starfield's skeleton, with
  records copied from a vanilla outfit, renders and animates in game. The Starfield end of wearable armor works.
* **Simplest viable target for a converter**: same NIF layout, one mesh for both bodies, first-person and ground
  models borrowed from vanilla, records copied from a vanilla outfit, no body morphs (clips on unusual body shapes,
  as these robes presumably do). Morphs, per-body meshes and real ground models are later refinements.
* **Needed in this repo**: write the skinned variant (SkinAttach + BSSkin::Instance + BSSkin::BoneData + weights in
  the `.mesh`), and read embedded meshes in `sfnif.parse_bsgeometry`. Confirm the bind layout and the 1.22 row length
  against one vanilla outfit NIF from the owner's Starfield archives before trusting either reading above.
