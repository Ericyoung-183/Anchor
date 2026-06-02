#!/usr/bin/env python3
"""Deterministic tracker helper for Anchor."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VERSION = 1
BROAD_ROOT_NAMES = {"/", str(Path.home()), str(Path.home() / "Desktop")}
VALID_TRACKER_STATUSES = {"active", "paused", "closed", "abandoned"}
VALID_AGENDA_STATUSES = {"active", "paused", "closed", "abandoned"}
VALID_ITEM_STATUSES = {
    "pending",
    "discussing",
    "child_agenda_active",
    "child_done",
    "decided",
    "actioned",
    "deferred",
    "blocked",
}
UNRESOLVED_ITEM_STATUSES = {"pending", "discussing", "child_agenda_active", "deferred", "blocked"}
DONE_ITEM_STATUSES = {"actioned", "decided", "child_done"}
ADVANCE_BLOCKING_ITEM_STATUSES = {"discussing", "child_agenda_active"}
TODO_HIGH_CONFIDENCE_NAMES = {"todo.md", "todos.md", "task.md", "tasks.md"}
TODO_SKIP_DIRS = {".git", ".anchor", ".github", "__pycache__", "node_modules", "build", "dist", ".venv", "venv"}
TODO_CHECKBOX_RE = re.compile(r"^(\s*[-*]\s+\[)([ xX])(\]\s+)(.*\S)(\s*)$")


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


def env_value(name: str) -> str:
    return os.environ.get(name, "").strip().lower()


def force_global_state() -> bool:
    return env_value("ANCHOR_STATE_MODE") == "global"


def auto_project_enabled() -> bool:
    return env_value("ANCHOR_AUTO_ENABLE_PROJECT") not in {"0", "false", "no", "off", "disabled"}


def project_storage(project_root: Path, thread_id: str) -> Storage:
    tracker_dir = project_root / ".anchor" / "state" / thread_id
    return Storage(
        project_root=project_root,
        state_source="project-local",
        tracker_dir=tracker_dir,
        tracker_path=tracker_dir / "active.json",
        events_path=tracker_dir / "events.jsonl",
    )


def global_storage(project_root: Path, thread_id: str, global_root: Path) -> Storage:
    tracker_dir = global_root / project_key(project_root) / thread_id
    return Storage(
        project_root=project_root,
        state_source="global-fallback",
        tracker_dir=tracker_dir,
        tracker_path=tracker_dir / "active.json",
        events_path=tracker_dir / "events.jsonl",
    )


def valid_project_root(project_root: Path) -> bool:
    return project_root.is_dir() and not is_broad_root(project_root)


def tracker_exists(storage: Storage) -> bool:
    return storage.tracker_path.is_file()


def can_auto_enable_project(project_root: Path) -> bool:
    return (
        auto_project_enabled()
        and valid_project_root(project_root)
        and (project_root / ".git").exists()
        and os.access(project_root, os.W_OK)
    )


def git_info_exclude_path(project_root: Path) -> Path | None:
    if not (project_root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--git-path", "info/exclude"],
            capture_output=True,
            check=True,
            text=True,
        )
        value = result.stdout.strip()
        if value:
            path = Path(value)
            return path if path.is_absolute() else (project_root / path).resolve()
    except (OSError, subprocess.CalledProcessError):
        pass
    dot_git = project_root / ".git"
    if dot_git.is_dir():
        return dot_git / "info" / "exclude"
    return None


def resolve_storage(
    cwd: str | Path,
    thread_id: str,
    global_state_root: str | Path | None = None,
    allow_auto_project: bool = False,
) -> Storage:
    cwd_path = Path(cwd).resolve()
    explicit_root = os.environ.get("ANCHOR_PROJECT_ROOT", "").strip()
    global_root = Path(global_state_root).expanduser() if global_state_root else default_global_state_root()

    git_root = find_git_root(cwd_path)
    fallback_project_root = git_root if git_root and not is_broad_root(git_root) else cwd_path
    fallback = global_storage(fallback_project_root, thread_id, global_root)
    if force_global_state():
        return fallback

    candidates: list[Path] = []
    if explicit_root:
        candidates.append(Path(explicit_root).expanduser().resolve())
    enabled = find_enabled_root(cwd_path)
    if enabled:
        candidates.append(enabled)

    for candidate in candidates:
        if (candidate / ".anchor" / "config.json").is_file() and valid_project_root(candidate):
            storage = project_storage(candidate, thread_id)
            if tracker_exists(storage):
                return storage

    if tracker_exists(fallback):
        return fallback

    for candidate in candidates:
        if (candidate / ".anchor" / "config.json").is_file() and valid_project_root(candidate):
            return project_storage(candidate, thread_id)

    if allow_auto_project and git_root and can_auto_enable_project(git_root):
        try:
            init_project(git_root)
            return project_storage(git_root, thread_id)
        except OSError:
            return fallback

    return fallback


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


@contextlib.contextmanager
def storage_lock(storage: Storage):
    storage.tracker_dir.mkdir(parents=True, exist_ok=True)
    lock_path = storage.tracker_dir / ".lock"
    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def append_event(storage: Storage, event: dict[str, Any]) -> None:
    storage.events_path.parent.mkdir(parents=True, exist_ok=True)
    event = {"at": now_iso(), **event}
    with storage.events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_tracker(storage: Storage) -> dict[str, Any]:
    if not storage.tracker_path.is_file():
        raise FileNotFoundError(f"Anchor tracker not found: {storage.tracker_path}")
    return json.loads(storage.tracker_path.read_text(encoding="utf-8"))


def load_tracker(cwd: str | Path, thread_id: str, global_state_root: str | Path | None = None) -> tuple[dict[str, Any], Storage]:
    storage = resolve_storage(cwd, thread_id, global_state_root)
    return read_tracker(storage), storage


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

    git_exclude = git_info_exclude_path(project_root)
    if git_exclude:
        git_exclude.parent.mkdir(parents=True, exist_ok=True)
        text = git_exclude.read_text(encoding="utf-8") if git_exclude.exists() else ""
        additions = [pattern for pattern in [".anchor/config.json", ".anchor/state/"] if pattern not in text]
        if additions:
            suffix = "" if text.endswith("\n") or not text else "\n"
            git_exclude.write_text(f"{text}{suffix}" + "\n".join(additions) + "\n", encoding="utf-8")

    return {
        "project_root": str(project_root),
        "config_path": str(config_path),
        "state_dir": str(state_dir),
    }


def read_project_config(config_path: Path) -> dict[str, Any]:
    if not config_path.is_file():
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))


def write_project_config(config_path: Path, config: dict[str, Any]) -> None:
    write_json(config_path, config)


def ensure_todo_project(cwd: str | Path) -> tuple[Path, Path, dict[str, Any]]:
    cwd_path = Path(cwd).resolve()
    enabled_root = find_enabled_root(cwd_path)
    if enabled_root:
        project_root = enabled_root
    else:
        git_root = find_git_root(cwd_path)
        if not git_root or not can_auto_enable_project(git_root):
            raise ValueError("Anchor TODO requires a safe Git project or existing .anchor/config.json")
        init_project(git_root)
        project_root = git_root

    config_path = project_root / ".anchor" / "config.json"
    if not config_path.is_file():
        init_project(project_root)
    return project_root, config_path, read_project_config(config_path)


def normalize_project_relpath(project_root: Path, path_value: str | Path) -> str:
    raw = Path(path_value).expanduser()
    path = raw if raw.is_absolute() else project_root / raw
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(project_root)
    except ValueError as exc:
        raise ValueError(f"TODO path must stay inside project root: {path_value}") from exc
    if rel.suffix.lower() != ".md":
        raise ValueError(f"TODO path must be a Markdown file: {path_value}")
    return rel.as_posix()


def parse_todo_file(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    items: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = TODO_CHECKBOX_RE.match(line)
        if not match:
            continue
        checked = match.group(2).lower() == "x"
        items.append({
            "line": line_no,
            "text": match.group(4).strip(),
            "checked": checked,
        })
    return items


def is_skipped_todo_path(path: Path, project_root: Path) -> bool:
    try:
        parts = path.relative_to(project_root).parts
    except ValueError:
        return True
    return any(part in TODO_SKIP_DIRS for part in parts)


def todo_candidate_confidence(path: Path) -> str:
    name = path.name.lower()
    if name in TODO_HIGH_CONFIDENCE_NAMES:
        return "high"
    return "low"


def discover_todo_candidates(project_root: Path) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for path in project_root.rglob("*.md"):
        if is_skipped_todo_path(path, project_root):
            continue
        name = path.name.lower()
        parsed = parse_todo_file(path)
        confidence = todo_candidate_confidence(path)
        include = confidence == "high"
        if not include and ("todo" in name or "task" in name):
            include = bool(parsed)
        if not include and name == "agents.md" and parsed:
            try:
                include = "todo" in path.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                include = False
        if not include:
            continue
        rel = path.relative_to(project_root).as_posix()
        candidates[rel] = {
            "path": rel,
            "confidence": confidence,
            "open_count": sum(1 for item in parsed if not item["checked"]),
            "total_count": len(parsed),
        }
    return [candidates[key] for key in sorted(candidates)]


def configured_todo_status(project_root: Path, config_path: Path, config: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    todo_config = config.get("todo") if isinstance(config.get("todo"), dict) else {}
    canonical_relpath = str(todo_config.get("canonical_path", "")).strip()
    try:
        normalized_relpath = normalize_project_relpath(project_root, canonical_relpath) if canonical_relpath else ""
    except ValueError as exc:
        return {
            "status": "invalid_canonical",
            "project_root": str(project_root),
            "config_path": str(config_path),
            "canonical_path": "",
            "canonical_relpath": canonical_relpath,
            "candidates": candidates,
            "open_count": 0,
            "open_items": [],
            "error": str(exc),
        }
    canonical_relpath = normalized_relpath
    canonical_path = project_root / canonical_relpath if canonical_relpath else None
    if canonical_relpath and (not canonical_path or not canonical_path.is_file()):
        return {
            "status": "missing_canonical",
            "project_root": str(project_root),
            "config_path": str(config_path),
            "canonical_path": str(canonical_path) if canonical_path else "",
            "canonical_relpath": canonical_relpath,
            "candidates": candidates,
            "open_count": 0,
            "open_items": [],
            "error": f"Canonical TODO file is missing: {canonical_relpath}",
        }
    parsed = parse_todo_file(canonical_path) if canonical_path else []
    open_items = [
        {
            "path": canonical_relpath,
            "line": item["line"],
            "text": item["text"],
        }
        for item in parsed
        if not item["checked"]
    ]
    return {
        "status": "configured",
        "project_root": str(project_root),
        "config_path": str(config_path),
        "canonical_path": str(canonical_path) if canonical_path else "",
        "canonical_relpath": canonical_relpath,
        "candidates": candidates,
        "open_count": len(open_items),
        "open_items": open_items,
    }


def todo_status(cwd: str | Path) -> dict[str, Any]:
    project_root, config_path, config = ensure_todo_project(cwd)
    candidates = discover_todo_candidates(project_root)
    todo_config = config.get("todo") if isinstance(config.get("todo"), dict) else {}
    canonical_relpath = str(todo_config.get("canonical_path", "")).strip()
    if canonical_relpath:
        return configured_todo_status(project_root, config_path, config, candidates)

    high_candidates = [candidate for candidate in candidates if candidate["confidence"] == "high"]
    if len(candidates) == 1 and len(high_candidates) == 1:
        config["todo"] = {
            "canonical_path": candidates[0]["path"],
            "legacy_sources": [],
            "policy": "canonical-only",
        }
        write_project_config(config_path, config)
        return configured_todo_status(project_root, config_path, config, candidates)

    if not candidates:
        return {
            "status": "unconfigured",
            "project_root": str(project_root),
            "config_path": str(config_path),
            "canonical_path": "",
            "canonical_relpath": "",
            "candidates": [],
            "open_count": 0,
            "open_items": [],
        }

    return {
        "status": "needs_selection",
        "project_root": str(project_root),
        "config_path": str(config_path),
        "canonical_path": "",
        "canonical_relpath": "",
        "candidates": candidates,
        "open_count": sum(candidate["open_count"] for candidate in candidates),
        "open_items": [],
    }


def todo_configure(cwd: str | Path, todo_path: str | Path, create: bool = False) -> dict[str, Any]:
    project_root, config_path, config = ensure_todo_project(cwd)
    relpath = normalize_project_relpath(project_root, todo_path)
    path = project_root / relpath
    if create and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# TODO\n\n", encoding="utf-8")
    if not path.is_file():
        raise FileNotFoundError(f"TODO file not found: {path}")
    candidates = discover_todo_candidates(project_root)
    legacy_sources = [candidate["path"] for candidate in candidates if candidate["path"] != relpath]
    config["todo"] = {
        "canonical_path": relpath,
        "legacy_sources": legacy_sources,
        "policy": "canonical-only",
    }
    write_project_config(config_path, config)
    return configured_todo_status(project_root, config_path, config, discover_todo_candidates(project_root))


def ensure_configured_todo_for_write(cwd: str | Path) -> dict[str, Any]:
    status = todo_status(cwd)
    if status["status"] == "unconfigured":
        return todo_configure(cwd, "TODO.md", create=True)
    if status["status"] == "needs_selection":
        raise ValueError("Multiple TODO candidates found; run todo-configure before writing TODO items")
    if status["status"] == "missing_canonical":
        raise ValueError("Canonical TODO file is missing; run todo-configure before writing TODO items")
    if status["status"] == "invalid_canonical":
        raise ValueError(status.get("error") or "Configured canonical TODO path is invalid")
    return status


def todo_add(cwd: str | Path, text: str) -> dict[str, Any]:
    item_text = " ".join(text.split())
    if not item_text:
        raise ValueError("TODO text is required")
    status = ensure_configured_todo_for_write(cwd)
    todo_path = Path(status["canonical_path"])
    existing = todo_path.read_text(encoding="utf-8") if todo_path.exists() else "# TODO\n\n"
    prefix = "" if existing.endswith("\n") or not existing else "\n"
    todo_path.write_text(f"{existing}{prefix}- [ ] {item_text}\n", encoding="utf-8")
    return todo_status(status["project_root"])


def todo_start(
    cwd: str | Path,
    thread_id: str,
    global_state_root: str | Path | None = None,
    title: str = "Project TODO",
) -> dict[str, Any]:
    status = todo_status(cwd)
    if status["status"] in {"needs_selection", "missing_canonical", "invalid_canonical"}:
        return status
    if status["status"] == "unconfigured" or status["open_count"] == 0:
        return {**status, "status": "empty"}
    items = [item["text"] for item in status["open_items"]]
    source_excerpt = "\n".join(f"- [ ] {item}" for item in items[:10])
    result = init_tracker(
        cwd=status["project_root"],
        thread_id=thread_id,
        title=title,
        items=items,
        global_state_root=global_state_root,
        source_ref=f"todo:{status['canonical_relpath']}",
        source_excerpt=source_excerpt,
    )
    return {
        **result,
        "status": "started",
        "todo_path": status["canonical_path"],
        "todo_relpath": status["canonical_relpath"],
        "todo_open_count": status["open_count"],
    }


def mark_done_lines(todo_path: Path, done_texts: list[str]) -> int:
    remaining: dict[str, int] = {}
    for text in done_texts:
        remaining[text] = remaining.get(text, 0) + 1
    lines = todo_path.read_text(encoding="utf-8").splitlines()
    completed = 0
    new_lines: list[str] = []
    for line in lines:
        match = TODO_CHECKBOX_RE.match(line)
        if not match:
            new_lines.append(line)
            continue
        text = match.group(4).strip()
        checked = match.group(2).lower() == "x"
        if not checked and remaining.get(text, 0) > 0:
            remaining[text] -= 1
            completed += 1
            new_lines.append(f"{match.group(1)}x{match.group(3)}{match.group(4)}{match.group(5)}")
        else:
            new_lines.append(line)
    trailing = "\n" if todo_path.read_text(encoding="utf-8").endswith("\n") else ""
    todo_path.write_text("\n".join(new_lines) + trailing, encoding="utf-8")
    return completed


def todo_sync(cwd: str | Path, thread_id: str, global_state_root: str | Path | None = None) -> dict[str, Any]:
    tracker, _ = load_tracker(cwd, thread_id, global_state_root)
    tracker_status = tracker.get("status")
    if tracker_status not in {"closed", "paused"}:
        raise ValueError(f"TODO sync requires a closed or paused tracker, got: {tracker_status}")
    root_agenda = tracker.get("agendas", {}).get("agenda-root")
    if not root_agenda:
        raise ValueError("TODO sync requires a root agenda")
    source_ref = str(root_agenda.get("source_ref", ""))
    if not source_ref.startswith("todo:"):
        raise ValueError("TODO sync requires a todo-backed agenda")

    status = todo_status(cwd)
    if status["status"] != "configured":
        raise ValueError("TODO sync requires a configured canonical TODO")
    source_relpath = source_ref.removeprefix("todo:")
    if source_relpath != status["canonical_relpath"]:
        raise ValueError(f"TODO source mismatch: tracker={source_relpath} canonical={status['canonical_relpath']}")

    done_texts = [
        item.get("text", "")
        for item in root_agenda.get("items", [])
        if item.get("status") in DONE_ITEM_STATUSES
    ]
    completed = mark_done_lines(Path(status["canonical_path"]), done_texts)
    refreshed = todo_status(cwd)
    return {
        "status": "synced",
        "project_root": status["project_root"],
        "todo_path": status["canonical_path"],
        "todo_relpath": status["canonical_relpath"],
        "tracker_status": tracker.get("status"),
        "completed_count": completed,
        "remaining_open_count": refreshed["open_count"],
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


def ensure_tracker_active(tracker: dict[str, Any]) -> None:
    status = tracker.get("status")
    if status != "active":
        raise ValueError(f"Anchor tracker is not active: {status}")


def derive_current_path(tracker: dict[str, Any]) -> list[str]:
    path = []
    for agenda_id in tracker.get("active_stack", []):
        agenda = tracker.get("agendas", {}).get(agenda_id)
        if not agenda:
            continue
        current = agenda.get("current_item_id")
        if current:
            path.append(current)
    return path


def derive_current_display_path(tracker: dict[str, Any]) -> list[str]:
    path = []
    for agenda_id in tracker.get("active_stack", []):
        agenda = tracker.get("agendas", {}).get(agenda_id)
        if not agenda:
            continue
        current = agenda.get("current_item_id")
        if not current:
            continue
        try:
            item = find_item(agenda, current)
        except KeyError:
            path.append(str(current))
            continue
        path.append(compact_text(item.get("text")) or str(current))
    return path


def current_path(cwd: str | Path, thread_id: str, global_state_root: str | Path | None = None) -> list[str]:
    tracker, _ = load_tracker(cwd, thread_id, global_state_root)
    return derive_current_path(tracker)


def iter_items(tracker: dict[str, Any]):
    for agenda in tracker.get("agendas", {}).values():
        for item in agenda.get("items", []):
            yield agenda, item


def unresolved_counts(tracker: dict[str, Any]) -> dict[str, int]:
    counts = {"pending": 0, "discussing": 0, "child_agenda_active": 0, "deferred": 0, "blocked": 0}
    for _, item in iter_items(tracker):
        status = item.get("status")
        if status in counts:
            counts[status] += 1
    return counts


def current_item_snapshot(tracker: dict[str, Any]) -> dict[str, Any] | None:
    stack = tracker.get("active_stack") or []
    if not stack:
        return None
    agenda = tracker.get("agendas", {}).get(stack[-1])
    if not agenda:
        return None
    item_id = agenda.get("current_item_id")
    if not item_id:
        return None
    try:
        item = find_item(agenda, item_id)
    except KeyError:
        return None
    return {
        "agenda_id": agenda.get("id"),
        "item_id": item.get("id"),
        "text": item.get("text"),
        "status": item.get("status"),
        "conclusion": item.get("conclusion", ""),
    }


def status_report(cwd: str | Path, thread_id: str, global_state_root: str | Path | None = None) -> dict[str, Any]:
    tracker, storage = load_tracker(cwd, thread_id, global_state_root)
    return {
        "tracker_path": str(storage.tracker_path),
        "state_source": storage.state_source,
        "project_root": str(storage.project_root),
        "tracker_status": tracker.get("status"),
        "current_path": derive_current_path(tracker),
        "current_item": current_item_snapshot(tracker),
        "unresolved_counts": unresolved_counts(tracker),
        "updated_at": tracker.get("updated_at"),
    }


def compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def unresolved_item_records(tracker: dict[str, Any]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for agenda_id, agenda in tracker.get("agendas", {}).items():
        source_ref = compact_text(agenda.get("source_ref"))
        for item in agenda.get("items", []):
            status = item.get("status")
            if status not in UNRESOLVED_ITEM_STATUSES:
                continue
            records.append({
                "agenda_id": agenda_id,
                "agenda_title": compact_text(agenda.get("title")),
                "item_id": compact_text(item.get("id")),
                "text": compact_text(item.get("text")),
                "status": compact_text(status),
                "conclusion": compact_text(item.get("conclusion")),
                "source_ref": source_ref,
            })
    return records


def export_unresolved(
    cwd: str | Path,
    thread_id: str,
    global_state_root: str | Path | None = None,
) -> str:
    tracker, storage = load_tracker(cwd, thread_id, global_state_root)
    current = " > ".join(derive_current_path(tracker)) or "(none)"
    records = unresolved_item_records(tracker)
    lines = [
        "# Anchor Unresolved Items",
        "",
        f"- Project: {tracker.get('project_root') or storage.project_root}",
        f"- Tracker status: {tracker.get('status')}",
        f"- Current path: {current}",
        f"- Tracker: {storage.tracker_path}",
        "- Memory: not written by this command; review and save explicitly if needed.",
        "",
        "## Items",
        "",
    ]
    if not records:
        lines.append("- None")
    for record in records:
        lines.append(
            "- [ ] [{status}] {agenda_id}/{item_id}: {text}".format(**record)
        )
        if record["agenda_title"]:
            lines.append(f"  - Agenda: {record['agenda_title']}")
        if record["conclusion"]:
            lines.append(f"  - Note: {record['conclusion']}")
        if record["source_ref"]:
            lines.append(f"  - Source: {record['source_ref']}")
    return "\n".join(lines).rstrip() + "\n"


def minutes_since(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    delta = dt.datetime.now(dt.timezone.utc) - parsed.astimezone(dt.timezone.utc)
    return max(0, int(delta.total_seconds() // 60))


def cap_context(text: str, max_context_chars: int | None) -> str:
    if not max_context_chars or max_context_chars <= 0 or len(text) <= max_context_chars:
        return text
    if max_context_chars <= 3:
        return "." * max_context_chars
    return text[: max_context_chars - 3].rstrip() + "..."


def validate_tracker(cwd: str | Path, thread_id: str, global_state_root: str | Path | None = None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    storage = resolve_storage(cwd, thread_id, global_state_root)
    try:
        tracker = read_tracker(storage)
    except FileNotFoundError as exc:
        return {
            "valid": False,
            "errors": [str(exc)],
            "warnings": [],
            "tracker_path": str(storage.tracker_path),
        }

    if tracker.get("version") != VERSION:
        errors.append(f"unsupported version: {tracker.get('version')}")
    if tracker.get("status") not in VALID_TRACKER_STATUSES:
        errors.append(f"invalid tracker status: {tracker.get('status')}")

    agendas = tracker.get("agendas")
    if not isinstance(agendas, dict):
        errors.append("agendas must be an object")
        agendas = {}

    active_stack = tracker.get("active_stack")
    if not isinstance(active_stack, list):
        errors.append("active_stack must be a list")
        active_stack = []

    if tracker.get("status") == "active" and not active_stack:
        errors.append("active tracker must have a non-empty active_stack")
    if tracker.get("status") in {"closed", "abandoned"} and active_stack:
        warnings.append("closed or abandoned tracker still has active_stack entries")

    for agenda_id in active_stack:
        if agenda_id not in agendas:
            errors.append(f"active_stack references missing agenda: {agenda_id}")

    for agenda_id, agenda in agendas.items():
        if agenda.get("id") != agenda_id:
            errors.append(f"agenda key/id mismatch: {agenda_id}")
        if agenda.get("status") not in VALID_AGENDA_STATUSES:
            errors.append(f"invalid agenda status for {agenda_id}: {agenda.get('status')}")
        items = agenda.get("items")
        if not isinstance(items, list):
            errors.append(f"agenda {agenda_id} items must be a list")
            items = []
        item_ids = {item.get("id") for item in items}
        current_item_id = agenda.get("current_item_id")
        if current_item_id and current_item_id not in item_ids:
            errors.append(f"agenda {agenda_id} current_item_id missing item: {current_item_id}")
        for item in items:
            item_id = item.get("id")
            if item.get("status") not in VALID_ITEM_STATUSES:
                errors.append(f"invalid item status for {agenda_id}/{item_id}: {item.get('status')}")
            for child_id in item.get("child_agenda_ids", []):
                if child_id not in agendas:
                    errors.append(f"item {agenda_id}/{item_id} references missing child agenda: {child_id}")

        parent_agenda_id = agenda.get("parent_agenda_id")
        parent_item_id = agenda.get("parent_item_id")
        if parent_agenda_id or parent_item_id:
            if parent_agenda_id not in agendas:
                errors.append(f"agenda {agenda_id} references missing parent agenda: {parent_agenda_id}")
            else:
                parent_items = agendas[parent_agenda_id].get("items", [])
                if parent_item_id not in {item.get("id") for item in parent_items}:
                    errors.append(f"agenda {agenda_id} references missing parent item: {parent_item_id}")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "tracker_path": str(storage.tracker_path),
        "state_source": storage.state_source,
        "project_root": str(storage.project_root),
    }


def init_tracker(
    cwd: str | Path,
    thread_id: str,
    title: str,
    items: list[str],
    global_state_root: str | Path | None = None,
    source_ref: str = "",
    source_excerpt: str = "",
) -> dict[str, Any]:
    if not items:
        raise ValueError("Anchor tracker requires at least one item")
    storage = resolve_storage(cwd, thread_id, global_state_root, allow_auto_project=True)
    with storage_lock(storage):
        if tracker_exists(storage):
            existing = read_tracker(storage)
            if existing.get("status") not in {"closed", "abandoned"}:
                raise ValueError(f"Anchor tracker already exists and is not closed: {existing.get('status')}")
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
                    "source_ref": source_ref,
                    "source_excerpt": source_excerpt,
                    "status": "active",
                    "current_item_id": agenda_items[0]["id"],
                    "items": agenda_items,
                }
            },
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        result = save_tracker(tracker, storage)
        append_event(storage, {"type": "init_tracker", "title": title, "items": items, "source_ref": source_ref})
    return {**result, "current_path": current_path(cwd, thread_id, global_state_root)}


def complete_current(
    cwd: str | Path,
    thread_id: str,
    global_state_root: str | Path | None = None,
    conclusion: str = "",
    status: str = "actioned",
) -> dict[str, Any]:
    storage = resolve_storage(cwd, thread_id, global_state_root)
    with storage_lock(storage):
        tracker = read_tracker(storage)
        ensure_tracker_active(tracker)
        agenda = tracker["agendas"][tracker["active_stack"][-1]]
        item = find_item(agenda, agenda["current_item_id"])
        set_item_status(item, status, conclusion)
        result = save_tracker(tracker, storage)
        append_event(storage, {"type": "complete_current", "item_id": item["id"], "status": status})
    return {**result, "current_path": current_path(cwd, thread_id, global_state_root)}


def defer_current(
    cwd: str | Path,
    thread_id: str,
    global_state_root: str | Path | None = None,
    reason: str = "",
) -> dict[str, Any]:
    return complete_current(cwd, thread_id, global_state_root, reason, status="deferred")


def block_current(
    cwd: str | Path,
    thread_id: str,
    global_state_root: str | Path | None = None,
    reason: str = "",
) -> dict[str, Any]:
    return complete_current(cwd, thread_id, global_state_root, reason, status="blocked")


def pause_tracker(
    cwd: str | Path,
    thread_id: str,
    global_state_root: str | Path | None = None,
    reason: str = "",
) -> dict[str, Any]:
    storage = resolve_storage(cwd, thread_id, global_state_root)
    with storage_lock(storage):
        tracker = read_tracker(storage)
        ensure_tracker_active(tracker)
        tracker["status"] = "paused"
        if tracker.get("active_stack"):
            tracker["agendas"][tracker["active_stack"][-1]]["status"] = "paused"
        result = save_tracker(tracker, storage)
        append_event(storage, {"type": "pause_tracker", "reason": reason})
    return {**result, "current_path": current_path(cwd, thread_id, global_state_root)}


def resume_tracker(
    cwd: str | Path,
    thread_id: str,
    global_state_root: str | Path | None = None,
) -> dict[str, Any]:
    storage = resolve_storage(cwd, thread_id, global_state_root)
    with storage_lock(storage):
        tracker = read_tracker(storage)
        if tracker.get("status") != "paused":
            raise ValueError(f"Anchor tracker is not paused: {tracker.get('status')}")
        tracker["status"] = "active"
        for agenda_id in tracker.get("active_stack", []):
            agenda = tracker["agendas"][agenda_id]
            if agenda.get("status") == "paused":
                agenda["status"] = "active"
        result = save_tracker(tracker, storage)
        append_event(storage, {"type": "resume_tracker"})
    return {**result, "current_path": current_path(cwd, thread_id, global_state_root)}


def abandon_tracker(
    cwd: str | Path,
    thread_id: str,
    global_state_root: str | Path | None = None,
    reason: str = "",
) -> dict[str, Any]:
    storage = resolve_storage(cwd, thread_id, global_state_root)
    with storage_lock(storage):
        tracker = read_tracker(storage)
        tracker["status"] = "abandoned"
        for agenda in tracker.get("agendas", {}).values():
            if agenda.get("status") in {"active", "paused"}:
                agenda["status"] = "abandoned"
        tracker["active_stack"] = []
        result = save_tracker(tracker, storage)
        append_event(storage, {"type": "abandon_tracker", "reason": reason})
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


def ensure_current_item_can_advance(agenda: dict[str, Any]) -> None:
    current_id = agenda.get("current_item_id")
    if not current_id:
        return
    current = find_item(agenda, current_id)
    status = current.get("status")
    if status in ADVANCE_BLOCKING_ITEM_STATUSES:
        raise ValueError(f"Current item must be completed, deferred, or blocked before moving next: {current_id}")


def parent_status_for_closed_child(agenda: dict[str, Any]) -> tuple[str, str]:
    unresolved = [item for item in agenda.get("items", []) if item.get("status") in UNRESOLVED_ITEM_STATUSES]
    if not unresolved:
        return "child_done", ""
    statuses = {str(item.get("status")) for item in unresolved}
    summary = ", ".join(f"{status}={sum(1 for item in unresolved if item.get('status') == status)}" for status in sorted(statuses))
    if statuses == {"deferred"}:
        return "deferred", f"Child agenda closed with unresolved child items: {summary}"
    return "blocked", f"Child agenda closed with unresolved child items: {summary}"


def next_item(
    cwd: str | Path,
    thread_id: str,
    global_state_root: str | Path | None = None,
) -> dict[str, Any]:
    storage = resolve_storage(cwd, thread_id, global_state_root)
    with storage_lock(storage):
        tracker = read_tracker(storage)
        ensure_tracker_active(tracker)
        while tracker["active_stack"]:
            agenda_id = tracker["active_stack"][-1]
            agenda = tracker["agendas"][agenda_id]
            ensure_current_item_can_advance(agenda)
            next_item_obj = next_pending_after(agenda)
            if next_item_obj:
                set_item_status(next_item_obj, "discussing")
                agenda["current_item_id"] = next_item_obj["id"]
                result = save_tracker(tracker, storage)
                append_event(storage, {"type": "next_item", "item_id": next_item_obj["id"]})
                return {**result, "current_path": derive_current_path(tracker)}

            agenda["status"] = "closed"
            tracker["active_stack"].pop()
            append_event(storage, {"type": "close_agenda", "agenda_id": agenda_id})
            parent_agenda_id = agenda.get("parent_agenda_id")
            parent_item_id = agenda.get("parent_item_id")
            if parent_agenda_id and parent_item_id:
                parent = tracker["agendas"][parent_agenda_id]
                parent["current_item_id"] = parent_item_id
                parent_status, parent_conclusion = parent_status_for_closed_child(agenda)
                set_item_status(find_item(parent, parent_item_id), parent_status, parent_conclusion)
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
    source_ref: str = "",
    source_excerpt: str = "",
) -> dict[str, Any]:
    if not items:
        raise ValueError("Child agenda requires at least one item")
    storage = resolve_storage(cwd, thread_id, global_state_root)
    with storage_lock(storage):
        tracker = read_tracker(storage)
        ensure_tracker_active(tracker)
        parent_agenda_id = tracker["active_stack"][-1]
        parent_agenda = tracker["agendas"][parent_agenda_id]
        current_item_id = parent_agenda.get("current_item_id")
        if parent_item_id != current_item_id:
            raise ValueError(f"Child agenda can only be pushed under the current item: {current_item_id}")
        parent_item = find_item(parent_agenda, parent_item_id)
        if parent_item.get("status") != "discussing":
            raise ValueError(f"Child agenda requires the current item to be discussing: {parent_item_id}")
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
            "source_ref": source_ref,
            "source_excerpt": source_excerpt,
            "status": "active",
            "current_item_id": child_items[0]["id"],
            "items": child_items,
        }
        parent_agenda["current_item_id"] = parent_item_id
        parent_item["child_agenda_ids"].append(child_id)
        set_item_status(parent_item, "child_agenda_active")
        tracker["active_stack"].append(child_id)
        result = save_tracker(tracker, storage)
        append_event(storage, {"type": "push_child", "parent_item_id": parent_item_id, "agenda_id": child_id, "source_ref": source_ref})
    return {**result, "current_path": current_path(cwd, thread_id, global_state_root)}


def render_context(
    cwd: str | Path,
    thread_id: str,
    global_state_root: str | Path | None = None,
    max_context_chars: int | None = None,
    stale_after_minutes: int | None = None,
) -> str:
    tracker, storage = load_tracker(cwd, thread_id, global_state_root)
    if tracker.get("status") != "active" or not tracker.get("active_stack"):
        return ""
    path = " > ".join(derive_current_display_path(tracker)) or "(none)"
    lines = [
        "[Anchor]",
        f"Anchor project root: {tracker.get('project_root') or storage.project_root}",
        f"State source: {tracker.get('state_source') or storage.state_source}",
        f"Current: {path}",
        "Rule: continue deepest unfinished item; return to parent after child agenda closes.",
        f"Tracker: {storage.tracker_path}",
    ]
    counts = unresolved_counts(tracker)
    unresolved_bits = []
    for key in ["deferred", "blocked"]:
        if counts.get(key):
            unresolved_bits.append(f"{key}={counts[key]}")
    if unresolved_bits:
        lines.append("Unresolved: " + " ".join(unresolved_bits))
    age = minutes_since(tracker.get("updated_at"))
    if stale_after_minutes is not None and age is not None and age >= stale_after_minutes:
        lines.append(f"Warning: tracker stale for {age} minutes; read tracker before advancing.")
    return cap_context("\n".join(lines), max_context_chars)


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
    p.add_argument("--source-ref", default="")
    p.add_argument("--source-excerpt", default="")
    p.add_argument("--global-state-root")

    p = sub.add_parser("status")
    p.add_argument("--cwd", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--global-state-root")

    p = sub.add_parser("validate")
    p.add_argument("--cwd", required=True)
    p.add_argument("--thread-id", required=True)
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

    p = sub.add_parser("defer")
    p.add_argument("--cwd", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--reason", default="")
    p.add_argument("--global-state-root")

    p = sub.add_parser("block")
    p.add_argument("--cwd", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--reason", default="")
    p.add_argument("--global-state-root")

    p = sub.add_parser("pause")
    p.add_argument("--cwd", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--reason", default="")
    p.add_argument("--global-state-root")

    p = sub.add_parser("resume")
    p.add_argument("--cwd", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--global-state-root")

    p = sub.add_parser("abandon")
    p.add_argument("--cwd", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--reason", default="")
    p.add_argument("--global-state-root")

    p = sub.add_parser("push-child")
    p.add_argument("--cwd", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--parent-item-id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--item", action="append", required=True)
    p.add_argument("--source-ref", default="")
    p.add_argument("--source-excerpt", default="")
    p.add_argument("--global-state-root")

    p = sub.add_parser("render-context")
    p.add_argument("--cwd", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--global-state-root")
    p.add_argument("--max-context-chars", type=int)
    p.add_argument("--stale-after-minutes", type=int)

    p = sub.add_parser("export-unresolved")
    p.add_argument("--cwd", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--global-state-root")

    p = sub.add_parser("todo-status")
    p.add_argument("--cwd", required=True)

    p = sub.add_parser("todo-configure")
    p.add_argument("--cwd", required=True)
    p.add_argument("--path", required=True)
    p.add_argument("--create", action="store_true")

    p = sub.add_parser("todo-add")
    p.add_argument("--cwd", required=True)
    p.add_argument("--text", required=True)

    p = sub.add_parser("todo-start")
    p.add_argument("--cwd", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--title", default="Project TODO")
    p.add_argument("--global-state-root")

    p = sub.add_parser("todo-sync")
    p.add_argument("--cwd", required=True)
    p.add_argument("--thread-id", required=True)
    p.add_argument("--global-state-root")

    args = parser.parse_args(argv)

    try:
        if args.command == "init-project":
            result = init_project(args.root, args.name)
        elif args.command == "init":
            result = init_tracker(args.cwd, args.thread_id, args.title, args.item, args.global_state_root, args.source_ref, args.source_excerpt)
        elif args.command == "status":
            result = status_report(args.cwd, args.thread_id, args.global_state_root)
        elif args.command == "validate":
            result = validate_tracker(args.cwd, args.thread_id, args.global_state_root)
        elif args.command == "next":
            result = next_item(args.cwd, args.thread_id, args.global_state_root)
        elif args.command == "complete":
            result = complete_current(args.cwd, args.thread_id, args.global_state_root, args.conclusion)
        elif args.command == "defer":
            result = defer_current(args.cwd, args.thread_id, args.global_state_root, args.reason)
        elif args.command == "block":
            result = block_current(args.cwd, args.thread_id, args.global_state_root, args.reason)
        elif args.command == "pause":
            result = pause_tracker(args.cwd, args.thread_id, args.global_state_root, args.reason)
        elif args.command == "resume":
            result = resume_tracker(args.cwd, args.thread_id, args.global_state_root)
        elif args.command == "abandon":
            result = abandon_tracker(args.cwd, args.thread_id, args.global_state_root, args.reason)
        elif args.command == "push-child":
            result = push_child(args.cwd, args.thread_id, args.parent_item_id, args.title, args.item, args.global_state_root, args.source_ref, args.source_excerpt)
        elif args.command == "render-context":
            print(render_context(args.cwd, args.thread_id, args.global_state_root, args.max_context_chars, args.stale_after_minutes))
            return 0
        elif args.command == "export-unresolved":
            print(export_unresolved(args.cwd, args.thread_id, args.global_state_root), end="")
            return 0
        elif args.command == "todo-status":
            result = todo_status(args.cwd)
        elif args.command == "todo-configure":
            result = todo_configure(args.cwd, args.path, args.create)
        elif args.command == "todo-add":
            result = todo_add(args.cwd, args.text)
        elif args.command == "todo-start":
            result = todo_start(args.cwd, args.thread_id, args.global_state_root, args.title)
        elif args.command == "todo-sync":
            result = todo_sync(args.cwd, args.thread_id, args.global_state_root)
        else:
            parser.error(f"unknown command: {args.command}")
    except (FileNotFoundError, KeyError, ValueError, OSError) as exc:
        print(f"anchor: error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "validate" and not result.get("valid", False):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
