# Anchor State Schema

## Storage

Project-local storage is enabled by:

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

## Invariants

- `active_stack[-1]` is the only agenda that “next” may advance.
- A child agenda must close, pause, or defer before the parent advances.
- Project-local writes require `.anchor/config.json`.
- Runtime state is not long-term project memory.

