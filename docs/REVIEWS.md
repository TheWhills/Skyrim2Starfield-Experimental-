# External reviews

Outside reviewers (people or other AI agents) can review this repo through GitHub. Findings arrive as an issue labelled
`review`; each finding is checked against the code, then fixed with a regression test or answered with evidence, and the issue
links the commits. Reviewers: please state what you ran or read for each finding and how to reproduce it.

Suggested prompt for an AI reviewer:

> Review https://github.com/dasscooby/fo4-to-starfield (start with README, docs/PLAN.md, docs/JOURNAL.md and the latest commits).
> Look for correctness bugs in `src/fo4sf`, `dotnet/`, `scripts/` that would make converted Fallout 4 content look, collide or
> load wrong in Starfield, or make the pipeline lose data silently. For each finding give: file and function, what goes wrong,
> a minimal reproduction (input + expected vs actual), and a suggested fix. Prefer few verified findings over many guesses.
> Do not propose committing game files. Check the open `review` issues first so you don't repeat resolved points.

## Review 1 (2026-10-08): ten findings, all confirmed; nine fixed, #8 partly open; follow-ups in docs/CODEX-HANDOFF.md

| # | Finding | Status |
|---|---|---|
| 1 | Connected floor triangles became one enclosing box, filling holes | Fixed: flat patches are rasterised on a 25 cm grid and merged into rectangles (`sfcollision._plane_rects`); test with a floor hole |
| 2 | Box caps silently dropped coverage | Fixed: drops are counted in a report carried into `manifest.json` (`collision_report`); surface cap raised to 160 |
| 3 | Normals / tangents not rotated with the shape | Fixed in `convert_static.shape_to_mesh`; test |
| 4 | Parent node transforms ignored | Fixed: `nif.world_transforms` composes every NiNode ancestor; test with a nested, rotated node |
| 5 | Texture-set cache keyed by diffuse only | Fixed: identity = hash of diffuse + normal + spec |
| 6 | Material resource IDs from the basename could repeat | Fixed: name (and so the ID salt) from the full material path |
| 7 | Probe could report misleading passes | Fixed: X/Y reach checked (`MOVED`), `LOWER` (0.6-3 m drop, e.g. stairs) separated from `FALL` (> 3 m) |
| 8 | Disabled state / original types flattened | Partly: initially-disabled refs keep the flag; original record types are still in the cell export but not yet written |
| 9 | FormIDs depended on conversion order | Fixed: persistent `formids.json` identity map (STAT by editor ID, CELL by name, REFR by source FO4 FormKey); reruns identical |
| 10 | Deployment could leave a partial install | Fixed: all archives built and validated first, manifest written before copying, rollback on failure |
