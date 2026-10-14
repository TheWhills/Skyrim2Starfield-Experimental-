# Known unknowns

Open questions that block or risk work. Remove an entry only with a link to the evidence that resolved it.

| # | Question | Blocks | Where it's tracked |
|---|---|---|---|
| 1 | `.af` per-bone channel layout (which bytes hold each bone's translation/rotation) | sliding vault / elevator doors | docs/spikes/WP-doors-research.md |
| 2 | Primitive encoding of FO4 precombine bodies with shared-index triples | 36 models on guessed collision boxes | research-log.md, journal |
| 3 | Do the one-sided door blocks disappear with E pressed outside the swing arc for all doors? | door acceptance (#32) | journal, route runs |
| 4 | Effect-shader wall stains as decals: dark sheets or correct? (FO4 gradient palette not reproduced) | material quality | journal |
| 5 | Does Qwen3-14B Q4_K_M (chosen by Claude + Codex, #32) do reliable OpenCode tool calls at 16K context, and what VRAM does it use? | local team | validation pending (game must be closed) |
| 6 | Which FO4 motion entries are dynamic (pushable) vs keyframed: decode the motion cinfo array and inverse mass | physics objects block doorways (Vault 114 `05C7DC`) | research-log.md 2026-10-09 |
