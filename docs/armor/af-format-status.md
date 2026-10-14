# Starfield `.af` animations: what is known, and from where (2026-10-14)

**Correction (Claude):** in chat on 2026-10-14 I said `.af` track encoding was unknown to this project. Wrong: it is
implemented in open source, and this repository already writes `.af` through it (`src/fo4sf/native_door.py`).

## Sources
* **CALUMI.Animation** (github.com/Calaverah/CALUMI.Animation, read at b0f3b5c, 2026-03-18): a C++ library that reads
  and writes Starfield `.af` animations and `.rig` skeletons, with an extern "C" API (CreateAnimationC,
  CreateAnimBlockC, Create{Rotation,Translation,Scalar}EntryC, SaveAnimationToSFBGSFormatDirectC,
  SaveSkeletonRigToSFBGSFormatDirectC, ...). **License: LGPL-3.0** (headers alone: MIT). Self-described alpha;
  "Planned: compression algorithm(s), full .af/.rig decoding".
* The Blender add-on Animation IO (deveris256/sf_animation_io, Nexus 16184) is built on the same DLL.
* This repo: `native_door.py` calls the DLL at run time via ctypes (`--dll`, never vendored, outputs outside the repo);
  `scripts/oracles/native_door_animation.py` round-trips synthetic rigs/clips through it (same-library readback, 186
  rotation samples within 1e-4; not an independent parser, not yet played in game).
* `docs/spikes/WP-doors-research.md`: header u16 at 0x28 field 2 = rig bone count (**verified**, 4 door families).

## Still open in the format (from CALUMI's own source comments)
Header flag bits marked UNKNOWN ("appears blank"), a "preamble" section of unknown meaning before the animation data,
"unknown suffix fill" floats/blocks, an `indexAtlas` whose entry width is unconfirmed, one unknown scalar per rig bone;
compressed rotations are read (RLE-prefixed), further compression schemes are "planned".

## Licensing rule for this repo (MIT)
Call the DLL at run time (dynamic linking, as native_door.py does) and read its source to understand the format: fine.
Do **not** paste or port CALUMI source into this MIT repository; an independent reader written here must come from
the files themselves (round-trip evidence), not from translating LGPL code.

## How "completely understood" gets measured
1. Round-trip survey on the owner's PC (`scripts/armor/af_roundtrip_survey.py`): every vanilla `.af` read through
   CALUMI with its rig, decoded, re-saved, reloaded and compared value by value. CALUMI's writer stores every bone
   uncompressed ("Will need compression algorithm eventually", SFBGS_AnimationScene.cpp), so the measure is decoded
   values, not bytes. load_failed / no_rig = what CALUMI cannot read; values_differ = reader / writer disagreement;
   values_equal = self-consistent, not yet proof the game agrees (step 2).
2. In-game write test: replace one vanilla idle `.af` (loose file, same path) with a CALUMI-written edit of itself
   (e.g. one arm raised) and see it play.
3. Study only what the survey shows is not round-tripping (the UNKNOWN fields above), with controlled synthetic clips.
   Findings go to the research log and, as bug reports / notes, upstream to CALUMI.
