"""Cursor-style tool activity lines and terminal spinners."""

from __future__ import annotations

import os
from typing import Any, Dict, List

DEFAULT_SPINNER = os.getenv("VOXPRIME_THINKING_SPINNER", "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")


def spinner_char(index: int, spinner: str | None = None) -> str:
    s = spinner or DEFAULT_SPINNER
    if not s:
        return "⠋"
    return s[index % len(s)]


def describe_tool_activity(tool_name: str, arguments: Dict[str, Any]) -> str:
    """One-line summary like Cursor (Read, Grepped, Run, …)."""
    args = arguments or {}

    if tool_name == "read_file":
        path = args.get("file_path", "?")
        start = args.get("start_line")
        end = args.get("end_line")
        if start is not None or end is not None:
            return f"Read `{path}` L{start or 1}-{end or '…'}"
        return f"Read `{path}`"

    if tool_name == "search_files":
        q = args.get("query", "")
        d = args.get("dir_path", ".")
        return f"Grepped `{q}` in `{d}`"

    if tool_name == "list_directory":
        path = (
            args.get("dir_path")
            or args.get("path")
            or args.get("directory")
            or args.get("folder")
            or "."
        )
        return f"Listed `{path}`"

    if tool_name == "run_command":
        cmd = str(args.get("command", "")).strip()
        if len(cmd) > 72:
            cmd = cmd[:69] + "..."
        return f"Run `{cmd}`"

    if tool_name == "delete_file":
        return f"Delete `{args.get('file_path', '?')}`"

    if tool_name in ("create_file", "write_file", "edit_file"):
        return f"{tool_name} `{args.get('file_path', '?')}`"

    if tool_name.startswith("git_"):
        return f"Git {tool_name}({args.get('repo_path', '.')})"

    if tool_name in ("get_weather", "search_web", "fetch_url", "fetch_webpage"):
        return f"{tool_name}({args})"

    return f"{tool_name}({args})"


class TurnActivityLog:
    """Collects tool steps for one user turn (printed like Cursor's trace)."""

    def __init__(self) -> None:
        self._lines: List[str] = []

    def reset(self) -> None:
        self._lines.clear()

    def record(self, tool_name: str, arguments: Dict[str, Any]) -> None:
        self._lines.append(describe_tool_activity(tool_name, arguments))

    @property
    def lines(self) -> List[str]:
        return list(self._lines)

    def format_block(self) -> str:
        if not self._lines:
            return ""
        body = "\n".join(f"  ▸ {line}" for line in self._lines)
        return f"\n\x1b[90mActivity this turn ({len(self._lines)} tool{'s' if len(self._lines) != 1 else ''}):\x1b[0m\n{body}\n"
