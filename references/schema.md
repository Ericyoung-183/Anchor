# Anchor State Schema

## Storage

Project-local storage is enabled explicitly by `init-project` or automatically by `init` when the cwd is inside a safe Git project:

```text
<project-root>/.anchor/config.json
```

When enabled:

```text
<project-root>/.anchor/state/<thread-id>/active.json
<project-root>/.anchor/state/<thread-id>/events.jsonl
```

Fallback:

```text
~/.codex/state/anchor/<project-key>/<thread-id>/active.json
~/.codex/state/anchor/<project-key>/<thread-id>/events.jsonl
```

## Tracker

Required fields:

- `version`
- `thread_id`
- `project_root`
- `state_source`
- `status`
- `active_stack`
- `agendas`
- `created_at`
- `updated_at`

Tracker statuses:

- `active`
- `paused`
- `closed`
- `abandoned`

Agenda statuses:

- `active`
- `paused`
- `closed`
- `abandoned`

Item statuses:

- `pending`
- `discussing`
- `child_agenda_active`
- `child_done`
- `decided`
- `actioned`
- `deferred`
- `blocked`

## Invariants

- `active_stack[-1]` is the only agenda that “next” may advance.
- `next` cannot advance while the current deepest item is still discussing or has an active child agenda.
- `push-child` can only attach a child agenda to the current deepest item while that item is discussing.
- A child agenda must close, pause, or defer before the parent advances.
- Closing a child agenda marks the parent `child_done` only when the child has no unresolved items; blocked or deferred child items keep the parent unresolved.
- Project-local writes require `.anchor/config.json`; `init` may auto-create it only for a safe Git root.
- Existing same-thread global-fallback trackers are not migrated or hidden by later project-local enablement.
- Broad roots, non-Git roots, unwritable roots, and forced-global mode use global fallback.
- Project TODO work uses one canonical Markdown ledger stored in `.anchor/config.json` as `todo.canonical_path`.
- Multiple TODO candidates require explicit `todo-configure`; Anchor must not merge or guess.
- A configured canonical TODO path that no longer exists is `missing_canonical`, not an empty TODO list.
- `todo-sync` only runs for closed or paused TODO-backed agendas; it marks actioned, decided, or child_done root TODO items done, while blocked and deferred items stay open.
- Runtime state is not long-term project memory.

## Commands

- `init-project <root>` explicitly enables project-local storage.
- `init` creates a root agenda and may auto-enable project-local storage for a safe Git project; it refuses to replace an active or paused tracker for the same thread. Use `--source-ref` and `--source-excerpt` when the list source is known.
- `push-child` creates a child agenda under the active item; use source fields when the child list source is known.
- `status` prints current stack, current item, unresolved counts, and tracker path.
- `validate` checks tracker references, statuses, stack integrity, and child-parent links.
- `next` advances the deepest active agenda.
- `complete` marks the current item actioned.
- `defer` marks the current item deferred.
- `block` marks the current item blocked.
- `pause` pauses the active tracker without losing the stack.
- `resume` reactivates a paused tracker.
- `abandon` closes the tracker as abandoned and clears the active stack.
- `render-context` prints short hook context for active trackers; `--max-context-chars` caps output and `--stale-after-minutes` adds a stale-state warning.
- `export-unresolved` prints Markdown handoff text for pending, discussing, child_agenda_active, deferred, and blocked items. It does not write Codex memory or append tracker events.
- `todo-status` discovers/configures the canonical TODO ledger when unambiguous and reports open checklist items.
- `todo-configure --path <file> [--create]` sets the canonical TODO ledger.
- `todo-add --text <text>` appends an open TODO, creating `TODO.md` if no ledger exists.
- `todo-start` creates an Anchor agenda from open canonical TODO items.
- `todo-sync` writes a closed or paused TODO-backed agenda back to the canonical TODO ledger.
