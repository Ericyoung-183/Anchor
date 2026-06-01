# Anchor Closure Template

Use this when the root agenda closes, the user pauses work for handoff, or unresolved items need persistence.

```text
Anchor agenda closed.

Completed:
- <item>: <decision or result>

Deferred:
- <item>: <reason or next checkpoint>

Blocked:
- <item>: <blocking dependency or user decision needed>

Recommended persistence:
- No persistence needed.
- Or: export unresolved items to project TODO/docs with `export-unresolved`.
- Or: ask the user before writing project memory.
```

Rules:

- Keep closure concise.
- Do not write memory automatically.
- Do not include raw event log noise.
- Persist only unresolved actions or decisions that change future work.
