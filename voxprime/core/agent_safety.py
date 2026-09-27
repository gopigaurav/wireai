"""
Safety and session utilities ported from example.py (Agentic Bridge).

Used by agent_with_tools.py: undo, dry-run, permissions, destructive confirmations.
"""

from __future__ import annotations

import atexit
import hashlib
import os
import shutil
import tempfile
from datetime import datetime
from difflib import get_close_matches
from typing import Any, Dict, List, Optional, Tuple

# Shell fragments that require explicit confirmation (from example.py)
DESTRUCTIVE_COMMANDS = [
    "rm ",
    "del ",
    "rmdir ",
    "remove-item ",
    "git reset",
    "git clean",
    "drop table",
    "truncate ",
    "format ",
    "mkfs",
]

FILE_MODIFY_TOOLS = frozenset(
    {
        "write_file",
        "create_file",
        "edit_file",
        "delete_file",
    }
)

# Shell execution — always prompt unless user allowed once / prefix (Cursor / Claude Code style)
COMMAND_TOOLS = frozenset({"run_command"})

# Git MCP write operations (mcp-server-git)
GIT_WRITE_TOOLS = frozenset(
    {
        "git_add",
        "git_commit",
        "git_create_branch",
        "git_checkout",
    }
)

# Permission prompt styling (terminal)
_BOLD = "\x1b[1m"
_CYAN = "\x1b[96m"
_YELLOW = "\x1b[93m"
_DIM = "\x1b[2m"
_RESET = "\x1b[0m"
_BOX = "\x1b[90m"


def _highlight_choice(key: str, label: str) -> str:
    return f"  {_BOLD}{_CYAN}[{key}]{_RESET} {_YELLOW}{label}{_RESET}"


def _permission_banner(title: str) -> None:
    print(f"\n{_BOX}{'═' * 60}{_RESET}")
    print(f"  {_BOLD}{title}{_RESET}")
    print(f"{_BOX}{'═' * 60}{_RESET}")


def _tool_filepath(tool_name: str, arguments: dict) -> str:
    for key in ("file_path", "filepath", "path"):
        if key in arguments:
            return str(arguments[key])
    return ""


def format_tool_description(tool_name: str, arguments: dict) -> str:
    if tool_name == "run_command":
        return f"Run command: {arguments.get('command', '')}"
    if tool_name.startswith("git_"):
        return f"Git: {tool_name}({arguments})"
    if tool_name == "delete_file":
        return f"Delete file: {_tool_filepath(tool_name, arguments)}"
    if tool_name in ("write_file", "create_file"):
        return f"Create/overwrite file: {_tool_filepath(tool_name, arguments)}"
    if tool_name == "edit_file":
        return f"Edit file: {_tool_filepath(tool_name, arguments)}"
    return f"{tool_name}({arguments})"


def is_destructive_tool(tool_name: str, arguments: dict) -> bool:
    if tool_name == "delete_file":
        return True
    if tool_name == "run_command":
        cmd = str(arguments.get("command", "")).lower()
        return any(fragment in cmd for fragment in DESTRUCTIVE_COMMANDS)
    return False


def find_similar_file(filepath: str, max_distance: int = 3) -> str:
    """Fuzzy match a filename in the same directory (example.py behavior)."""
    if os.path.exists(filepath):
        return filepath

    dirname = os.path.dirname(filepath) or "."
    basename = os.path.basename(filepath)
    if not os.path.isdir(dirname):
        return filepath

    candidates = [f for f in os.listdir(dirname) if os.path.isfile(os.path.join(dirname, f))]
    if not candidates:
        return filepath

    close = get_close_matches(basename, candidates, n=1, cutoff=0.6)
    if close:
        return os.path.join(dirname, close[0])

    def levenshtein(s1: str, s2: str) -> int:
        if len(s1) < len(s2):
            return levenshtein(s2, s1)
        if not s2:
            return len(s1)
        prev = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            curr = [i + 1]
            for j, c2 in enumerate(s2):
                curr.append(
                    min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2))
                )
            prev = curr
        return prev[-1]

    for name in candidates:
        if levenshtein(basename, name) <= max_distance:
            return os.path.join(dirname, name)
    return filepath


