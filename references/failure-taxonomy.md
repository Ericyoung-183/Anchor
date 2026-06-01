# Anchor Failure Taxonomy

Use these categories for Overwatch review, debugging, and regression fixtures.

## missed-root-capture

A concrete list and sequential intent exist, but no root tracker is created.

## missed-child-capture

The current item expands into a sequential sublist, but no child agenda is pushed.

## wrong-next-target

The assistant advances to the wrong item, usually returning to a parent agenda before finishing the child agenda.

## skipped-active-item

The assistant advances from A to B without first completing, deferring, or blocking A.

## premature-parent-return

The assistant leaves a child agenda before it is closed, paused, or deferred.

## wrong-child-parent

The assistant creates a child agenda under any item except the current deepest item.

## stale-tracker-ignored

An active tracker exists, but the assistant answers from memory or nearby documents instead of reading it.

## prose-only-state-change

The assistant says an item is complete, skipped, blocked, or paused without updating tracker state.

## recreated-agenda-from-search

The assistant searches TODO files or documents and replaces the frozen agenda with a newly assembled list.

## overwritten-active-tracker

The assistant starts a new agenda for a thread that already has an active or paused tracker, replacing the user's current agenda state.

## active-context-overinjection

Hook or skill context injects long history, full lists, or closed tracker content into active context.

## wrong-project-state-write

Anchor writes project-local state under a broad root, arbitrary non-Git directory, unwritable project, or forced-global mode; or hides an existing same-thread global fallback tracker after project-local enablement.

## ignored-canonical-todo

The assistant scans or edits non-canonical TODO files after `.anchor/config.json` defines `todo.canonical_path`.

## guessed-multiple-todos

The assistant silently chooses or merges among multiple TODO candidates instead of requiring `todo-configure`.

## unsynced-todo-agenda

A TODO-backed agenda closes, but completed items are not synced back to the canonical TODO ledger.

## premature-todo-sync

The assistant syncs an active TODO-backed agenda before closing or pausing it, causing partial progress to be written as if the agenda were finished.

## missing-canonical-todo-misread

The configured canonical TODO file is missing, but Anchor reports the project TODO as empty instead of surfacing the missing file.
