# Anchor Changelog

## 0.3.5 - 2026-06-06

- Tightened raw Codex session pressure checks so helper-returned `whole_picture` only satisfies the rule after the assistant shows a user-visible Whole Picture.
- Reduced raw-session false positives from tool output, `--help`, failed helper commands, smoke-test helper calls, assistant review summaries, and method phrases such as `逐条核验`.
- Added real-session regression fixtures for missing user-visible Whole Picture after `init` and `interrupt`.

## 0.3.4 - 2026-06-06

- Packaged `anchor_pressure_check.py` with the Skill so transcript pressure checks are available in installed and published product copies.
- Preserve real user text that appears after injected Codex context in raw session audit mode.

## 0.3.3 - 2026-06-06

- Added `interrupt` for temporary topic switches without replacing the frozen active agenda.
- Added Codex session audit mode to pressure checks so injected AGENTS/system/Overwatch text does not create transcript false positives.

## 0.3.2 - 2026-06-02

- Require root and child agenda starts to show a concise Whole Picture with the current item marked before handling the first item.
- Return `agenda_snapshot` and `whole_picture` from `init` and `push-child` so the display can come from helper state, not model memory.

## 0.3.1 - 2026-06-02

- Render active agenda context with item text so non-ASCII agenda items remain readable in hook context.
- Treat configured canonical TODO paths outside the project root as `invalid_canonical` and refuse to read or write them.
- Resolve the repository Git exclude path for linked worktrees so project-local `.anchor/` runtime files do not appear in `git status`.

## 0.3.0 - 2026-06-01

- Added Todo Bridge commands for canonical TODO discovery, configuration, add, start, and sync.
- Added project TODO ledger rules: one canonical Markdown file, fail-closed multiple-candidate handling, and TODO-backed agenda sync.

## 0.2.1 - 2026-06-01

- Auto-enable project-local state for new trackers in safe Git projects.
- Preserve existing same-thread global fallback trackers instead of migrating or hiding them.
- Added explicit fallback switches: `ANCHOR_STATE_MODE=global` and `ANCHOR_AUTO_ENABLE_PROJECT=0`.

## 0.2.0 - 2026-06-01

- Added hardened tracker state commands: status, validate, defer, block, pause, resume, abandon, and export-unresolved.
- Added capture protocol references, pressure examples, phrase map, and failure taxonomy.
- Added hook guardrail support for disabled injection, capped context, stale warnings, and unresolved counts.
- Added package-only release scripts and release hygiene checks.
