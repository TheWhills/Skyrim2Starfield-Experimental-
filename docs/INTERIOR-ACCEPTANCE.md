# Interior slice acceptance

The shipping milestone is eight interiors in one deployed build. This checklist does not
record a pass. A pass is an evidence JSON that
[`scripts/oracles/interior_acceptance.py`](../scripts/oracles/interior_acceptance.py)
accepts. Journal screenshots and offline round-trips are leads, not rows.

Actors, terrain, weapons, and Papyrus stay out until this slice exits 0.

## Cells

Vault 111, Vault 81, Red Rocket cave, Vault 114, Prydwen, Hotel Rexford, Boston Public
Library, Parsons.

## Per cell

| Check | Pass means |
|---|---|
| `walkable` | Floors and stairs hold the player. No fall-through. |
| `doorways` | A closed door blocks. An open hinged door can be walked through. A load door stays solid; falling through it fails the cell. |
| `door_swing` | Both sides of each hinged door open on OPEN, and the leaf rests in the frame. Walking through a leaf the other side already opened does not count. Load doors stay shut; teleport is not this check. |
| `selected_body` | Each attachment uses its own selected Havok body. A shared system does not put every body on every node. |
| `frame_collision` | The frame blocks. Only the opening changes when the leaf moves. |
| `lighting` | The room is neither washed out nor fully metallic. |
| `materials` | Surfaces read as the source materials, including decals that are part of the cell. |

## Build gates

These apply once to the deployed revision, not once per cell.

| Check | Pass means |
|---|---|
| `startup` | The game starts with this build installed and reaches a load. |
| `single_model` | One transplanted collision model is spawned before the whole slice is judged. |
| `rollback` | Uninstall removes this build and the game starts without it. |

## Evidence

`revision` is the 40-digit lowercase git sha that was built. `build_id` names that
staging build. `installed` lists relative paths and lowercase sha256 hashes of the files
that were actually installed. Every check is `{result, kind, evidence}`. `result` is
`pass`, `fail`, or `unverified`. `kind` is `game` or `offline`. `evidence` is a
non-empty note of what was seen.

A `pass` counts only when `kind` is `game` and the revision, build id, and install hashes
are present. An offline parse, a mesh round-trip, or a screenshot that is not tied to
those pins does not close a row. A missing row stays unverified. The oracle exits 1
while any row is unverified, failed, or malformed.

`door_swing` stays open when the route file never recorded OPEN. Both sides ending past
the plane is geometry. It is not a swing. A route file that omits a manifest swinging
door does not cover that cell; `scripts/oracles/route_coverage.py` lists those refs.
Two routes on the same side are still one side.
A generation that keeps only the first routes can drop doors that sit later in the cell.
The earlier Prydwen file was 40 stairs, and its three swinging doors were past that cut.
The regenerated file lists both sides of those three. The list is not a walk.
`scripts/oracles/route_activation.py` lists every hinged ref in a results file that
lacks two OPEN crossings. When a route records `side`, those crossings count only if
the sides are 1 and -1 and their plane normals point opposite ways. Two OPEN crossings
on the same side are still one side. Two OPEN crossings in the same direction are still
one side, even when the routes are labeled 1 and -1. A file that never stored `side`
still counts two visits only when those normals point opposite ways.
A partial file can show that pair for some refs and leave the rest unproven. That
count does not close `door_swing`. `route_eval` can exit 0 on one recorded OPEN.
That is not `door_swing`. A placed model whose FO4 collision failed is not a walkable pass.
`scripts/oracles/placed_collision.py` lists those refs, and refs whose mesh the build
rejected. A guessed box is not a native body. A skipped-part note with a box fallback
is still a guessed box. A native body that also skipped a part is partial, not clean.
Evidence that names a machine-specific
path cannot close a row.

Do not commit the evidence file if it names a machine path or contains game data.
There is no accepted evidence file in the repo. Every row above is unverified.

```
python scripts/oracles/interior_acceptance.py --evidence <evidence.json>
```
