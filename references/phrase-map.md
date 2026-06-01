# Anchor Phrase Map

Map user language to deterministic state actions.

| User phrase | State action |
|-------------|--------------|
| "一个一个过" | If a list exists, initialize root tracker. |
| "逐条讨论" | If a list exists, initialize root tracker. |
| "你来主持" | Initialize or continue tracker; keep position explicit. |
| "下一个" | advance deepest active agenda. |
| "继续" | Read `status`; advance only if current item is complete or explicitly skipped. |
| "回到刚才" | Read `status`; do not reconstruct from memory. |
| "回到上层" | Close, pause, or defer child agenda before parent movement. |
| "这个先跳过" | `defer` current item with reason. |
| "这个等我确认" | `block` current item with reason. |
| "暂停这个清单" | `pause` tracker. |
| "继续刚才的清单" | `resume` if paused, then read `status`. |
| "不跟踪这个" | Do not create tracker; abandon candidate state. |
| "重新开始" | Ask whether to abandon or pause active tracker before creating a new root. |
| "看看还有哪些 TODO 没做" | Run `todo-status`; if open items exist, offer `todo-start`. |
| "继续处理 TODO" | Run `todo-start` from the canonical TODO ledger. |
| "记一个 TODO" | Run `todo-add`; do not hand-edit `.anchor/config.json`. |
| "TODO 都处理完了吗" | Run `todo-status`; answer from the canonical ledger only. |

Default rule: when in doubt, ask one short confirmation instead of guessing.
