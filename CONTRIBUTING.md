# Contributing

Thanks for looking. This project is deliberately split into small, self-contained pieces so you can finish
one in a sitting.

## Pick something

1. Read [docs/PLAN.md](docs/PLAN.md) (10 minutes).
2. Open [docs/WORK-PACKAGES.md](docs/WORK-PACKAGES.md) or the GitHub issues. Take a package marked `ready`,
   or a **spike** (S1–S9 in [docs/RISKS.md](docs/RISKS.md)): spikes are the most valuable work right now.
3. Comment on the issue so nobody duplicates it.

## Do it

- Work from the package's **acceptance test**. A change isn't done until that passes.
- Add a **synthetic-fixture test** (build the input bytes in the test; never commit game files).
- Record what you tried in [docs/JOURNAL.md](docs/JOURNAL.md): date, game versions, command, result,
  oracle output (including negative results; they save the next person days).
- For a spike, write `docs/spikes/Sx-<name>.md`: question, method, result, **go / no-go / fallback**.

## Hard rules

- **No game data in commits.** Run `python scripts/guard.py` before every commit. A GitHub Actions template that runs it lives in `ci/` (not enabled yet; see WP-18).
- Don't commit your `config.toml` or any path from your machine.
- Offline / single-player only.
- Python tools that read game data run with `python -I` so they don't import from the data folder.

## Using an AI agent

Read [team status and file ownership](docs/CODEX-HANDOFF.md) first. Claude, Codex and Grok must check
[new or updated GitHub issues](https://github.com/dasscooby/fo4-to-starfield/issues) and relevant comments
before each work session, choosing the next task, or declaring a fix complete. The owner uses issues
as the shared inbox for bug reports and priorities. Follow the active milestone and coordinate ownership.

Reference issue numbers in fixes and keep evidence concise. Offline checks do not establish in-game
acceptance. Keep full discussions in issues instead of copying them into the handoff. Add appropriate
synthetic tests, run the guard, and note AI assistance in the PR.

## Style

Python: type hints, `unittest`, no hidden global state, deterministic output (sorted keys, no timestamps in
generated files). Mapping tables are JSON/TOML in `mappings/` with a one-line rationale per non-obvious entry.
