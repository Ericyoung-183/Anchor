---
name: anchor
description: Use when a coding or analysis conversation forms a multi-item discussion list, review finding list, diagnosis list, project TODO backlog, or nested follow-up list and the user wants to proceed item by item without losing position
---

# Anchor

Anchor keeps live discussion agendas from drifting. Use it when the conversation has a concrete list to process sequentially, especially when “next” must mean the next item in the current deepest layer.

## When To Start

Start Anchor only when both signals exist:

- A concrete list exists: review findings, diagnosis issues, audit items, TODO discussion items, or child questions under the current item.
- The conversation shows item-by-item intent: “one by one”, “next”, “continue”, “you host”, “逐条讨论”, “一个一个过”, or equivalent.

Do not start Anchor for ordinary explanatory lists, brainstorm options, or long-term backlog scans without item-by-item intent.

## Required Behavior

1. Freeze the source list before discussing items.
2. Use the helper script for state changes; do not rely on memory.
3. Interpret “next” from the deepest active agenda layer.
4. Complete, defer, or block the current item before advancing.
5. Finish or pause a child layer before returning to its parent.
6. If no active state exists, rebuild from a clear source or ask the user.
7. At closure, export unresolved actions only if they need long-term project memory, TODO, or docs.

## Anchor Capture Protocol

Use this trigger matrix before responding to list-processing turns:

| Situation | Action |
|-----------|--------|
| list exists + sequential intent | `init` root tracker with source fields |
| active item creates sublist + sequential intent | `push-child` under the current item |
| user says “next” and tracker exists | `next` from the deepest active agenda |
| user skips current item | `defer`, then advance only when appropriate |
| user is blocked on current item | `block`, preserving reason |
| user pauses the agenda | `pause`; do not keep injecting active context |
| user resumes | `resume`, then read `status` |
| ambiguous list | ask one short confirmation before creating state |
| user says not to track | do not create tracker; abandon candidate state |
| no tracker exists but user says “back/next” | do not guess; rebuild source or ask |

When creating root and child agenda state, include `--source-ref` and `--source-excerpt` when available. Before discussing the first item, show a concise "Whole Picture" of the full agenda, mark the current item, then continue. Keep it brief: agenda title, ordered items, current marker, and the first item to handle.

## Storage Rule

When `init` creates a new tracker in a safe Git project, the helper auto-enables project-local state by creating `.anchor/config.json`, `.anchor/state/`, and `.git/info/exclude` entries. Existing global-fallback trackers stay global for the same thread. Use global fallback for broad roots, non-Git or unwritable directories, `ANCHOR_STATE_MODE=global`, or `ANCHOR_AUTO_ENABLE_PROJECT=0`.

## Project TODO Bridge

When the user asks about remaining TODOs, continuing project TODOs, recording a TODO, or processing TODOs one by one, use the helper's TODO commands. `todo-status` discovers the canonical TODO ledger and reports open items; `todo-configure` chooses the only active TODO file when discovery needs selection; `todo-add` records new TODOs; `todo-start` creates an agenda from open TODO items; `todo-sync` writes closed or paused TODO-backed agendas back to the ledger. Do not hand-edit `.anchor/config.json` or treat multiple TODO files as one active source.

## Helper

Use `scripts/anchor.py` for deterministic state handling.

References:

- `references/schema.md`: state shape, commands, invariants.
- `references/examples.md`: realistic pressure examples.
- `references/phrase-map.md`: user phrase to state action mapping.
- `references/failure-taxonomy.md`: drift categories for review and debugging.
- `references/closure-template.md`: concise closure handoff format.
