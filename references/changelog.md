# Anchor Changelog

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
