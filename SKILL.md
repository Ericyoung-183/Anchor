---
name: anchor
description: Use when a coding or analysis conversation forms a multi-item discussion list, review finding list, diagnosis list, or nested follow-up list and the user wants to proceed item by item without losing position
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
4. Finish or pause a child layer before returning to its parent.
5. If no active state exists, rebuild from a clear source or ask the user.
6. At closure, export unresolved actions only if they need long-term project memory, TODO, or docs.

## Storage Rule

Project-local state is allowed only when the target project has `.anchor/config.json`. Otherwise use the global fallback. Never create `.anchor/` inside an arbitrary project without explicit enablement.

## Helper

Use `scripts/anchor.py` for deterministic state handling. See `references/schema.md` for the state shape and invariants.

