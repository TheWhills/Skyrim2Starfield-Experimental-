# Magic and casting (started 2026-11-09)

Owner (2026-11-09): magic and casting are part of the conversion. What is known so far:
- docs/armor/animation-port.md: Starfield's melee graph has CastSelf / CastTarget animation slots (events
  CastSelfStart / CastTargetStart) and Starborn powers cast with one gesture; full Skyrim magic (a spell per hand,
  charge / release, concentration, dual cast, wards) likely needs SFSE; supported idea: spells as hand "weapons".
- Record layouts (xEdit wbDefinitionsTES5 / wbDefinitionsSF1, read 2026-11-09; supported): both games keep SPEL
  (type, cast type, delivery) and MGEF (archetype, projectile, cast type, delivery). Starfield's archetype list keeps
  Skyrim's at the same numbers (Value Modifier, Calm, Frenzy, Invisibility, Light, Bound Weapon, Summon Creature,
  Telekinesis, Paralysis, Reanimate, Cloak, Slow Time, Spawn Hazard, Banish, ...) and replaces Werewolf / Vampire Lord /
  Grab Actor with its own (Damage, Immunity, Boostpack, Antigravity, Gravity Wielder, ...). Its MGEF DATA is laid out
  differently (archetype at 80, cast / delivery as bytes at 100 / 101), its projectiles add Plasma and Emitter.

scripts/magic/magic_survey.py (read-only) counts Skyrim's castable spells by school, archetype, cast type, delivery,
hand and projectile type, does the same for Starfield's, and per Skyrim archetype / way of casting says whether
Starfield has it and uses it: what can be carried over as data (effects, projectiles) and what needs new behaviour
(hand casting, concentration, charging). Its range checks test the layouts on the real files.

Next, once the survey is in: one Skyrim spell end to end (Flames or Firebolt) as the first test, by the cheapest
route the survey supports (a power with the Skyrim effect / projectile, then hand casting through the cast slots).

On hold (owner, 2026-11-09): spells as hand-equipped weapons (own weapon-type moveset, Skyrim casting clips, hand
flames from the fire conversion, magicka / both hands / dual cast in S2SCombat) is the preferred route over Starborn
powers, but the first spell test waits until the effects are known: the fire survey (Skyrim flame cards, particles)
and the magic survey (queue steps 3c / 3d) come first. Open then: a melee or a gun weapon as the spell's template.
