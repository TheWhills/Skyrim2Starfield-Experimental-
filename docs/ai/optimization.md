# Optimization log

Ongoing (AGENTS.md "Keep optimizing"). Every entry: date, agent, what, **measured before / after** (same command,
same input), and the commit. Use the `optimization` label on the issue or PR.

## Baselines (measured 2026-10-09 on the owner's PC; Ryzen 9 7950X3D, RTX 4070 Ti 12 GB, 32 GB)

| What | Command | Measured | Source |
|---|---|---|---|
| Full conversion build, 15 cells / 4,014 models | `scripts/convert_batch.py --cell-json merged.json` (no `--resume`) | 311–373 s | Claude, journal 2026-10-09 |
| Plugin write, 15 cells | `dotnet/PluginSpike` | ~10 s (not timed precisely) | Claude |
| Unit tests (241) | `python -m unittest discover -s tests` | 2.4 s | Claude |
| Deploy + launch + load cell | `research/s1/cycle.ps1` | ~3 min | Claude |
| Parsons route run, 45 routes | `scripts/game/route_run.ps1` | ~2 min per door route (prompt search + console checks) | Claude, in progress |
| Guardian status (one sample) | `guardian.py status` | 1.1 s | Claude |
| Remote usage report, 24 h | `remote_usage.py` | 2.7 s | Claude |
| Local model tokens per task | `guardian.py report` | no data yet (no model) | n/a |

## Candidates (not done; each needs a before/after)
- Build: `--resume` checkpoints (Codex) instead of full rebuilds when only a few models change. The last six
  Claude rebuilds were full (~6 min each) for changes touching 2–118 models.
- Route runs: the prompt search takes up to 9 screenshot+OCR rounds per door; start the tilt from the last
  successful pitch per cell.
- Remote usage: Codex 102 M input tokens in 24 h, 96% cached; Claude 160 M cache reads; Grok 73 M input.
  Long single sessions dominate. Shorter sessions with handoff notes may cut cached-context cost; measure first.

## Entries

### 2026-10-09 Claude: model load without memory mapping (local team)
Before: `lms load qwen3-14b --gpu max` -> LM Studio held 10.5 GB of system RAM for a model fully in VRAM; RAM 88.2%,
the guardian held every request (restrict/block). After: `tools/ai-team/load_model.py` (tryMmap=false,
keepModelInMemory=false) -> LM Studio 5.4 GB, RAM 71.4%, VRAM unchanged (10,890 -> 10,930 MiB). Requests admitted.

### 2026-10-09 Claude: 32K context at the cost of 16K (local team)
OpenCode's own system prompt + tools is ~12K tokens; at 16K context it compacted and re-continued in a loop.
Before: 16K, f16 KV cache, VRAM 10,952 MiB. After: 32K, q8_0 K/V cache + flash attention, VRAM 11,061 MiB (90.1%,
below the 92% restrict level with a resident model). Twice the context for +109 MiB.

### 2026-10-09 Claude: wake remote agents with a fresh session, not a fork
Before: `wake_agent.py` forked Codex's last session; one headless turn reported **5,677,999 tokens used** (the
whole long session history replayed) and, in the default read-only sandbox, could not fix or post anything.
After: default is a fresh session with a short brief pointing at #32 / handoff / AGENTS.md, with workspace-write +
network. `--fork` stays available when the old context is really needed. After (measured): the next fresh-session wake fixed the bug it was briefed on, ran the tests and the guard, and
opened PR #34 using **54,793 tokens** (99% less than the fork's 5,677,999).
