"""Parse tool-call JSON from model output (including large create_file payloads)."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

FILE_WRITE_TOOLS = frozenset({"create_file", "edit_file", "write_file"})


def is_tool_json_attempt(text: str) -> bool:
    """Model started a tool-call JSON payload (may be truncated)."""
    s = text.lstrip()
    if not s.startswith("{"):
        return False
    head = s[:240]
    return bool(re.search(r'"tools"\s*:', head) or re.search(r"\btools\s*:", head))


def extract_balanced_json(text: str, start_idx: int) -> Optional[Tuple[str, int]]:
    """Return a balanced {...} or [...] substring starting at start_idx."""
    if start_idx >= len(text) or text[start_idx] not in "{[":
        return None
    stack: List[str] = []
    open_to_close = {"[": "]", "{": "}"}
    in_string = False
    escape = False
    for idx in range(start_idx, len(text)):
        ch = text[idx]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in open_to_close:
            stack.append(ch)
        elif ch in ("]", "}"):
            if not stack or open_to_close[stack[-1]] != ch:
                return None
            stack.pop()
            if not stack:
                return text[start_idx : idx + 1], idx + 1
    return None


def _normalize_tool_entry(tool: Any) -> Optional[Tuple[str, Dict[str, Any]]]:
    if not isinstance(tool, dict):
        return None
    name = tool.get("name", "")
    args = tool.get("args", {})
    if not name or not isinstance(args, dict):
        return None
    args = dict(args)
    args.pop("encoding", None)
    return name, args


def _tools_from_parsed(data: Any) -> List[Tuple[str, Dict[str, Any]]]:
    out: List[Tuple[str, Dict[str, Any]]] = []
    if isinstance(data, dict) and "tools" in data:
        items = data["tools"]
    elif isinstance(data, list):
        items = data
    else:
        return out
    if not isinstance(items, list):
        return out
    for tool in items:
        pair = _normalize_tool_entry(tool)
        if pair:
            out.append(pair)
    return out


def _salvage_file_tool(
    content: str, tool_name: str
) -> List[Tuple[str, Dict[str, Any]]]:
    """Last resort when JSON.loads fails on a huge escaped content string."""
    if f'"{tool_name}"' not in content and f"'{tool_name}'" not in content:
        return []
    fp_match = re.search(
        r'"file_path"\s*:\s*"((?:[^"\\]|\\.)*)"', content, re.DOTALL
    )
    if not fp_match:
        return []
    file_path = json.loads(f'"{fp_match.group(1)}"')

    key = '"content"'
    pos = content.find(key)
    if pos < 0:
        return []
    i = pos + len(key)
    while i < len(content) and content[i].isspace():
        i += 1
    if i >= len(content) or content[i] != '"':
        return []
    i += 1
    chars: List[str] = []
    escape = False
    while i < len(content):
        ch = content[i]
        if escape:
            chars.append(ch)
            escape = False
            i += 1
            continue
        if ch == "\\":
            escape = True
            i += 1
            continue
        if ch == '"':
            break
        chars.append(ch)
        i += 1
    else:
        return []

    raw = "".join(chars)
    try:
        body = json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        body = raw.encode("utf-8").decode("unicode_escape", errors="replace")

    return [(tool_name, {"file_path": file_path, "content": body})]


def _salvage_create_file(content: str) -> List[Tuple[str, Dict[str, Any]]]:
    return _salvage_file_tool(content, "create_file")


def _salvage_edit_file(content: str) -> List[Tuple[str, Dict[str, Any]]]:
    out = _salvage_file_tool(content, "edit_file")
    if out:
        return out
    return _salvage_file_tool(content, "write_file")


def complete_truncated_json(content: str) -> str:
    """Close open strings/brackets when the model hit the token limit mid-JSON."""
    text = content.rstrip()
    in_string = False
    escape = False
    brace_depth = 0
    bracket_depth = 0
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth = max(brace_depth - 1, 0)
        elif ch == "[":
            bracket_depth += 1
        elif ch == "]":
            bracket_depth = max(bracket_depth - 1, 0)

    if in_string:
        text += '"'
    text += "]" * bracket_depth + "}" * brace_depth
    return text


def extract_tool_calls(
    content: str, *, _repaired: bool = False
) -> List[Tuple[str, Dict[str, Any]]]:
    """Extract tool calls; returns at most one tool per agent step (first entry)."""
    text = content.strip()
    if not text:
        return []

    for marker in ('{"tools"', '{ "tools"'):
        idx = text.find(marker)
        if idx >= 0:
            seg = extract_balanced_json(text, idx)
            if seg:
                try:
                    parsed = json.loads(seg[0])
                    calls = _tools_from_parsed(parsed)
                    if calls:
                        return [calls[0]]
                except json.JSONDecodeError:
                    pass

    match = re.search(r"\btools\b\s*:", text)
    if match:
        search_start = match.end()
        while search_start < len(text) and text[search_start].isspace():
            search_start += 1
        for open_ch in ("[", "{"):
            pos = text.find(open_ch, search_start)
            if pos == -1:
                continue
            seg = extract_balanced_json(text, pos)
            if not seg:
                continue
            try:
                parsed = json.loads(seg[0])
                if isinstance(parsed, dict) and "tools" in parsed:
                    calls = _tools_from_parsed(parsed)
                else:
                    calls = _tools_from_parsed(parsed)
                if calls:
                    return [calls[0]]
            except json.JSONDecodeError:
                continue

    if not _repaired and is_tool_json_attempt(text):
        repaired = complete_truncated_json(text)
        if repaired != text:
            calls = extract_tool_calls(repaired, _repaired=True)
            if calls:
                return [calls[0]]

    for salvage in (_salvage_create_file, _salvage_edit_file):
        salvaged = salvage(text)
        if salvaged:
            return [salvaged[0]]

    return []
