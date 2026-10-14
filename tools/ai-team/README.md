# Local AI engineering team for fo4-to-starfield

A local OpenCode team (Lead + Implementation + Research + QA) running on one LM Studio model, behind a
**Resource Guardian** that deterministically limits local inference. Remote agents (Claude, Codex, Grok, ChatGPT)
keep working through GitHub. Architecture: [docs/ai/architecture.md](../../docs/ai/architecture.md).
Rules every agent follows: [AGENTS.md](../../AGENTS.md).

## Pieces and files

| What | Where |
|---|---|
| OpenCode project config (provider, default agent, permissions, `subagent_depth: 1`) | `opencode.json` (repo root) |
| Agents: `fo4-lead` (primary, default), `fo4-implement`, `fo4-research`, `fo4-qa` | `.opencode/agents/*.md` |
| Guardian settings + agent -> model aliases | `tools/ai-team/config.json` |
| Admission proxy (:1235 -> LM Studio :1234) | `tools/ai-team/guardian/proxy.py` |
| Status / report / pause / resume / stop / shutdown | `tools/ai-team/guardian/guardian.py` |
| Remote usage (Codex, Claude Code, Grok logs; GitHub activity) | `tools/ai-team/remote_usage.py` |
| Board + combined status | `tools/ai-team/team.py` |
| Wake an idle Codex / Grok (forks its last session, one headless turn; idle + cooldown guards) | `tools/ai-team/wake_agent.py` |
| Runtime state, history DB, logs (outside the repo) | `%LOCALAPPDATA%\fo4-ai-team\state\` (`guardian.db`, `proxy.log`; override with `FO4_AI_TEAM_STATE`) |
| Project knowledge, optimization log | `docs/ai/` (`optimization.md`: baselines + before/after entries) |

## Start

1. LM Studio server on (`lms server start` or the app), Starfield closed. Load the model:
   `python tools\ai-team\load_model.py` (qwen3-14b, 32K context, q8 KV cache, all on GPU, no memory mapping).
   Don't use `lms load`: it memory-maps the file and holds ~10 GB of system RAM, which makes the guardian block.
2. `powershell -File tools\ai-team\start-team.ps1`: starts the guardian proxy, checks LM Studio, prints status.
3. Interactive: `opencode` in the repository (the Lead is the default agent). Unattended: `powershell -File tools\ai-team\run-lead.ps1`:
   one Lead session per cycle (default 30 min) in its own worktree (branch `ai/local-lead`); skips while Starfield runs or
   the guardian is paused/blocked; reloads the model if LM Studio unloaded it; log `lead-cycles.log` in the state dir.
   One OpenCode session at a time.

Local inference is **blocked while Starfield runs** (the GPU is needed for game tests). Close the game first.

## Status, usage, logs

- `python tools\ai-team\team.py status`: hardware, guardian level/mode, running and queued jobs, recent failures,
  local usage per agent, remote usage, warnings (JSON).
- `python tools\ai-team\team.py board`: GitHub tasks by state (live).
- `python tools\ai-team\guardian\guardian.py status`: just the guardian (exit code 0 ok, 1 restrict, 2 block).
- `python tools\ai-team\guardian\guardian.py report --hours 24`: local requests, tokens, latency, throttling.
- Logs: `%LOCALAPPDATA%\fo4-ai-team\state\proxy.log` (every non-admit decision and job end), `state\guardian.db` (SQLite:
  `jobs`, `decisions`, `samples`, `control`); OpenCode's own logs: `opencode --print-logs`.

## Pause, resume, stop

- Pause (queued and new requests wait, running ones finish): `python tools\ai-team\guardian\guardian.py pause`
- Resume: `... guardian.py resume`
- Graceful shutdown: `powershell -File tools\ai-team\stop-team.ps1`
- Emergency stop (refuse everything at once, then shut down): `... stop-team.ps1 -Emergency`, afterwards
  `guardian.py resume` before the next start. Model unload is manual (`lms unload --all`), never automatic.
- After a crash: start again; jobs left "running"/"queued" are marked `abandoned` (restart recovery).

## What is enforced, and what isn't

Enforced by code (proxy): max 1 concurrent local inference request; resource check before each admission
(RAM 70/85/90%, VRAM 95% block, 92% restrict with a resident model, game running = block, LM Studio down =
block); queue with a bounded wait (600 s) then HTTP 503; bounded upstream retries (2, backoff 2 s / 4 s) only
before any output was sent; request timeout 900 s; pause / stop switch; every decision logged.
Resources are sampled fresh at every admission attempt (`proxy.py`, `_wait_for_admission`), not taken from an
earlier status call; a queued job re-checks every 2 s. A job that is already running is not interrupted if the game
starts or memory rises afterwards: only new admissions are held.
Enforced by OpenCode config: agent permissions (no push/merge/destructive commands, Lead edits only docs/ai,
QA edits nothing, Research edits only its two docs), Lead may delegate only to the three specialists,
specialists cannot delegate (`task: deny`, `subagent_depth: 1`).

**Not controlled** (bypasses): LM Studio's chat UI or anything calling :1234 directly; the remote agents (Claude,
Codex, Grok, ChatGPT) and their subscriptions; OpenCode's built-in `explore`/`general` subagents are available
to manual `@` use. Remote usage figures are read from local session logs where they exist (Codex also writes its
plan's rate-limit percentages); nothing is invented, ChatGPT shows as unavailable.

## GitHub workflow

Issues = tasks (labels `ready`, `in-progress`, `blocked`, `spike`, `needs-qa`, `review`); comments carry progress,
each starting with the role (`Lead (local):`, `QA (local):`, `Claude:`, ...); substantial work on a branch
`ai/<issue>-<slug>` in its own worktree (`git worktree add ../fo4-to-starfield-wt/<name> -b ai/<issue>-<slug>`);
PR for review; QA review before merge; merging and pushing need the owner's approval. Labels can be stale; the Lead
also reads #32 and docs/CODEX-HANDOFF.md.

## Manual operations

Choosing/downloading/loading the model; starting LM Studio; starting OpenCode; approving PR creation, merges and
pushes; any game deployment or live testing (Claude's lane); installing anything as a service (not done).

## Validation (2026-10-09, Qwen3-14B Q4_K_M, 32K context)

| # | Test | Result |
|---|---|---|
| 1 | LM Studio API responds | pass |
| 2 | OpenCode connects to the model (via the guardian) | pass |
| 3 | Model performs a real tool call (`file_size` with correct args) | pass, 10.4 s, 174/147 tokens |
| 4 | Lead invokes a specialist (`task` -> fo4-research) | pass |
| 5 | Research reads project files (exact first heading of docs/PLAN.md) | pass, whole run 231 s |
| 6 | Implementation works in an isolated test branch (`ai/test-validation`, own worktree) | pass |
| 7 | QA reviews without modifying (its edit attempt was refused by permissions) | pass, whole run 522 s |
| 8 | `gh` reads repository issues | pass |
| 9 | Resource monitoring returns valid JSON | pass |
| 10 | Thresholds trigger the expected scheduling (4 unit tests + live) | pass |
| 11 | Overloaded system queues new work (game running; RAM 88-90%; 1 running >= max 1) | pass |
| 12 | Logs record the activity (26 requests with API token counts, 8 throttling decisions) | pass |
| 13 | Shutdown leaves no orphaned jobs or processes | pass |

Observed: each Lead step takes ~40-135 s; Qwen3 writes long `<think>` reasoning first (next optimization
candidate: measure with thinking off). The Lead once mis-formatted a task call and corrected itself.

## Tests
`python -m unittest tests.test_ai_guardian` (admission policy on synthetic snapshots); validation results of the
initial setup are in docs/ai/decisions.md and the setup report.
