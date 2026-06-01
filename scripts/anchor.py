#!/usr/bin/env python3
"""Deterministic tracker helper for Anchor."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VERSION = 1
BROAD_ROOT_NAMES = {"/", str(Path.home()), str(Path.home() / "Desktop")}


@dataclass(frozen=True)
class Storage:
    project_root: Path
    state_source: str
    tracker_dir: Path
    tracker_path: Path
    events_path: Path


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return cleaned or "item"


def project_key(path: Path) -> str:
    resolved = str(path.resolve())
    digest = hashlib.sha1(resolved.encode("utf-8")).hexdigest()[:10]
    return f"{slug(path.name)}-{digest}"


def is_broad_root(path: Path) -> bool:
    try:
        resolved = str(path.resolve())
    except Exception:
        resolved = str(path)
    return resolved in BROAD_ROOT_NAMES


def find_upward(cwd: Path, marker: str) -> Path | None:
    current = cwd.resolve()
    for candidate in [current, *current.parents]:
        if is_broad_root(candidate):
            return None
        if (candidate / marker).exists():
            return candidate
    return None


def find_git_root(cwd: Path) -> Path | None:
    return find_upward(cwd, ".git")


def find_enabled_root(cwd: Path) -> Path | None:
    return find_upward(cwd, ".anchor/config.json")


def default_global_state_root() -> Path:
    return Path.home() / ".codex" / "state" / "anchor"


def resolve_storage(
    cwd: str | Path,
    thread_id: str,
    global_state_root: str | Path | None = None,
) -> Storage:
    cwd_path = Path(cwd).resolve()
    explicit_root = os.environ.get("ANCHOR_PROJECT_ROOT", "").strip()
    global_root = Path(global_state_root).expanduser() if global_state_root else default_global_state_root()

    candidates: list[Path] = []
    if explicit_root:
        candidates.append(Path(explicit_root).expanduser().resolve())
    enabled = find_enabled_root(cwd_path)
    if enabled:
        candidates.append(enabled)

    for candidate in candidates:
        if (candidate / ".anchor" / "config.json").is_file() and not is_broad_root(candidate):
            tracker_dir = candidate / ".anchor" / "state" / thread_id
            return Storage(
                project_root=candidate,
                state_source="project-local",
                tracker_dir=tracker_dir,
                tracker_path=tracker_dir / "active.json",
                events_path=tracker_dir / "events.jsonl",
            )

    git_root = find_git_root(cwd_path)
    project_root = git_root if git_root and not is_broad_root(git_root) else cwd_path
    tracker_dir = global_root / project_key(project_root) / thread_id
    return Storage(
        project_root=project_root,
        state_source="global-fallback",
        tracker_dir=tracker_dir,
        tracker_path=tracker_dir / "active.json",
        events_path=tracker_dir / "events.jsonl",
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def append_event(storage: Storage, event: dict[str, Any]) -> None:
    storage.events_path.parent.mkdir(parents=True, exist_ok=True)
    event = {"at": now_iso(), **event}
    with storage.events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def load_tracker(cwd: str | Path, thread_id: str, global_state_root: str | Path | None = None) -> tuple[dict[str, Any], Storage]:
    storage = resolve_storage(cwd, thread_id, global_state_root)
    if not storage.tracker_path.is_file():
        raise FileNotFoundError(f"Anchor tracker not found: {storage.tracker_path}")
    return json.loads(storage.tracker_path.read_text(encoding="utf-8")), storage


def save_tracker(tracker: dict[str, Any], storage: Storage) -> dict[str, Any]:
    tracker["updated_at"] = now_iso()
    write_json(storage.tracker_path, tracker)
    return {
        "tracker_path": str(storage.tracker_path),
        "state_source": storage.state_source,
        "project_root": str(storage.project_root),
    }


def init_project(root: str | Path, project_name: str | None = None) -> dict[str, Any]:
    project_root = Path(root).expanduser().resolve()
    if is_broad_root(project_root):
        raise ValueError(f"Refusing to enable broad root: {project_root}")

    anchor_dir = project_root / ".anchor"
    state_dir = anchor_dir / "state"
    anchor_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "version": VERSION,
        "project_name": project_name or project_root.name,
        "project_root": str(project_root),
        "created_at": now_iso(),
        "storage": "project-local-when-enabled",
    }
    config_path = anchor_dir / "config.json"
    if config_path.exists():
        existing = json.loads(config_path.read_text(encoding="utf-8"))
        config = {**existing, "project_root": str(project_root), "version": VERSION}
    write_json(config_path, config)

    git_exclude = project_root / ".git" / "info" / "exclude"
    if git_exclude.exists():
        text = git_exclude.read_text(encoding="utf-8")
        additions = [pattern for pattern in [".anchor/config.json", ".anchor/state/"] if pattern not in text]
        if additions:
            suffix = "" if text.endswith("\n") or not text else "\n"
            git_exclude.write_text(f"{text}{suffix}" + "\n".join(additions) + "\n", encoding="utf-8")

    return {
        "project_root": str(project_root),
        "config_path": str(config_path),
        "state_dir": str(state_dir),
    }


def make_items(items: list[str]) -> list[dict[str, Any]]:
    seen: dict[str, int] = {}
    result = []
    for raw in items:
        base = slug(raw)
        count = seen.get(base, 0) + 1
        seen[base] = count
        item_id = base if count == 1 else f"{base}-{count}"
        result.append({
            "id": item_id,
            "text": raw,
            "status": "pending",
            "conclusion": "",
            "child_agenda_ids": [],
            "updated_at": now_iso(),
        })
    return result


def set_item_status(item: dict[str, Any], status: str, conclusion: str = "") -> None:
    item["status"] = status
    if conclusion:
        item["conclusion"] = conclusion
    item["updated_at"] = now_iso()


def find_item(agenda: dict[str, Any], item_id: str) -> dict[str, Any]:
    for item in agenda["items"]:
        if item["id"] == item_id:
            return item
    raise KeyError(f"Item not found: {item_id}")


def current_path(cwd: str | Path, thread_id: str, global_state_root: str | Path | None = None) -> list[str]:
    tracker, _ = load_tracker(cwd, thread_id, global_state_root)
    path = []
    for agenda_id in tracker.get("active_stack", []):
        current = tracker["agendas"][agenda_id].get("current_item_id")
        if current:
            path.append(current)
    return path


def init_tracker(
    cwd: str | Path,
    thread_id: str,
    title: str,
    items: list[str],
    global_state_root: str | Path | None = None,
) -> dict[str, Any]:
    if not items:
        raise ValueError("Anchor tracker requires at least one item")
    storage = resolve_storage(cwd, thread_id, global_state_root)
    agenda_items = make_items(items)
    set_item_status(agenda_items[0], "discussing")
    tracker = {
        "version": VERSION,
        "thread_id": thread_id,
        "project_root": str(storage.project_root),
        "state_source": storage.state_source,
        "status": "active",
        "active_stack": ["agenda-root"],
        "agendas": {
            "agenda-root": {
                "id": "agenda-root",
                "title": title,
                "parent_agenda_id": None,
                "parent_item_id": None,
                "source_ref": "",
                "source_excerpt": "",
                "status": "active",
                "current_item_id": agenda_items[0]["id"],
                "items": agenda_items,
            }
        },
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    result = save_tracker(tracker, storage)
    append_event(storage, {"type": "init_tracker", "title": title, "items": items})
    return {**result, "current_path": current_path(cwd, thread_id, global_state_root)}


def complete_current(
    cwd: str | Path,
    thread_id: str,
    global_state_root: str | Path | None = None,
    conclusion: str = "",
    status: str = "actioned",
) -> dict[str, Any]:
    tracker, storage = load_tracker(cwd, thread_id, global_state_root)
    agenda = tracker["agendas"][tracker["active_stack"][-1]]
    item = find_item(agenda, agenda["current_item_id"])
    set_item_status(item, status, conclusion)
    result = save_tracker(tracker, storage)
    append_event(storage, {"type": "complete_current", "item_id": item["id"], "status": status})
    return {**result, "current_path": current_path(cwd, thread_id, global_state_root)}


def next_pending_after(agenda: dict[str, Any]) -> dict[str, Any] | None:
    current_id = agenda.get("current_item_id")
    start = 0
    if current_id:
        for idx, item in enumerate(agenda["items"]):
            if item["id"] == current_id:
                start = idx + 1
                break
    for item in agenda["items"][start:]:
        if item["status"] == "pending":
            return item
    return None


def next_item(
    cwd: str | Path,
    thread_id: str,
    global_state_root: str | Path | None = None,
) -> dict[str, Any]:
    tracker, storage = load_tracker(cwd, thread_id, global_state_root)
    while tracker["active_stack"]:
        agenda_id = tracker["active_stack"][-1]
        agenda = tracker["agendas"][agenda_id]
        next_item_obj = next_pending_after(agenda)
        if next_item_obj:
            set_item_status(next_item_obj, "discussing")
            agenda["current_item_id"] = next_item_obj["id"]
            result = save_tracker(tracker, storage)
            append_event(storage, {"type": "next_item", "item_id": next_item_obj["id"]})
            return {**result, "current_path": current_path(cwd, thread_id, global_state_root)}

        agenda["status"] = "closed"
        tracker["active_stack"].pop()
        append_event(storage, {"type": "close_agenda", "agenda_id": agenda_id})
        parent_agenda_id = agenda.get("parent_agenda_id")
        parent_item_id = agenda.get("parent_item_id")
        if parent_agenda_id and parent_item_id:
            parent = tracker["agendas"][parent_agenda_id]
            parent["current_item_id"] = parent_item_id
            set_item_status(find_item(parent, parent_item_id), "child_done")
            continue
        tracker["status"] = "closed"
        break

    result = save_tracker(tracker, storage)
    return {**result, "current_path": current_path(cwd, thread_id, global_state_root)}


def push_child(
    cwd: str | Path,
    thread_id: str,
    parent_item_id: str,
    title: str,
    items: list[str],
    global_state_root: str | Path | None = None,
) -> dict[str, Any]:
    if not items:
        raise ValueError("Child agenda requires at least one item")
    tracker, storage = load_tracker(cwd, thread_id, global_state_root)
    parent_agenda_id = tracker["active_stack"][-1]
    parent_agenda = tracker["agendas"][parent_agenda_id]
    parent_item = find_item(parent_agenda, parent_item_id)
    child_id_base = f"agenda-{slug(parent_item_id)}-child"
    child_id = child_id_base
    suffix = 2
    while child_id in tracker["agendas"]:
        child_id = f"{child_id_base}-{suffix}"
        suffix += 1

    child_items = make_items(items)
    set_item_status(child_items[0], "discussing")
    tracker["agendas"][child_id] = {
        "id": child_id,
        "title": title,
        "parent_agenda_id": parent_agenda_id,
        "parent_item_id": parent_item_id,
        "source_ref": "",
        "source_excerpt": "",
        "status": "active",
        "current_item_id": child_items[0]["id"],
        "items": child_items,
    }
    parent_agenda["current_item_id"] = parent_item_id
    parent_item["child_agenda_ids"].append(child_id)
    set_item_status(parent_item, "child_agenda_active")
    tracker["active_stack"].append(child_id)
    result = save_tracker(tracker, storage)
    append_event(storage, {"type": "push_child", "parent_item_id": parent_item_id, "agenda_id": child_id})
    return {**result, "current_path": current_path(cwd, thread_id, global_state_root)}


def render_context(
    cwd: str | Path,
    thread_id: str,
    global_state_root: str | Path | None = None,
) -> str:
    tracker, storage = load_tracker(cwd, thread_id, global_state_root)
    if tracker.get("status") != "active" or not tracker.get("active_stack"):
        return ""
    path = " > ".join(current_path(cwd, thread_id, global_state_root)) or "(none)"
    return "\n".join([
        "[Anchor]",
        f"Anchor project root: {tracker.get('project_root') or storage.project_root}",
        f"State source: {tracker.get('state_source') or storage.state_source}",
        f"Current: {path}",
        "Rule: continue deepest unfinished item; return to parent after child agenda closes.",
        f"Tracker: {storage.tracker_path}",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Anchor tracker helper")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-project")
    p.add_argument("root")
    p.add_argument("--name")

    p = sub.add_parser("init")
    p.add_argument("--cwd", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--item", action="append", required=True)
    p.add_argument("--global-state-root")

    p = sub.add_parser("next")
    p.add_argument("--cwd", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--global-state-root")

    p = sub.add_parser("complete")
    p.add_argument("--cwd", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--conclusion", default="")
    p.add_argument("--global-state-root")

    p = sub.add_parser("push-child")
    p.add_argument("--cwd", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--parent-item-id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--item", action="append", required=True)
    p.add_argument("--global-state-root")

    p = sub.add_parser("render-context")
    p.add_argument("--cwd", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--global-state-root")

    args = parser.parse_args(argv)

    try:
        if args.command == "init-project":
            result = init_project(args.root, args.name)
        elif args.command == "init":
            result = init_tracker(args.cwd, args.thread_id, args.title, args.item, args.global_state_root)
        elif args.command == "next":
            result = next_item(args.cwd, args.thread_id, args.global_state_root)
        elif args.command == "complete":
            result = complete_current(args.cwd, args.thread_id, args.global_state_root, args.conclusion)
        elif args.command == "push-child":
            result = push_child(args.cwd, args.thread_id, args.parent_item_id, args.title, args.item, args.global_state_root)
        elif args.command == "render-context":
            print(render_context(args.cwd, args.thread_id, args.global_state_root))
            return 0
        else:
            parser.error(f"unknown command: {args.command}")
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(f"anchor: error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
