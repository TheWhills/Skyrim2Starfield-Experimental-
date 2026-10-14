# Brief for ChatGPT (paste this into a new chat)

You are joining an open-source project, https://github.com/dasscooby/fo4-to-starfield. It ports Fallout 4 interiors into
Starfield's Creation Engine 2 with our own converters (Python + .NET, no game assets in Git). Three agents already work on
it: Claude (collision/conversion/live game tests), Codex (deployment, IDs, door rig modules), Grok (acceptance checks).
Status and coordination: issue #32 and `docs/CODEX-HANDOFF.md`; history: `docs/JOURNAL.md`.

**Your lane: file-format research, offline, no game or PC access needed.** Pick one, post findings on #32 with byte offsets
and how you verified them. Don't guess silently; say what is confirmed and what is a hypothesis.

1. **Starfield `.af` animation files** (needed to make FO4 sliding vault and elevator doors open). Notes so far:
   `docs/spikes/WP-doors-research.md`, section "Sliding doors" and ".af first look". The Akila hinged door's `open.af` is
   218 bytes: 6 bones, 31 frames, a 16-entry keyframe table, packed values, then one smooth 16-bit channel (likely the
   hinge rotation). Goal: per bone, decode translation/rotation over time. Any public knowledge of this format (it may be
   ACL-like compressed animation) is very useful.
2. **FO4 Havok 2014 `hknpCompressedMeshShapeData` primitive encoding used in precombined meshes** (`SCOL\CM*.NIF`).
   Normal sections decode fine (`src/fo4sf/fo4collision.py`). Some precombine bodies have 0 packed vertices, 4 shared
   vertices per primitive, primitives like `(3,2,2,2)`, and a shared-index array of triples `(2130, start, x)` with start
   stepping by 4 and x looking like a half-float near 1.0. What is this encoding (convex primitives? a different primitive
   type flag?). Correction: these are not all thin rods; some four-vertex groups span ~3 m in every axis, and grouping by
   4 is itself unconfirmed. See `docs/JOURNAL.md`, "Precombine debris parts".

Rules: no game assets in Git; no passwords, payments or outreach; keep posts short and factual.
