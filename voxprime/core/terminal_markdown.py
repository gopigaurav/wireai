"""ANSI highlighting for assistant markdown in the terminal (options, code, questions)."""

from __future__ import annotations

import os
import re
from typing import List

_BOLD = "\x1b[1m"
_CYAN = "\x1b[96m"
_YELLOW = "\x1b[93m"
_GREEN = "\x1b[92m"
_DIM = "\x1b[2m"
_MAGENTA = "\x1b[95m"
_RESET = "\x1b[0m"

_FENCE_RE = re.compile(r"^\s*```(\w*)?\s*$")
_NUMBERED_RE = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")
_BOLD_ONLY_RE = re.compile(r"^\s*\*\*(.+?)\*\*\s*$")
_INLINE_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_RECOMMENDED_RE = re.compile(r"\(recommended\)", re.IGNORECASE)


def markdown_format_enabled() -> bool:
    return os.getenv("VOXPRIME_FORMAT_MARKDOWN", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def _inline_bold(text: str) -> str:
    return _INLINE_BOLD_RE.sub(lambda m: f"{_BOLD}{_YELLOW}{m.group(1)}{_RESET}", text)


def format_assistant_line(line: str, state: dict) -> str:
    """Format one line of assistant prose for the terminal."""
    raw = line
    stripped = line.strip()

    if _FENCE_RE.match(stripped):
        state["in_code"] = not state.get("in_code", False)
        lang = stripped.strip("`").strip() or "code"
        if state["in_code"]:
            state["code_lang"] = lang
            return f"\n{_CYAN}{_BOLD}--- {lang} ---{_RESET}"
        return f"{_DIM}--- end ---{_RESET}"

    if state.get("in_code"):
        return f"  {_GREEN}{line}{_RESET}"

    if _BOLD_ONLY_RE.match(stripped):
        title = _BOLD_ONLY_RE.match(stripped).group(1)
        return f"\n{_BOLD}{_CYAN}{title}{_RESET}"

    m = _NUMBERED_RE.match(line)
    if m:
        indent, num, rest = m.group(1), m.group(2), m.group(3)
        rest = _inline_bold(rest)
        rest = _RECOMMENDED_RE.sub(
            lambda _: f"{_GREEN}(recommended){_RESET}", rest
        )
        return f"{indent}{_BOLD}{_CYAN}{num}.{_RESET} {rest}"

    if stripped.startswith("- ") or stripped.startswith("* "):
        body = _inline_bold(stripped[2:])
        return f"  {_CYAN}•{_RESET} {body}"

    if stripped.endswith("?") and len(stripped) < 160:
        return f"\n{_BOLD}{_MAGENTA}{line}{_RESET}"

    return _inline_bold(line)


class TerminalStreamFormatter:
    """Line-buffer streamed tokens and emit ANSI-formatted lines."""

    def __init__(self) -> None:
        self._buf = ""
        self._state: dict = {"in_code": False, "code_lang": ""}
        self._enabled = markdown_format_enabled()

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        if not self._enabled:
            return chunk
        self._buf += chunk.replace("\r\n", "\n").replace("\r", "\n")
        parts: List[str] = []
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            parts.append(format_assistant_line(line, self._state) + "\n")
        return "".join(parts)

    def flush(self) -> str:
        if not self._buf:
            return ""
        if not self._enabled:
            tail = self._buf
            self._buf = ""
            return tail
        line = self._buf
        self._buf = ""
        return format_assistant_line(line, self._state)
