# Local AI team: architecture

```
                         GitHub (issues = tasks, comments = messages, PRs = proposed changes)
                           ^            ^             ^                 ^
                           |            |             |                 |
  remote agents:     Claude Code    Codex CLI       Grok CLI         ChatGPT (app)      <- own subscriptions,
  (own processes)    (live game)    (deploy, IDs)   (acceptance)     (format research)     not controlled locally
                           |
  local team (OpenCode, one session at a time)
  +-------------------------------------------------------------------------------+
  |  fo4-lead (primary, default)   -- task tool -->  fo4-research (read-only)      |
  |    reads issues, picks one task,                  fo4-implement (own worktree)  |
  |    checks guardian, delegates,                    fo4-qa (no edits, runs tests) |
  |    reviews, drafts PRs                            subagent_depth = 1: no chains |
  +--------------------------|----------------------------------------------------+
                             | OpenAI-compatible API, model = agent alias (fo4-lead, fo4-qa, ...)
                             v
  Resource Guardian proxy  127.0.0.1:1235   (tools/ai-team/guardian/proxy.py)
    admission controller: max 1 local inference, resource policy, queue, pause/stop, logs -> %LOCALAPPDATA%\fo4-ai-team\state\guardian.db
                             |
                             v
  LM Studio server  127.0.0.1:1234   one loaded coding model shared by all aliases
                             |
                             v
  RTX 4070 Ti 12 GB  (shared with Starfield: the game blocks local inference)
```

- **Deterministic control** is the proxy, not a prompt: every local agent request passes it; it admits one at a
  time, checks GPU/RAM/LM Studio/game state first, queues or rejects otherwise, and records usage.
- **Bypasses** (not controlled): LM Studio's own chat UI or any tool calling :1234 directly; all remote agents.
- **Status**: `python tools/ai-team/guardian/guardian.py status` (JSON). Usage: `guardian.py report`,
  remote side `tools/ai-team/remote_usage.py`.
- Details and operation: [tools/ai-team/README.md](../../tools/ai-team/README.md). Decisions: [decisions.md](decisions.md).
