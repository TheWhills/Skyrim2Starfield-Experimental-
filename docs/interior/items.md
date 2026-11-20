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
