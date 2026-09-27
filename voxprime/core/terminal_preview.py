"""Collapsed terminal previews for file tools (Cursor-style)."""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, Tuple

from voxprime.core.tool_parse import FILE_WRITE_TOOLS

DEFAULT_PREVIEW_LINES = int(os.getenv("VOXPRIME_FILE_PREVIEW_LINES", "8"))


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + 1


def format_file_tool_preview(
    tool_name: str,
    arguments: Dict[str, Any],
    *,
    max_lines: int = DEFAULT_PREVIEW_LINES,
) -> str:
    path = arguments.get("file_path") or arguments.get("filepath") or "?"
    content = arguments.get("content")
    if tool_name not in FILE_WRITE_TOOLS:
        return f"{tool_name} {arguments}"

    lines: list[str] = []
    lines.append(f"\n\x1b[36m{tool_name}\x1b[0m → {path}")

    if content is None:
        lines.append("  (no content in args)")
        return "\n".join(lines) + "\n"

    body = str(content)
    n = _line_count(body)
    preview_lines = body.splitlines()[:max_lines]
    lines.append(f"  ┌─ preview ({n} line{'s' if n != 1 else ''})")
    for pl in preview_lines:
        display = pl if len(pl) <= 120 else pl[:117] + "..."
        lines.append(f"  │ {display}")
    if n > max_lines:
        lines.append(f"  └─ \x1b[90m… +{n - max_lines} more lines (expand in editor)\x1b[0m")
    else:
        lines.append("  └─")
    return "\n".join(lines) + "\n"


def format_tool_calls_collapsed(
    tool_calls: Iterable[Tuple[str, Dict[str, Any]]],
    *,
    max_lines: int = DEFAULT_PREVIEW_LINES,
) -> str:
    parts = []
    for name, args in tool_calls:
        if name in FILE_WRITE_TOOLS:
            parts.append(format_file_tool_preview(name, args, max_lines=max_lines))
        else:
            parts.append(f"\n\x1b[36m{name}\x1b[0m {args}\n")
    return "".join(parts)


def looks_like_tool_json_stream(text: str) -> bool:
    from voxprime.core.tool_parse import is_tool_json_attempt

    return is_tool_json_attempt(text) and len(text.lstrip()) >= 12
