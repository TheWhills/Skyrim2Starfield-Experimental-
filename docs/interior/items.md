# Loose items as real items (plan, 2026-11-10)

Owner: "in the inn all the wine is a static object but it needs to be an item with physics ... when you can run into
it, drop it, it moves". Today every placed Skyrim item (MiscItem, Ingestible, Weapon, Ammunition, Armor, books ...)
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
2. **Shape:** box first (bottles, plates and books are fine as boxes); convex hulls later (S6's next step, also for
   statics).
3. **Records:** an item converter like item_convert (armour) for MISC / ALCH / BOOK / WEAP / AMMO / KEYM: Starfield
   record copied from a vanilla item of the same kind (a vanilla drink for wine and mead), Skyrim name (string
   tables), value, weight, keywords, the converted world model. Gold -> credits (a rate to choose).
4. **Placement:** the interior / exterior builders place a REFR of the item base instead of a static (ownership
   carried over, "don't havok settle" flags kept so items do not jump at load).
5. **Effects: Starfield's own.** Owner 2026-11-10: food and drink work like any Starfield aid / food item. So each
   Skyrim ALCH / INGR is matched to a vanilla Starfield item of the same kind (wine -> a vanilla wine / alcohol,
   mead / ale -> a vanilla beer, bread / cheese / meat / vegetables -> vanilla foods of that kind, healing / stamina /
   magicka potions -> Starfield aid items by strength) and copied from it WITH its effects (heal over time, buffs,
   alcohol), keeping only the Skyrim name, model, value and weight. A table Skyrim item -> vanilla template, built
   from keywords and names, editable by hand; unmatched items get the plainest vanilla food / drink of their kind.
6. **Containers (later):** barrels, chests, sacks as CONT with their Skyrim inventory lists (LVLI -> leveled lists).
7. **In game:** the Sleeping Giant Inn: knock the wine bottles over, pick one up (the steal warning), drop it, drink it.

Weapons and armour already have converters (weapon_test_pack, item_convert); placed copies of them use the same
placement step.
