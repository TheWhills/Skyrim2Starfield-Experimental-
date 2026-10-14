# Agent status

**Not live.** Each line is a snapshot with its date and source; refresh from the source before relying on it.
Live sources: GitHub issue #32 and labels (`in-progress`, `blocked`, `needs-qa`), `git log origin/main`,
docs/CODEX-HANDOFF.md, and `python tools/ai-team/guardian/guardian.py status` for the local team.

| Agent | Role | Last known activity | Source, date |
|---|---|---|---|
| Claude (remote) | collision/conversion, live game tests | pinned-build route results (V111 12/12, Parsons 11 doors both sides); FO4 dynamic-body rule | #32, git log, 2026-10-10 |
| Codex (remote) | deployment/recovery, checkpoints, door bridge | PR #34 (QA PASS, awaiting owner merge); PR #35 in progress | gh pr list, 2026-10-10 |
| Grok (remote) | acceptance oracle | opposite-direction both-sides rule (`1f7e712`) | git log, 2026-10-09 |
| ChatGPT (remote) | format research | `.af` profile comparison and corrections | git log, 2026-10-09 |
| fo4-lead (local) | supervisor | woke Codex (2026-10-09); first unattended cycle failed (task_id), fixed `0940d32` | lead-cycles.log, 2026-10-09 |
| guardian (local) | admission control | paused manually at 23:28 on 2026-10-09; still paused | guardian.py status, 2026-10-10 |
