"""Run shell commands with live output and dev-server time limits (aider-style)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable, Optional

from voxprime.core.stdin_broker import pause_broker_for_subprocess
from voxprime.core.terminal_activity import spinner_char

_DIM = "\x1b[2m"
_BOLD = "\x1b[1m"
_CYAN = "\x1b[96m"
_YELLOW = "\x1b[93m"
_GREEN = "\x1b[92m"
_RED = "\x1b[91m"
_MAGENTA = "\x1b[95m"
_BLUE = "\x1b[94m"
_BORDER = "\x1b[38;5;45m"  # teal accent (reads well on dark terminals)
_RESET = "\x1b[0m"

DEFAULT_TIMEOUT = int(os.getenv("VOXPRIME_CMD_TIMEOUT", "180"))
DEV_SERVER_CAP = int(os.getenv("VOXPRIME_DEV_SERVER_SECONDS", "25"))

_DEV_SERVER_RE = re.compile(
    r"\b(?:"
    r"npm\s+(?:start|run\s+dev)|yarn\s+(?:start|dev)|pnpm\s+(?:start|dev)|"
    r"react-scripts\s+start|next\s+dev|"
    r"vite(?:\s|$)(?!build)|flask\s+run|uvicorn\b|django-admin\s+runserver|"
    r"python\s+-m\s+http\.server"
    r")\b",
    re.IGNORECASE,
)

_hooks_var: ContextVar[Optional["CommandHooks"]] = ContextVar("voxprime_shell_hooks", default=None)


@dataclass
class CommandHooks:
    """Optional callbacks while a command runs (terminal + web status)."""

    on_status: Optional[Callable[[str], None]] = None
    on_line: Optional[Callable[[str], None]] = None


@contextmanager
def shell_run_hooks(hooks: Optional[CommandHooks]):
    token = _hooks_var.set(hooks)
    try:
        yield
    finally:
        _hooks_var.reset(token)


def _active_hooks() -> Optional[CommandHooks]:
    return _hooks_var.get()


def looks_like_dev_server(command: str) -> bool:
    return bool(_DEV_SERVER_RE.search(command.strip()))


_NPX_RE = re.compile(r"\bnpx\b", re.IGNORECASE)


def ensure_non_interactive_package_managers(command: str) -> str:
    """Avoid npx/npm install prompts that hang when stdin is brokered."""
    c = command.strip()
    if _NPX_RE.search(c) and not re.search(r"\bnpx\s+(-y|--yes)\b", c, re.I):
        c = _NPX_RE.sub("npx --yes", c, count=1)
    return c


# Scaffolding into "." often opens an interactive TUI (hangs with agent stdin).
_SCAFFOLD_INTO_DOT = re.compile(
    r"(?:npm|yarn|pnpm)\s+create\s+\S+.*\s+\.(\s|--)",
    re.IGNORECASE,
)
_NPX_SCAFFOLD_INTO_DOT = re.compile(
    r"npx\s+(?:(?:--yes|-y)\s+)?(?:\S+\s+)*\S*create\S*\s+\.(\s|--)",
    re.IGNORECASE,
)


def scaffold_into_cwd_blocked_message() -> str:
    return (
        "Command targets the current directory ('.'). Interactive scaffolds cannot run in this "
        "session. Ask the user which subdirectory to use (or create the project with file tools), "
        "then run a non-interactive command with that path. Infer stack and scripts from the "
        "repo (package.json, pyproject.toml, go.mod, etc.) — do not assume a framework."
    )


def blocks_scaffold_into_cwd(command: str) -> bool:
    c = (command or "").strip()
    return bool(_SCAFFOLD_INTO_DOT.search(c) or _NPX_SCAFFOLD_INTO_DOT.search(c))


def normalize_shell_command(command: str) -> str:
    """On Windows, route PowerShell cmdlets through powershell.exe (cmd.exe cannot run them)."""
    command = ensure_non_interactive_package_managers(command)
    if sys.platform != "win32":
        return command
    c = command.strip()
    low = c.lower()
    if low.startswith(("powershell", "pwsh", "cmd ", "cmd.exe", "cmd/c", "cmd /c")):
        return command
    ps_markers = (
        "get-childitem",
        "select-object",
        "remove-item",
        "test-path",
        "invoke-webrequest",
        "set-location",
        "$env:",
    )
    if any(m in low for m in ps_markers):
        inner = c.replace('"', '\\"')
        return f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{inner}"'
    return command


def _brief_command(command: str, max_len: int = 72) -> str:
    c = " ".join(command.split())
    return c if len(c) <= max_len else c[: max_len - 3] + "..."


def _style_shell_line(line: str) -> str:
    """Light semantic coloring for common tool output (npm, build, errors)."""
    stripped = line.strip()
    if not stripped:
        return line
    low = stripped.lower()
    if any(x in low for x in ("error", "failed", "enoent", "err!", "npm err")):
        return f"{_RED}{line.rstrip()}{_RESET}\n"
    if any(
        x in low
        for x in (
            "compiled successfully",
            "success",
            "done in",
            "added ",
            " packages",
            "build folder is ready",
        )
    ):
        return f"{_GREEN}{line.rstrip()}{_RESET}\n"
    if any(
        x in low
        for x in (
            "installing",
            "creating",
            "running",
            "building",
            "compiling",
            "fetching",
            "resolving",
        )
    ):
        return f"{_CYAN}{line.rstrip()}{_RESET}\n"
    if stripped.startswith("> ") or "react-scripts" in low:
        return f"{_MAGENTA}{line.rstrip()}{_RESET}\n"
    return line if line.endswith("\n") else line + "\n"


def _print_shell_header(raw_command: str, effective_command: str, workdir: str) -> None:
    bar = "─" * 56
    b = _BORDER
    print(
        f"\n{b}╭─{_RESET} {_BOLD}{_CYAN}TERMINAL{_RESET} {_DIM}· VoxPrime agent{_RESET}",
        flush=True,
    )
    print(f"{b}│{_RESET} {_BLUE}cwd{_RESET}  {_DIM}{workdir}{_RESET}", flush=True)
    print(
        f"{b}│{_RESET} {_BLUE}cmd{_RESET}  {_YELLOW}{_brief_command(raw_command, 110)}{_RESET}",
        flush=True,
    )
    if effective_command.strip() != raw_command.strip():
        print(
            f"{b}│{_RESET} {_BLUE}via{_RESET} {_DIM}{_brief_command(effective_command, 110)}{_RESET}",
            flush=True,
        )
    print(f"{b}╰{bar}{_RESET}", flush=True)
    print(
        f"  {_DIM}{b}│{_RESET} {_BOLD}output{_RESET} {_DIM}(streaming){_RESET}\n",
        flush=True,
    )


def _emit_status(text: str) -> None:
    hooks = _active_hooks()
    if hooks and hooks.on_status:
        hooks.on_status(text)
    else:
        sys.stdout.write(f"\r{text}")
        sys.stdout.flush()


def _emit_line(line: str) -> None:
    hooks = _active_hooks()
    if hooks and hooks.on_line:
        hooks.on_line(line)
    else:
        text = _style_shell_line(line)
        sys.stdout.write(f"{_BORDER}│{_RESET} {text}")
        sys.stdout.flush()


def _clear_status_line() -> None:
    sys.stdout.write("\r\x1b[2K")
    sys.stdout.flush()


def _kill_process(proc: subprocess.Popen) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_shell_command(
    command: str,
    *,
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
) -> dict:
    """
    Run a shell command; stream stdout/stderr to the terminal.
    Dev servers (npm start, etc.) are capped at DEV_SERVER_CAP seconds so the agent REPL does not hang.
    """
    raw_command = (command or "").strip()
    command = normalize_shell_command(raw_command)
    if not command:
        return {"error": "Empty command"}
    if blocks_scaffold_into_cwd(command):
        msg = scaffold_into_cwd_blocked_message()
        print(f"\n{_YELLOW}!{_RESET} {msg}\n", flush=True)
        return {"error": msg, "result": msg, "exit_code": 1}

    workdir = cwd or os.getcwd()
    dev_server = looks_like_dev_server(command)
    limit = timeout if timeout is not None else DEFAULT_TIMEOUT
    if dev_server:
        limit = min(limit, DEV_SERVER_CAP)

    encoding = sys.stdout.encoding or "utf-8"
    collected: list[str] = []
    spin_idx = 0
    last_output_at = time.time()
    reader_done = threading.Event()

    _print_shell_header(raw_command, command, workdir)

    child_env = os.environ.copy()
    child_env.setdefault("npm_config_yes", "true")
    child_env.setdefault("NPM_CONFIG_YES", "true")

    try:
        with pause_broker_for_subprocess():
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding=encoding,
                errors="replace",
                bufsize=1,
                env=child_env,
            )
    except Exception as e:
        return {"error": str(e)}

    def _reader() -> None:
        nonlocal last_output_at
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            collected.append(line)
            last_output_at = time.time()
            _clear_status_line()
            _emit_line(line)
        reader_done.set()

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()

    started = time.time()
    timed_out = False
    dev_capped = False

    while proc.poll() is None:
        elapsed = time.time() - started
        if elapsed > limit:
            timed_out = True
            dev_capped = dev_server
            _kill_process(proc)
            break

        ch = spinner_char(spin_idx)
        spin_idx += 1
        brief = _brief_command(command)
        idle = int(time.time() - last_output_at)
        status = (
            f"{_YELLOW}{ch}{_RESET} {_BOLD}{_MAGENTA}running{_RESET} "
            f"{_DIM}│{_RESET} {_YELLOW}{brief}{_RESET} "
            f"{_DIM}({int(elapsed)}s"
        )
        if idle >= 2:
            status += f", idle {idle}s"
        status += f"){_RESET}"
        _emit_status(status)
        time.sleep(0.12)

    thread.join(timeout=2)
    _clear_status_line()

    code = proc.poll()
    if code is None:
        code = -1

    output = "".join(collected).strip()
    max_result = 24_000
    if len(output) > max_result:
        output = output[:max_result] + f"\n… [truncated, {len(collected)} lines total]"

    if dev_capped:
        print(
            f"\n\x1b[33m!\x1b[0m Dev server stopped after {limit}s (session kept responsive)\n",
            flush=True,
        )
        note = (
            f"\n\n[System: Dev server command stopped after {limit}s so the chat session can continue. "
            "Use `npm run build` or `npm test` to verify fixes. "
            "Run `npm start` yourself in a separate terminal to use the dev server.]"
        )
        body = (output + note) if output else note.strip()
        return {
            "result": body,
            "exit_code": code,
            "dev_server_capped": True,
        }

    if timed_out:
        return {
            "result": (
                (output + f"\n\n[Command timed out after {limit}s]")
                if output
                else f"Command timed out after {limit}s"
            ),
            "exit_code": code,
            "timed_out": True,
        }

    elapsed_s = time.time() - started
    dur = f"{elapsed_s:.1f}s" if elapsed_s < 120 else f"{int(elapsed_s)}s"

    if code != 0:
        prefix = f"Exit code {code}\n" if output else f"Exit code {code}"
        hint = ""
        low = output.lower()
        if "current directory is not empty" in low or "cancel operation" in low:
            hint = (
                "\n\n[System: Scaffold failed — do not target `.` in a non-empty tree. "
                "Ask the user for a new directory name or scaffold with create_file/edit_file. "
                "Match commands to what the repo already uses.]\n"
            )
        print(
            f"\n{_BORDER}╰─{_RESET} {_RED}{_BOLD}failed{_RESET} "
            f"{_DIM}exit {code} · {dur}{_RESET}\n",
            flush=True,
        )
        body = prefix + output if output else prefix
        return {"result": body + hint, "exit_code": code}

    print(
        f"\n{_BORDER}╰─{_RESET} {_GREEN}{_BOLD}done{_RESET} "
        f"{_DIM}· {dur}{_RESET}\n",
        flush=True,
    )
    return {
        "result": output if output else "Command finished (no output).",
        "exit_code": 0,
    }