class UndoManager:
    """Backup files before modifications; restore with undo_last()."""

    def __init__(self, max_history: int = 50):
        self.max_history = max_history
        self.history: List[Dict[str, Any]] = []
        self._temp_dir = os.path.join(tempfile.gettempdir(), "voxprime_undo")
        os.makedirs(self._temp_dir, exist_ok=True)

    def save_file_state(self, filepath: str) -> Optional[str]:
        if not filepath or not os.path.exists(filepath):
            return None
        backup_id = hashlib.md5(
            f"{filepath}{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]
        backup_path = os.path.join(self._temp_dir, f"{backup_id}.bak")
        with open(filepath, "rb") as src, open(backup_path, "wb") as dst:
            dst.write(src.read())
        self.history.append(
            {
                "type": "file_modification",
                "filepath": os.path.abspath(filepath),
                "backup_path": backup_path,
                "timestamp": datetime.now().isoformat(),
            }
        )
        while len(self.history) > self.max_history:
            old = self.history.pop(0)
            bp = old.get("backup_path")
            if bp and os.path.exists(bp):
                os.remove(bp)
        return backup_path

    def undo_last(self) -> Tuple[bool, str]:
        if not self.history:
            return False, "No actions to undo"
        entry = self.history.pop()
        if entry.get("type") != "file_modification":
            return False, "Unknown action type"
        filepath = entry["filepath"]
        backup_path = entry["backup_path"]
        if not os.path.exists(backup_path):
            return False, "Backup file not found"
        with open(backup_path, "rb") as src, open(filepath, "wb") as dst:
            dst.write(src.read())
        os.remove(backup_path)
        return True, f"Restored: {filepath}"

    def clear(self) -> None:
        for entry in self.history:
            bp = entry.get("backup_path")
            if bp and os.path.exists(bp):
                os.remove(bp)
        self.history.clear()


class DryRunManager:
    def __init__(self) -> None:
        self.enabled = False
        self.planned_actions: List[Dict[str, Any]] = []

    def enable(self) -> None:
        self.enabled = True
        self.planned_actions = []
        print("\n[DRY-RUN ON] Actions will be previewed, not executed.")

    def disable(self) -> None:
        self.enabled = False
        print("\n[DRY-RUN OFF] Actions will execute normally.")

    def record(self, tool_name: str, arguments: dict) -> str:
        action = {"tool": tool_name, "arguments": arguments}
        self.planned_actions.append(action)
        return format_tool_description(tool_name, arguments)

    def show_planned(self) -> None:
        if not self.planned_actions:
            print("[No planned actions]")
            return
        print(f"\n[PLANNED ACTIONS — {len(self.planned_actions)}]")
        for i, act in enumerate(self.planned_actions, 1):
            print(f"  {i}. {format_tool_description(act['tool'], act['arguments'])}")


class PermissionManager:
    """Cursor / Claude-style allow once, skip, or allow-always for files and shell commands."""

    def __init__(self) -> None:
        self.allowed_always: set[str] = set()
        self.session_allowed: set[str] = set()
        self.allowed_always_commands: set[str] = set()
        self.session_allowed_commands: set[str] = set()
        self.denied_always_commands: set[str] = set()
        # Until `reset` clears conversation — allow any run_command without prompts
        self.conversation_allow_all_shell: bool = False

    def _matches(self, filepath: str, pattern: str) -> bool:
        import fnmatch

        return fnmatch.fnmatch(filepath, pattern) or fnmatch.fnmatch(
            os.path.basename(filepath), pattern
        )

    def _matches_command(self, command: str, pattern: str) -> bool:
        import fnmatch

        cmd = command.strip()
        return fnmatch.fnmatch(cmd, pattern) or cmd.startswith(pattern.rstrip("*"))

    @staticmethod
    def command_prefix_pattern(command: str) -> str:
        """Pattern for 'allow always' — e.g. `npm install foo` -> `npm*`."""
        parts = command.strip().split(None, 1)
        if not parts:
            return "*"
        return f"{parts[0]}*"

    def is_allowed(self, tool_name: str, arguments: dict) -> bool:
        if tool_name in GIT_WRITE_TOOLS:
            if "__all_git_writes__" in self.session_allowed_commands:
                return True
            key = f"git:{tool_name}:{arguments.get('repo_path', '')}"
            if key in self.session_allowed_commands:
                return True
            return False
        if tool_name in COMMAND_TOOLS:
            return self._is_command_allowed(str(arguments.get("command", "")))

        if tool_name not in FILE_MODIFY_TOOLS:
            return True
        filepath = _tool_filepath(tool_name, arguments)
        if not filepath:
            return True
        if filepath in self.session_allowed:
            return True
        for pattern in self.allowed_always:
            if self._matches(filepath, pattern):
                return True
        return False

    def _is_command_allowed(self, command: str) -> bool:
        cmd = command.strip()
        if not cmd:
            return True
        if self.conversation_allow_all_shell:
            return True
        if cmd in self.session_allowed_commands:
            return True
        for pattern in self.denied_always_commands:
            if self._matches_command(cmd, pattern):
                return False
        for pattern in self.allowed_always_commands:
            if self._matches_command(cmd, pattern):
                return True
        return False

    def grant(self, filepath: str, scope: str = "once") -> None:
        if scope == "once":
            self.session_allowed.add(filepath)
        elif scope == "always":
            ext = os.path.splitext(filepath)[1]
            if ext:
                self.allowed_always.add(f"*{ext}")
            self.allowed_always.add(os.path.basename(filepath))

    def grant_command(self, command: str, scope: str = "once") -> None:
        cmd = command.strip()
        if scope == "once":
            self.session_allowed_commands.add(cmd)
        elif scope == "always":
            self.allowed_always_commands.add(self.command_prefix_pattern(cmd))

    def reset_conversation_permissions(self) -> None:
        """Clear per-conversation shell auto-approve (e.g. after `reset`)."""
        self.conversation_allow_all_shell = False

    def reset_all(self) -> None:
        self.allowed_always.clear()
        self.session_allowed.clear()
        self.allowed_always_commands.clear()
        self.session_allowed_commands.clear()
        self.denied_always_commands.clear()
        self.conversation_allow_all_shell = False

    def ask(self, tool_name: str, arguments: dict) -> bool:
        if tool_name in COMMAND_TOOLS:
            return self._ask_run_command(arguments)
        if tool_name in GIT_WRITE_TOOLS:
            return self._ask_git_write(tool_name, arguments)
        return self._ask_file_permission(tool_name, arguments)

    async def _read_choice(self, prompt: str) -> str:
        from voxprime.core.stdin_broker import get_broker

        broker = get_broker()
        if broker:
            return (await broker.read_choice(prompt)).strip()
        return input(prompt).strip()

    async def ask_async(self, tool_name: str, arguments: dict) -> bool:
        if tool_name in COMMAND_TOOLS:
            return await self._ask_run_command_async(arguments)
        if tool_name in GIT_WRITE_TOOLS:
            return await self._ask_git_write_async(tool_name, arguments)
        return await self._ask_file_permission_async(tool_name, arguments)

    def _ask_git_write(self, tool_name: str, arguments: dict) -> bool:
        _permission_banner("Allow Git change?")
        print(f"  {format_tool_description(tool_name, arguments)}")
        print()
        print(_highlight_choice("A", "Allow once"))
        print(_highlight_choice("D", "Skip"))
        print(_highlight_choice("AA", "Allow all git writes this session"))
        try:
            choice = input(f"\n  {_DIM}Your choice{_RESET} {_CYAN}(A/D/AA){_RESET}: ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            print("\n  Skipped (interrupted).")
            return False
        if choice in ("A", "ALLOW", "Y", "YES", "RUN"):
            key = f"git:{tool_name}:{arguments.get('repo_path', '')}"
            self.session_allowed_commands.add(key)
            return True
        if choice in ("AA", "ALLOW ALWAYS", "ALLOWALWAYS"):
            self.session_allowed_commands.add("__all_git_writes__")
            return True
        print("  Skipped.")
        return False

    async def _ask_git_write_async(self, tool_name: str, arguments: dict) -> bool:
        _permission_banner("Allow Git change?")
        print(f"  {format_tool_description(tool_name, arguments)}")
        print()
        print(_highlight_choice("A", "Allow once"))
        print(_highlight_choice("D", "Skip"))
        print(_highlight_choice("AA", "Allow all git writes this session"))
        try:
            choice = (await self._read_choice(
                f"\n  {_DIM}Your choice{_RESET} {_CYAN}(A/D/AA){_RESET}: "
            )).upper()
        except (EOFError, KeyboardInterrupt):
            print("\n  Skipped (interrupted).")
            return False
        if choice in ("A", "ALLOW", "Y", "YES", "RUN"):
            key = f"git:{tool_name}:{arguments.get('repo_path', '')}"
            self.session_allowed_commands.add(key)
            return True
        if choice in ("AA", "ALLOW ALWAYS", "ALLOWALWAYS"):
            self.session_allowed_commands.add("__all_git_writes__")
            return True
        print("  Skipped.")
        return False

    def _ask_file_permission(self, tool_name: str, arguments: dict) -> bool:
        filepath = _tool_filepath(tool_name, arguments)
        _permission_banner("Allow file change?")
        print(f"  {format_tool_description(tool_name, arguments)}")
        print()
        print(_highlight_choice("A", "Allow once"))
        print(_highlight_choice("D", "Skip"))
        print(_highlight_choice("AA", "Always allow similar paths"))
        try:
            choice = input(f"\n  {_DIM}Your choice{_RESET} {_CYAN}(A/D/AA){_RESET}: ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            print("\n  Skipped (interrupted).")
            return False
        if choice in ("A", "ALLOW", "Y", "YES", "RUN"):
            self.grant(filepath, "once")
            return True
        if choice in ("AA", "ALLOW ALWAYS", "ALLOWALWAYS"):
            self.grant(filepath, "always")
            return True
        print("  Skipped.")
        return False

    async def _ask_file_permission_async(self, tool_name: str, arguments: dict) -> bool:
        _permission_banner("Allow file change?")
        print(f"  {format_tool_description(tool_name, arguments)}")
        print()
        print(_highlight_choice("A", "Allow once"))
        print(_highlight_choice("D", "Skip"))
        print(_highlight_choice("AA", "Always allow similar paths"))
        try:
            choice = (await self._read_choice(
                f"\n  {_DIM}Your choice{_RESET} {_CYAN}(A/D/AA){_RESET}: "
            )).upper()
        except (EOFError, KeyboardInterrupt):
            print("\n  Skipped (interrupted).")
            return False
        if choice in ("A", "ALLOW", "Y", "YES", "RUN"):
            self.grant(_tool_filepath(tool_name, arguments), "once")
            return True
        if choice in ("AA", "ALLOW ALWAYS", "ALLOWALWAYS"):
            self.grant(_tool_filepath(tool_name, arguments), "always")
            return True
        print("  Skipped.")
        return False

    def _ask_run_command(self, arguments: dict) -> bool:
        command = str(arguments.get("command", "")).strip()
        cwd = os.getcwd()
        destructive = is_destructive_tool("run_command", arguments)
        risk = "  ⚠️  This command looks destructive.\n" if destructive else ""

        _permission_banner("Allow terminal command?")
        if risk:
            print(risk)
        print(f"  {_DIM}Directory:{_RESET} {cwd}")
        print(f"  {_DIM}Command:{_RESET}   {_YELLOW}{command}{_RESET}")
        print()
        print(_highlight_choice("A", "Run once"))
        print(_highlight_choice("D", "Skip"))
        prefix = self.command_prefix_pattern(command)
        print(
            _highlight_choice(
                "AA",
                f"Allow similar commands (prefix `{prefix}`) for this terminal session",
            )
        )
        print(
            _highlight_choice(
                "AS",
                "Allow any shell command until you run `reset` (this conversation only)",
            )
        )
        print(f"{_BOX}{'═' * 60}{_RESET}")
        try:
            choice = input(
                f"\n  {_DIM}Your choice{_RESET} {_CYAN}(A/D/AA/AS){_RESET}: "
            ).strip().upper()
        except (EOFError, KeyboardInterrupt):
            print("\n  Skipped (interrupted).")
            return False
        return self._apply_run_command_choice(choice, command)

    def _apply_run_command_choice(self, choice: str, command: str) -> bool:
        if choice in ("A", "ALLOW", "Y", "YES", "RUN"):
            self.grant_command(command, "once")
            print(f"  {_CYAN}→{_RESET} {_BOLD}Running command…{_RESET} (live output below)\n")
            return True
        if choice in ("AA", "ALLOW ALWAYS", "ALLOWALWAYS"):
            self.grant_command(command, "always")
            print(
                f"  {_CYAN}→{_RESET} Allowed prefix `{self.command_prefix_pattern(command)}` "
                f"for this terminal session.\n"
            )
            print(f"  {_CYAN}→{_RESET} {_BOLD}Running command…{_RESET} (live output below)\n")
            return True
        if choice in ("AS", "ALLOW SHELL", "ALLOWALL", "ALLOW ALL", "ALL"):
            self.conversation_allow_all_shell = True
            print(
                f"  {_CYAN}→{_RESET} All shell commands auto-approved until "
                f"`reset` clears the conversation.\n"
            )
            print(f"  {_CYAN}→{_RESET} {_BOLD}Running command…{_RESET} (live output below)\n")
            return True
        print(f"  {_DIM}→ Skipped.{_RESET}\n")
        return False

    async def _ask_run_command_async(self, arguments: dict) -> bool:
        command = str(arguments.get("command", "")).strip()
        cwd = os.getcwd()
        destructive = is_destructive_tool("run_command", arguments)
        risk = "  ⚠️  This command looks destructive.\n" if destructive else ""

        _permission_banner("Allow terminal command?")
        if risk:
            print(risk)
        print(f"  {_DIM}Directory:{_RESET} {cwd}")
        print(f"  {_DIM}Command:{_RESET}   {_YELLOW}{command}{_RESET}")
        print()
        print(_highlight_choice("A", "Run once"))
        print(_highlight_choice("D", "Skip"))
        prefix = self.command_prefix_pattern(command)
        print(
            _highlight_choice(
                "AA",
                f"Allow similar commands (prefix `{prefix}`) for this terminal session",
            )
        )
        print(
            _highlight_choice(
                "AS",
                "Allow any shell command until you run `reset` (this conversation only)",
            )
        )
        print(f"{_BOX}{'═' * 60}{_RESET}")
        try:
            choice = (await self._read_choice(
                f"\n  {_DIM}Your choice{_RESET} {_CYAN}(A/D/AA/AS){_RESET}: "
            )).upper()
        except (EOFError, KeyboardInterrupt):
            print("\n  Skipped (interrupted).")
            return False
        return self._apply_run_command_choice(choice, command)


class SessionStats:
    def __init__(self) -> None:
        self.tool_calls = 0
        self.denied = 0
        self.dry_run = 0

    def summary(self) -> str:
        return (
            f"Tool calls: {self.tool_calls}, denied: {self.denied}, "
            f"dry-run previews: {self.dry_run}"
        )


_undo_singleton = UndoManager()


def get_undo_manager() -> UndoManager:
    return _undo_singleton


def cleanup_undo_files() -> None:
    if os.path.exists(_undo_singleton._temp_dir):
        shutil.rmtree(_undo_singleton._temp_dir, ignore_errors=True)


atexit.register(cleanup_undo_files)
