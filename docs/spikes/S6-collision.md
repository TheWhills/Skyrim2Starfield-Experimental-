# S6: collision (2026-10-07)

**Result: GO for axis-aligned box collision, confirmed in game.** A converted prop now has physics in Starfield 1.16.244: two
copies spawned on top of each other pushed each other apart and tipped over, and the player's movement shoved them.
Screenshot: [media/fo4-chairs-colliding-in-starfield.png](../media/fo4-chairs-colliding-in-starfield.png).
Code: `src/fo4sf/sfcollision.py`, `sfnif.build_static_nif(collision_blob=...)`, `convert_static(collision_template=...)`,
oracle `scripts/oracles/collision_regression.py`. Fidelity tier T3 (one box per asset).

## How Starfield stores collision

Three pieces in the NIF (verified on `meshes/setdressing/historicaloilportraits/*.nif` and 427 other box props):
1. the **root `NiNode`** has `Collision Object` pointing at a `bhkNPCollisionObject`;
2. `bhkNPCollisionObject` (14 bytes): `target = 0` (the root), `flags = 0x0080`, `data = <bhkPhysicsSystem block>`, `body id = 0`;
3. `bhkPhysicsSystem` = `u32 size` + a **Havok tagfile** (`00 00 18 18 'TAG0'` ...). `BSXFlags` is `2` when collision exists.

Block order in vanilla (and ours): `NiNode, BSXFlags, bhkNPCollisionObject, bhkPhysicsSystem, BSGeometry, NiIntegerExtraData,
BSLightingShaderProperty`.

Survey of 2,500 vanilla `setdressing` NIFs by Havok shape type: 596 single `hknpConvexShape`, 411 `hknpCompressedMeshShape`,
232 `hknpBoxShape`, 183 convex+compound, plus mixes. The smallest tagfile is about 5.7 KB (mostly type descriptions).

## What we do: patch a vanilla box blob

Writing Havok tagfiles from scratch is out of reach for now, so `box_blob` takes a vanilla plain-box blob (6,168 bytes, identity
rotation, read **at run time from the user's own archive**, never committed) and overwrites the floats that depend on the box.
Regressing 369 identity-rotation box blobs against the box's centre `c` and half-extents `h` (recovered from the 8 corners at
offset 592) found **36 words that fit exactly**:

| offsets | meaning | value |
|---|---|---|
| 540, 556, 572 | half-extents | `hx`, `hy`, `hz` |
| 576, 580, 584 | centre | `cx`, `cy`, `cz` |
| 592 .. 684 (8 x 3 floats) | box corners | `c + (+-hx, +-hy, +-hz)`, corner order `(+++),(-++),(+-+),(--+),(++-),(-+-),(+--),(---)` |
| 700, 716, 732, 748, 764, 780 | six face-plane offsets | `-cx-hx`, `cx-hx`, `-cy-hy`, `cy-hy`, `-cz-hz`, `cz-hz` |

Six other varying words are constant or zero; the remaining ~70 are mass/inertia, uninitialised padding and similar and are left
as in the template. The template used here is `historicaloilportraits_shackleton.nif` (any identity-rotation plain-box NIF
works; `check_template` verifies size, `TAG0` header, `hknpBoxShape`, no compound/compressed-mesh shape, identity matrix).
Box = axis-aligned bounds of all converted geometry, in metres.

## In-game result

- The converted chair loads with collision with no errors.
- Spawning two at the same spot made them **collide with each other and tip over** (so the shapes, positions and sizes are right).
- **Correction after a human play-test:** the player is blocked by them but **cannot push them; they do not move**. The tilt seen
  right after spawning came from two bodies being created inside each other, not from a movable body. So converted props behave
  as solid, fixed scenery (right for most set dressing). Movable clutter would need a dynamic-body template.
- Shadows on the converted props look correct (play-test).

## Not covered yet

- Rotated boxes, convex hulls (the most common vanilla shape, 596 of 2,500), compound and mesh shapes, spheres/capsules.
- Static vs dynamic motion type, mass and inertia, collision layers/materials (sound, footsteps), per-part collision.
- Converting Fallout 4's own collision (`bhkNPCollisionObject` with Havok 2014 data) instead of an AABB.
- Next steps: a convex-hull generator (find where vertex lists sit in a `hknpConvexShape` blob and regress those, or use
  [CoACD](https://github.com/fo76utils/CoACD) for decomposition), then compound shapes for walkable interiors.
