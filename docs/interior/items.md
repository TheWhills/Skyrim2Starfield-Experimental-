# Loose items as real items (plan, 2026-11-10)

Owner: "in the inn all the wine is a static object but it needs to be an item with physics ... when you can run into
it, drop it, it moves". Then: "we'd get them to work the same way as any aid / food item in Starfield ... items that you can
pick up, drop, have physics / gravity": Starfield's own item behaviour, which comes with an item record (Take, the
inventory, Drop) and a world model whose body is dynamic (gravity, knocked over, thrown). Today every placed Skyrim item (MiscItem, Ingestible, Weapon, Ammunition, Armor, books ...)
goes through the static converter (src/fo4sf/exterior.py CONVERT_TYPES: "they become plain statics here, visuals
only"): the model with a fixed box collision, no item record. Status words as in docs/npc/races-roadmap.md.

## What a Skyrim item needs to become in Starfield
| Part | Skyrim | Starfield |
|---|---|---|
| Base record | MISC (clutter, gems, ingots), ALCH (food, drink: the inn's wine and mead), INGR (ingredients), BOOK, WEAP, AMMO, ARMO, KEYM, SLGM | MISC, ALCH (food / drink / aid), BOOK (notes, slates), WEAP, AMMO, ARMO, KEYM; INGR and soul gems have no direct twin (MISC or ALCH with keywords) |
| World model | its NIF with a dynamic rigid body (bhkRigidBody: mass, motion system, convex / box shape) | NIF + bhkNPCollisionObject whose body is DYNAMIC (motion type, mass properties) |
| Inventory data | name, value, weight, keywords, pickup / drop sounds | the same fields (FULL, DATA value / weight, KWDA, pickup / putdown sounds) |
| Effects | ALCH / INGR magic effects (restore health, fortify ...) | those of the matching vanilla Starfield food / drink / aid item |
| Placement | REFR of the item, often owned (XOWN: the innkeeper's wine) | REFR of the item, ownership kept so taking it is stealing |

## Steps
1. **research - dynamic physics (the hard part).** S6 found converted props are fixed scenery: our box collision
   comes from a vanilla STATIC template. Making a body dynamic is a known pattern here: sfcollision.keyframed turns a
   static box into a keyframed one by copying the motion type (offset 240), filter / flags, body ids and the
   compressed mass properties (1064-1095) from a donor of the same 6,168-byte box layout. The same with a donor that
   is a DYNAMIC vanilla item (a box-shaped misc item) should give a box that falls, tips and can be pushed. To find
   donors: a probe over vanilla MISC / ALCH / BOOK world models (their physics blobs: shape type, size, motion type
   word, mass words) - read on the owner's PC like every template. Mass per item: from Skyrim's own bhkRigidBody
   (each clutter NIF carries its mass) or from size x a density.
   **built (2026-11-10):** scripts/interior/item_physics_probe.py (read-only): every vanilla MISC / ALCH / BOOK / AMMO /
   KEYM world model's bodies (tagfile size, Havok shape classes), and for the 6,168-byte box layout the
   KEYFRAMED_FIELDS words, box size and mass words, grouped by the motion word at 240 and labelled against the static
   template's and the door donor's -> candidate dynamic donors.
2. **Shape:** box first (bottles, plates and books are fine as boxes); convex hulls later (S6's next step, also for
   statics).
3. **Records:** an item converter like item_convert (armour) for MISC / ALCH / BOOK / WEAP / AMMO / KEYM: Starfield
   record copied from a vanilla item of the same kind (a vanilla drink for wine and mead), Skyrim name (string
   tables), value, weight, keywords, the converted world model. Gold -> credits (a rate to choose).
4. **Placement:** the interior / exterior builders place a REFR of the item base instead of a static (ownership
   carried over, "don't havok settle" flags kept so items do not jump at load).
5. **Effects: Starfield's own** (proposal; the owner's "work the same way as any aid / food item in Starfield" meant
   picking up, dropping and physics, steps 1-4). Each
   Skyrim ALCH / INGR is matched to a vanilla Starfield item of the same kind (wine -> a vanilla wine / alcohol,
   mead / ale -> a vanilla beer, bread / cheese / meat / vegetables -> vanilla foods of that kind, healing / stamina /
   magicka potions -> Starfield aid items by strength) and copied from it WITH its effects (heal over time, buffs,
   alcohol), keeping only the Skyrim name, model, value and weight. A table Skyrim item -> vanilla template, built
   from keywords and names, editable by hand; unmatched items get the plainest vanilla food / drink of their kind.
6. **Containers (later):** barrels, chests, sacks as CONT with their Skyrim inventory lists (LVLI -> leveled lists).
7. **In game:** the Sleeping Giant Inn: knock the wine bottles over, pick one up (the steal warning), drop it, drink it.

Weapons and armour already have converters (weapon_test_pack, item_convert); placed copies of them use the same
placement step.

## Probe results (owner's run, 2026-11-20)
item_physics_probe (verified): 1290 models of 344 ALCH / 1319 MISC / 992 BOOK / 132 AMMO / 242 KEYM; shapes mostly
hknpConvexShape (2967), hknpBoxShape 682, compound 324; tagfiles most often 7088 / 7376 bytes. The box-layout
comparison found only 10 bodies, all static cargo crates (motion word as the static template): loose items are
convex, so the dynamic fields have to be read from convex bodies. item_body_dump.py decodes a few vanilla drinks /
foods / misc items' bodies in full with hktagfile (every field by the file's own type table) next to the static
template; our own convex writer (meshcollision) writes static bodies ("no mass properties").
item_body_dump first run (owner, 2026-11-20): every body decoded to {} - Starfield's NIF physics tagfiles have no
hkRootLevelContainer, item 1 is the hknpPhysicsSystemData itself (checked here on a fan blade, the dartboard and the
trilobite ragdoll; fixed). Seen meanwhile (verified on those three): a ragdoll body is motionType 2 with a mass, a
hknpRefMassDistribution and a motionPropertiesId into the system's motionProperties (gravity, damping, deactivation);
the fan blade is motionType 0, mass 0, no motion properties, but each convex piece carries hknpShapeMassProperties
(mass, volume, compressed inertia) where our convex writer puts none. Loose items next (summary lines per body).

### Loose item bodies, decoded (owner's item_body_dump run, 2026-11-20, verified)
Six vanilla loose items (Digipick, Credits, onion, pear, two beer packs) against the static template (an oil
portrait). Every loose item is one body, convex (onion, pear, digipick: hknpConvexShape) or box (credits, beer packs:
hknpBoxShape), and differs from the static one only in:

| field | loose item | static |
|---|---|---|
| body motionType | 2 (dynamic) | 0 |
| body mass | 1 (digipick), 2 (credits), 5 (food, drink) | 0 |
| body flags | 138 | 0 |
| body collisionFilterInfo | 4 | 1 |
| body motionPropertiesId | 0 | 65535 |
| body massDistribution | hknpRefMassDistribution (centre of mass + volume, inertia axes quaternion, inertia diagonal) | none |
| system motionProperties | one entry: gravity 1, linear damping 0.1, angular 0.05, max speeds 100 / 200, deactivation and cast settings | none |

The same in all six: one hknpMaterial (friction 1.75, restitution 1.45-1.70), qualityId 255, the shape carrying an
hknpShapeMassProperties property (mass = volume x 1000, compressed centre / inertia) - the static template has one
too; our convex writer (meshcollision._emit_convex) writes none. The body's mass is a round number per kind, not the
shape's volume mass. So a dynamic body = our convex shape with the shape mass property, plus the body / system fields
above copied from a vanilla loose item, the mass distribution computed from the hull.

## Wine bottle test (2026-11-20, owner: "lets get the wine bottle test going")
scripts/interior/item_test.py, the smallest end-to-end form of steps 1-3 before any builder places items: a Skyrim
ALCH (default the first wine with a bottle model; --item) becomes S2SItemTest.esm's ALCH copied from a vanilla
Starfield drink (--donor; default the first ALCH whose EditorID / model reads wine, then whiskey / liquor / bottle,
that has a physics body): its effects, sounds, keywords, value and weight, with the Skyrim name and our model. The
model is converted as the statics are (SkyrimConverter, no collision of ours) and gets the DONOR's physics body
(item_test.with_physics: bhkNPCollisionObject + bhkPhysicsSystem on the root, the donor's collision flags and
BSXFlags): dynamic as the donor's (motionType 2, mass, mass distribution, motion properties), but the donor bottle's
hull, not ours. Unverified: that a body copied from another model falls, settles and can be taken in game; that the
donor's hull sits right on our bottle (origin at the base in both: supported for clutter). Next after it works: our
own dynamic convex body (the fields in the table above on meshcollision's hull, mass distribution from the hull).
**Verified in game** (owner, 2026-11-21 08:53): S2S_FoodWineAlto ("Alto Wine", the Skyrim bottle, donor
Drink_Alc_Bottle_Generic_SpaceWine's body and record) placed with placeatme: about the right size, physics (falls,
can be knocked over), picked up as "Alto Wine", drunk; the donor's effects and value (+10% persuasion, -15% O2
recovery, 265). So a Skyrim model with a vanilla dynamic body copied onto it works as a loose item. The item card
showed "Oõ▮" as its description (the donor's DESC string id read as text): DESC now empty. Note: MO2's Mod Index was
19, the game's 1B (official plugins the game loads that MO2 shows unticked); use help's FormID.

## Placed items (2026-11-21, owner: "yes" to making Riverwood's tables and shelves real items first)
scripts/interior/make_items.py (after the batch's convert, before PluginSpike; tools\owner\riverwood_doors.ps1
-Items) and PluginSpike ITEMS: the wine test's recipe (verified) for every Skyrim ALCH / INGR reference in the batch's
cells. MiscItem clutter (plates, tankards, baskets) stays static for now.
- **Kind** (Skyrim ENIT flags + words): drink (food flag and a bottle / jug / wine / mead / ale word), food (other
  food, every INGR), potion (not food: potions, poisons). Starfield donors the same way (food flag + drink words;
  medicine flag or med / aid / chem words; EditorIDs with test / notplayable / template left out).
- **Donor:** of the same kind (any ALCH when the kind has none), the closest size: |log ratio| of the heights plus
  of the sorted flat sides, our converted model's bounds against the donor's OBND (read as 6 floats, metres; a
  donor with any other OBND layout ranks last: supported, Mutagen's Starfield ObjectBounds is P3Float and our
  furniture OBND in metres verified in game). Unscripted (no VMAD) before scripted. The first of the best 12 whose
  NIF has a body wins. The copy keeps the donor's effects, sounds, keywords, value and weight (step 5: Starfield's
  own); Skyrim's value / weight are in items.json for later.
- **Model:** <static>_item.nif next to the static in convert\meshes (packed with it): the static's own fixed box
  body is overwritten in place by the donor's dynamic one (item_test.with_physics; appending it, as for the wine
  test's collision-less model, left the static box first: found by test_make_items). The donor's hull is the
  donor's shape, so our geometry is moved (every child of the root) to put its flat centre and its bottom on the
  donor's bounds; the reference is shifted back by origin_offset_m, so the item stands where Skyrim put it. A
  Skyrim item whose origin is its centre (unresolved which ones) would otherwise sink half into the table.
- **References:** Skyrim's position / rotation / scale, Initially Disabled, and Don't Havok Settle (REFR flag
  0x20000000 in Skyrim; written as the same bit, unresolved whether Starfield's REFR reads it the same). XOWN is
  recorded, not written (no ownership yet: taking is not stealing).
**First run** (owner, 2026-11-21 09:11, riverwood_doors.ps1 -Items): the C# compiled (verified); 297 placed items from
53 Skyrim bases in the six Riverwood interiors became ALCH copies (inn 29, Riverwood Trader 113, ...); FoodRabbit /
FoodPheasant skipped (models not converted). The Skyrim kinds came out right, the Starfield ones did not: 343 ALCH with a
model split drink 269 / food 8 / potion 66 (drink words matched model paths; flags / words made ShipRepairKit and
LegendaryCatalyst "potions"), so the wine copied Food_Pack_Oishii_Seaweed_Combo and a cereal box, every cabbage /
cheese wheel / leek Food_Generic_CerealBox. Fixed: the donor's kind is its EditorID prefix (Drink_, Food_, Aid_ / Med_
/ Chem_), and its size is the union of its BSGeometry boxes (centre + half extents, node transforms applied) instead
of OBND (its units then unconfirmed; the second run showed them equal); OBND only when the NIF has no box. Donors without a physics body are dropped before ranking.
**Second run** (owner, 09:17): donors drink 82 / food 148 / potion 53, all with a body, all sized from geometry; the
geometry sizes equal the OBND ones (verified: Food_Generic_CerealBox 0.136 x 0.136 x 0.195 both ways), so OBND was in
metres after all (the first run's odd picks came from the kind pools, not the units). Matches mostly by kind and size
(mead -> Erdebrau cans, salmon steak -> naan bread, potions -> Aid_MedPack), but no Starfield drink is as tall as
Skyrim's 0.4 m wine bottles, so all wine copied a TerraBrew to-go cup (coffee effects, a short cup body), and raw
vegetables copied packaged meals (box bodies). Now a Skyrim drink with an alcohol word prefers Drink_Alc_ donors and
raw produce (not baked / grilled / cooked) Food_Produce_ ones, when any exist; size decides within them.
Unverified: everything in game; the C# (written without a compiler: NuGet is blocked here; API names checked against
Mutagen's Starfield Ingestible.xml: Name, Description, Model, ObjectBounds, mod.Ingestibles). Next: own hulls (the
donor's shape is wrong for odd sizes: `fit` in items.json shows how far), ownership, Skyrim's effects / value / weight.

