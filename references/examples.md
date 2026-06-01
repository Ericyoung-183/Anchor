# Anchor Pressure Examples

Use these examples to decide when to create, advance, pause, or avoid Anchor state.

### Example 1: Review Findings A-G

User asks for a diagnostic review. The assistant produces findings A, B, C, D, E, F, G. User says "我们一个一个过".

Action: create a root tracker with A-G and start at A.

### Example 2: Child Agenda Under C

While discussing C, the assistant identifies subquestions 1, 2, 3, 4, 5. User says "这几个也逐个处理".

Action: `push-child` under C, start at 1, and do not return to D until the child agenda closes, pauses, or is deferred.

### Example 3: Next After Child Item

Current path is `C > 2`. User says "下一个".

Action: advance to `C > 3`, not root D.

### Example 4: Unrelated Side Question

Current path is `C > 2`. User asks an unrelated clarification. After answering, user says "回到刚才，下一个".

Action: read tracker status and advance to `C > 3`.

### Example 5: Skip Current Item

Current item is B. User says "这个先跳过".

Action: `defer` B with a short reason, then advance only when the conversation should continue.

### Example 6: Block Current Item

Current item needs user credentials or a decision. User says "这个等我确认".

Action: `block` the item with the reason. Do not silently mark it complete.

### Example 7: Stop Tracking

User says "这个清单不用跟踪了".

Action: abandon or avoid creating tracker. Confirm only if abandoning active state would lose unresolved items.

### Example 8: Two Independent Lists Collide

An active agenda exists. A new unrelated list appears and user says "这个也逐个过".

Action: ask whether to pause the current agenda, close it, or replace it. Do not silently overwrite the tracker.

### Example 9: Explanatory List Only

Assistant lists three architecture options and user asks for a recommendation.

Action: do not create Anchor state unless the user wants to process options item by item.

### Example 10: Diagnosis Summary Only

Assistant produces findings A-D. User asks "先给我结论".

Action: do not create a tracker yet. If user later says "逐个处理", create one from the frozen finding list.

### Example 11: Closed Tracker

Tracker status is closed. User sends a normal prompt.

Action: render no context. Do not resurrect the closed agenda.

### Example 12: Global Fallback For Unsafe Roots

Current cwd is the user's home directory, Desktop, a non-Git scratch directory, or another unsafe root. User wants to process a list.

Action: use global fallback. Do not create `.anchor/` in the project.

### Example 13: Auto Project-Local State

Current project is a safe Git project. User wants to process a list and no legacy global tracker exists for this thread.

Action: `init` auto-creates `.anchor/config.json` and stores state in `<project-root>/.anchor/state/<thread-id>/`.

### Example 14: Existing Global Tracker

A same-thread tracker already exists in global fallback from before project-local auto-enable was introduced.

Action: keep using the global fallback tracker. Do not migrate or hide active session state.

### Example 15: Overwatch Drift

User says "下一个" while active path is `C > 2`; assistant searches TODO files and starts D.

Action: Overwatch should flag `wrong-next-target` and `recreated-agenda-from-search`.

### Example 16: Continue Project TODO

User says "看看还有哪些 TODO 没做".

Action: run `todo-status`. If open items exist and the user wants to continue, run `todo-start` and host them as the next agenda.

### Example 17: Multiple TODO Files

`TODO.md` and `docs/todo.md` both exist and no canonical TODO is configured.

Action: report `needs_selection` and ask which file should become canonical. Do not merge or pick silently.

### Example 18: TODO Agenda Closed

A TODO-backed agenda closes after all items are completed.

Action: run `todo-sync`, then `todo-status`; if open items remain, ask whether to continue, otherwise say the project TODO is clear.
