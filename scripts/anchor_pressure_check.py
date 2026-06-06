#!/usr/bin/env python3
"""Deterministic pressure checks for Anchor transcript drift."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


CATEGORIES = {
    "missed-root-capture": {
        "severity": "HIGH",
        "suggestion": "Freeze the root list with `anchor.py init` before processing the first item.",
    },
    "missed-child-capture": {
        "severity": "HIGH",
        "suggestion": "Push the child list with `anchor.py push-child` before discussing child items.",
    },
    "prose-only-state-change": {
        "severity": "MED",
        "suggestion": "Persist the item transition with `complete`, `defer`, `block`, and `next` before moving on.",
    },
    "wrong-next-target": {
        "severity": "HIGH",
        "suggestion": "Advance the deepest active child item instead of returning to the parent agenda.",
    },
    "stale-tracker-ignored": {
        "severity": "MED",
        "suggestion": "Read or validate the existing tracker before rebuilding context from files.",
    },
    "todo-bridge-bypass": {
        "severity": "HIGH",
        "suggestion": "Use `todo-status` and the canonical TODO Bridge commands before searching or editing TODO files.",
    },
    "recreated-agenda-from-search": {
        "severity": "HIGH",
        "suggestion": "Treat searches as evidence only; do not replace the frozen active Anchor agenda.",
    },
    "missing-whole-picture": {
        "severity": "MED",
        "suggestion": "After `init`, `push-child`, or `interrupt`, show the full agenda Whole Picture with the current item marked.",
    },
}

CHILD_TERMS = ["下面有", "子问题", "子清单", "展开", "拆成", "child"]
DONE_TERMS = ["处理完", "已经处理", "完成了", "已完成", "done"]
ADVANCE_TERMS = ["下一个", "进入下一个", "继续"]
SKIP_OR_BLOCK_TERMS = ["跳过", "先放一放", "阻塞", "blocked", "defer"]
SEARCH_TERMS = ["rg ", "grep ", "find ", "ripgrep", "重新搜", "重新扫", "搜索"]
TRACKER_IGNORE_TERMS = ["不看之前的 tracker", "忽略 tracker", "ignore tracker", "重新扫", "重新搜索"]
WRONG_PARENT_TERMS = ["回到父层", "回 root", "回到 root", "继续 D", "进入 D", "父层继续"]
TODO_TERMS = ["todo", "待办", "[ ]"]
CODEX_NOISE_TERMS = [
    "# AGENTS.md instructions",
    "<INSTRUCTIONS>",
    "</INSTRUCTIONS>",
    "<environment_context>",
    "MEMORY_SUMMARY BEGINS",
    "Overwatch Review #",
    "<!-- Overwatch Review",
    "[Overwatch",
    "DevGate:",
]
ANCHOR_HELPER_OUTPUT_KEYS = {
    "tracker_path",
    "whole_picture",
    "agenda_snapshot",
    "current_path",
    "valid",
    "errors",
    "warnings",
}


def compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def collect_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for item in value.values():
            strings.extend(collect_strings(item))
        return strings
    if isinstance(value, list):
        strings = []
        for item in value:
            strings.extend(collect_strings(item))
        return strings
    return []


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        strings = []
        for item in content:
            if isinstance(item, dict):
                strings.append(str(item.get("text") or item.get("input_text") or ""))
            else:
                strings.append(str(item))
        return " ".join(strings)
    return ""


def is_codex_noise(text: str) -> bool:
    return any(term in text for term in CODEX_NOISE_TERMS)


def strip_codex_injected_prefix(text: str) -> str:
    if "# AGENTS.md instructions" not in text:
        return text
    marker = "</environment_context>"
    if marker not in text:
        return ""
    return text.rsplit(marker, 1)[1].strip()


def extract_codex_function_output(output: str) -> str:
    body = str(output or "").strip()
    if "Output:" in body:
        body = body.rsplit("Output:", 1)[1].strip()
    if not body:
        return ""
    if ("usage: anchor.py" in body or "anchor.py" in body) and "error:" in body:
        return json.dumps({"anchor_command_error": True}, ensure_ascii=False)
    if body.startswith("[Anchor") or body.startswith("Warning: tracker stale"):
        return body

    candidates = [body]
    if "{" in body and "}" in body:
        candidates.append(body[body.find("{"):body.rfind("}") + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and ANCHOR_HELPER_OUTPUT_KEYS.intersection(parsed):
            return json.dumps(parsed, ensure_ascii=False)
    return ""


def read_transcript(path: str | Path) -> list[dict[str, Any]]:
    events = []
    for line_no, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"content": raw}
        text = compact_text(" ".join(collect_strings(payload)))
        events.append({
            "line": line_no,
            "source": "transcript",
            "payload": payload,
            "text": text,
            "command": text,
        })
    return events


def read_codex_session(path: str | Path) -> list[dict[str, Any]]:
    events = []
    for line_no, raw in enumerate(Path(path).read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            wrapper = json.loads(raw)
        except json.JSONDecodeError:
            continue
        payload = wrapper.get("payload") if isinstance(wrapper, dict) else None
        if not isinstance(payload, dict):
            continue
        payload_type = payload.get("type")
        text = ""
        if payload_type == "message":
            role = payload.get("role")
            text = content_text(payload.get("content"))
            text = strip_codex_injected_prefix(text)
            if not text:
                continue
            if role == "developer" and "[Anchor]" not in text:
                continue
            if role not in {"user", "assistant", "developer"}:
                continue
            if is_codex_noise(text):
                continue
        elif payload_type == "function_call":
            role = "tool_call"
            arguments = str(payload.get("arguments") or "")
            if "anchor.py" not in arguments:
                continue
            text = f"{payload.get('name') or 'tool'} {arguments}"
        elif payload_type == "function_call_output":
            role = "tool_output"
            output = str(payload.get("output") or "")
            text = extract_codex_function_output(output)
            if not text:
                continue
        else:
            continue
        compact = compact_text(text)
        if compact:
            events.append({
                "line": line_no,
                "source": "codex",
                "role": role,
                "payload": payload,
                "text": compact,
                "command": compact,
            })
    return events


def has_any(text: str, needles: list[str]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def has_list_signal(text: str) -> bool:
    numbered = len(re.findall(r"(?:^|\s)(?:\d+\.|[A-Z][、,，])", text))
    checkbox_or_bullets = len(re.findall(r"(?:^|\s)(?:[-*]\s+|\[[ xX]\])", text))
    chinese_enumeration = len(re.findall(r"[、,，;；]", text))
    explicit_count = bool(re.search(r"(三个|四个|五个|3 个|4 个|5 个|3个|4个|5个)", text))
    return numbered >= 2 or checkbox_or_bullets >= 2 or chinese_enumeration >= 2 or explicit_count


def has_sequential_intent(text: str) -> bool:
    if has_any(text, ["one by one", "item by item", "process sequentially"]):
        return True
    return re.search(r"(一个一个|逐条|逐项)(?:地)?(?:过|处理|讨论|看|检查|推进|聊|走|来)", text) is not None


def is_child_list_signal(text: str) -> bool:
    return has_any(text, CHILD_TERMS) and has_list_signal(text) and has_sequential_intent(text)


def is_root_list_signal(text: str) -> bool:
    return has_list_signal(text) and has_sequential_intent(text)


def is_prose_state_change(text: str) -> bool:
    done_and_advance = has_any(text, DONE_TERMS) and has_any(text, ADVANCE_TERMS)
    skip_or_block = has_any(text, SKIP_OR_BLOCK_TERMS) and has_any(text, ADVANCE_TERMS)
    return done_and_advance or skip_or_block


def anchor_command(event: dict[str, Any], command: str) -> bool:
    text = event["command"]
    if "--help" in text:
        return False
    if event.get("source") == "codex" and command in {"init", "push-child", "interrupt"}:
        if "mktemp" in text or ">/dev/null" in text:
            return False
    pattern = rf"anchor\.py\s+{re.escape(command)}(?:\s|$)"
    return re.search(pattern, text) is not None


def has_anchor_context(event: dict[str, Any]) -> bool:
    text = event["text"]
    if event.get("source") == "codex":
        return text.startswith("[Anchor]") and "Current:" in text
    return "[Anchor]" in text and "Current:" in text


def has_todo_bridge_context(event: dict[str, Any]) -> bool:
    text = event["text"]
    if event.get("source") == "codex":
        return text.startswith("[Anchor Todo Bridge]")
    return "[Anchor Todo Bridge]" in text


def has_stale_warning(text: str) -> bool:
    return "Warning: tracker stale" in text


def has_nested_current_path(text: str) -> bool:
    match = re.search(r"Current:\s*([^\n\r]+)", text)
    return bool(match and ">" in match.group(1))


def has_whole_picture(text: str) -> bool:
    return "Whole Picture" in text and has_any(text, ["当前", "current", "←", "<-"])


def can_trigger_capture(event: dict[str, Any]) -> bool:
    role = event.get("role")
    return role in {None, "user"}


def can_display_whole_picture(event: dict[str, Any]) -> bool:
    role = event.get("role")
    return role in {None, "assistant"}


def helper_current_path(text: str) -> list[Any] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or "current_path" not in parsed:
        return None
    current_path = parsed["current_path"]
    return current_path if isinstance(current_path, list) else None


def is_anchor_command_error(text: str) -> bool:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and parsed.get("anchor_command_error") is True


def is_search_event(text: str) -> bool:
    return has_any(text, SEARCH_TERMS)


def is_todo_search_event(text: str) -> bool:
    return is_search_event(text) and has_any(text, TODO_TERMS)


def has_anchor_command(events: list[dict[str, Any]], start: int, stop: int, commands: set[str]) -> bool:
    for event in events[start:stop]:
        if any(anchor_command(event, command) for command in commands):
            return True
    return False


def make_finding(category: str, event: dict[str, Any]) -> dict[str, Any]:
    meta = CATEGORIES[category]
    return {
        "category": category,
        "severity": meta["severity"],
        "line": event["line"],
        "evidence": event["text"][:240],
        "suggestion": meta["suggestion"],
    }


def classify_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    root_active = False
    child_active = False
    active_anchor_context = False
    nested_anchor_context = False
    pending_nested_next = False
    stale_warning_active = False
    todo_bridge_active = False
    pending_whole_picture: dict[str, Any] | None = None
    pending_whole_picture_index: int | None = None

    for index, event in enumerate(events):
        text = event["text"]
        current_path = helper_current_path(text)
        if current_path is not None:
            root_active = bool(current_path)
            child_active = len(current_path) > 1
            active_anchor_context = bool(current_path)
            nested_anchor_context = len(current_path) > 1
        if has_anchor_context(event):
            active_anchor_context = True
            nested_anchor_context = has_nested_current_path(text)
        if has_todo_bridge_context(event):
            todo_bridge_active = True
        if has_stale_warning(text):
            stale_warning_active = True
        if anchor_command(event, "init"):
            root_active = True
            pending_whole_picture = event
            pending_whole_picture_index = index
        if anchor_command(event, "push-child"):
            child_active = True
            pending_whole_picture = event
            pending_whole_picture_index = index
        if anchor_command(event, "interrupt"):
            child_active = True
            pending_whole_picture = event
            pending_whole_picture_index = index
        if anchor_command(event, "next"):
            pending_nested_next = False
        if anchor_command(event, "next") and child_active:
            child_active = False
        if any(anchor_command(event, command) for command in ["todo-status", "todo-configure", "todo-start"]):
            todo_bridge_active = False

        if pending_whole_picture and event is not pending_whole_picture:
            if has_whole_picture(text) and can_display_whole_picture(event):
                pending_whole_picture = None
                pending_whole_picture_index = None
            elif is_anchor_command_error(text):
                pending_whole_picture = None
                pending_whole_picture_index = None
            elif any(anchor_command(event, command) for command in ["init", "push-child", "interrupt"]):
                pass
            elif pending_whole_picture_index is not None and index - pending_whole_picture_index >= 2:
                findings.append(make_finding("missing-whole-picture", pending_whole_picture))
                pending_whole_picture = None
                pending_whole_picture_index = None

        if stale_warning_active and has_any(text, TRACKER_IGNORE_TERMS):
            findings.append(make_finding("stale-tracker-ignored", event))
            stale_warning_active = False
            continue

        if todo_bridge_active and is_todo_search_event(text):
            findings.append(make_finding("todo-bridge-bypass", event))
            todo_bridge_active = False
            continue

        if active_anchor_context and is_search_event(text) and pending_nested_next:
            findings.append(make_finding("recreated-agenda-from-search", event))
            pending_nested_next = False
            continue

        if nested_anchor_context and has_any(text, ADVANCE_TERMS):
            pending_nested_next = True

        if pending_nested_next and has_any(text, WRONG_PARENT_TERMS):
            findings.append(make_finding("wrong-next-target", event))
            pending_nested_next = False
            continue

        lookahead_stop = min(len(events), index + 4)
        if can_trigger_capture(event) and is_child_list_signal(text) and root_active:
            if not has_anchor_command(events, index, lookahead_stop, {"push-child"}):
                findings.append(make_finding("missed-child-capture", event))
            continue

        if can_trigger_capture(event) and is_root_list_signal(text) and not root_active:
            if not has_anchor_command(events, index, lookahead_stop, {"init"}):
                findings.append(make_finding("missed-root-capture", event))
            continue

        if is_prose_state_change(text) and root_active:
            if not has_anchor_command(events, index, lookahead_stop, {"complete", "defer", "block", "next"}):
                findings.append(make_finding("prose-only-state-change", event))

    if pending_whole_picture:
        findings.append(make_finding("missing-whole-picture", pending_whole_picture))

    return findings


def check_transcript(path: str | Path) -> dict[str, Any]:
    events = read_transcript(path)
    findings = classify_events(events)
    return {
        "path": str(path),
        "event_count": len(events),
        "finding_count": len(findings),
        "findings": findings,
    }


def check_codex_session(path: str | Path) -> dict[str, Any]:
    events = read_codex_session(path)
    findings = classify_events(events)
    return {
        "path": str(path),
        "event_count": len(events),
        "finding_count": len(findings),
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Anchor transcript pressure fixtures")
    parser.add_argument("--codex-session", action="store_true", help="Parse raw Codex session JSONL and ignore injected rule noise")
    parser.add_argument("transcript", nargs="+", help="JSONL or text transcript path")
    args = parser.parse_args(argv)

    checker = check_codex_session if args.codex_session else check_transcript
    results = [checker(path) for path in args.transcript]
    payload: dict[str, Any]
    if len(results) == 1:
        payload = results[0]
    else:
        payload = {
            "finding_count": sum(result["finding_count"] for result in results),
            "results": results,
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if any(result["findings"] for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
