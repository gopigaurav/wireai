"""
Restore pre-cleanup VoxPrime tree from _recovered + transcript patches.
Run: python scripts/full_pre_cleanup_restore.py
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REC = ROOT / "_recovered"
TRANSCRIPT = Path(
    r"C:\Users\gopig\.cursor\projects\c-Personal-stuff-Coding\agent-transcripts"
    r"\93dfba81-c471-46e1-87ed-6aa48fd45992\93dfba81-c471-46e1-87ed-6aa48fd45992.jsonl"
)

MODULE_MAP = {
    "agent_safety.py": "voxprime/core/agent_safety.py",
    "thinking_display.py": "voxprime/core/thinking_display.py",
    "stdin_broker.py": "voxprime/core/stdin_broker.py",
    "shell_runner.py": "voxprime/core/shell_runner.py",
    "terminal_activity.py": "voxprime/core/terminal_activity.py",
    "terminal_markdown.py": "voxprime/core/terminal_markdown.py",
    "terminal_preview.py": "voxprime/core/terminal_preview.py",
    "tool_parse.py": "voxprime/core/tool_parse.py",
    "wholefile_parse.py": "voxprime/core/wholefile_parse.py",
    "generation_loop.py": "voxprime/core/generation_loop.py",
    "editor_bridge.py": "voxprime/core/editor_bridge.py",
    "workspace_probe.py": "voxprime/core/workspace_probe.py",
    "workspace_paths.py": "voxprime/core/workspace_paths.py",
    "screenshot.py": "voxprime/core/screenshot.py",
    "file_reader.py": "voxprime/file_reader.py",
    "media_ingest.py": "voxprime/media_ingest.py",
    "prompts.py": "voxprime/agent/prompts.py",
    "prompt_bridge.py": "voxprime/agent/prompt_bridge.py",
    "hub.py": "voxprime/mcp/hub.py",
    "config.py": "voxprime/mcp/config.py",
    "external_server.py": "voxprime/mcp/external_server.py",
    "chat_server.py": "voxprime/web/chat_server.py",
}


def dedupe_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        if out and line == out[-1]:
            continue
        out.append(line)
    return out


def collapse_repeated_defs(lines: list[str]) -> list[str]:
    """Remove repeated VISION_MODEL / _multi_agent_enabled blocks."""
    pattern = [
        'VISION_MODEL = config.VISION_MODEL or os.getenv("VOXPRIME_VISION_MODEL", "").strip()',
        "",
        "def _multi_agent_enabled() -> bool:",
        '    """MVP: single Ollama agent + MCP tools. Set VOXPRIME_MULTI_AGENT=1 to enable teams."""',
        '    return os.getenv("VOXPRIME_MULTI_AGENT", "0").strip().lower() in ("1", "true", "yes")',
    ]
    out: list[str] = []
    i = 0
    n = len(lines)
    seen_vision_block = False
    while i < n:
        if i + len(pattern) <= n and lines[i : i + len(pattern)] == pattern:
            if not seen_vision_block:
                out.extend(pattern)
                seen_vision_block = True
            i += len(pattern)
            continue
        out.append(lines[i])
        i += 1
    return out


def collect_agent_patches() -> list[tuple[str, str]]:
    patches: list[tuple[str, str]] = []
    if not TRANSCRIPT.is_file():
        return patches
    for line in TRANSCRIPT.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        for item in obj.get("message", {}).get("content") or []:
            if not isinstance(item, dict) or item.get("name") != "StrReplace":
                continue
            p = item.get("input", {}).get("path", "")
            pl = p.lower()
            if "agent_with_tools" not in pl and "groundwire_cli" not in pl:
                continue
            old, new = item["input"].get("old_string"), item["input"].get("new_string")
            if old is not None and new is not None:
                patches.append((old, new))
    return patches


def apply_patches_once(text: str, patches: list[tuple[str, str]]) -> tuple[str, int]:
    applied = 0
    for old, new in patches:
        if old in text:
            text = text.replace(old, new, 1)
            applied += 1
    return text, applied


def install_modules() -> None:
    for src_name, dest_rel in MODULE_MAP.items():
        src = REC / src_name
        if not src.is_file():
            print("skip missing module", src_name)
            continue
        dest = ROOT / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    for pkg in ("voxprime/core", "voxprime/agent", "voxprime/mcp", "voxprime/web"):
        init = ROOT / pkg / "__init__.py"
        if not init.exists():
            init.write_text('"""VoxPrime package."""\n', encoding="utf-8")

    # Copy legacy package pieces from groundwire/ if voxprime missing
    gw = ROOT / "groundwire"
    vp = ROOT / "voxprime"
    if gw.is_dir():
        for sub in ("workflows", "tools", "agents", "shortcut_commands", "voice", "config.py", "__init__.py"):
            src = gw / sub
            if not src.exists():
                continue
            dest = vp / sub
            if dest.exists():
                continue
            if src.is_dir():
                shutil.copytree(src, dest)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)


def patch_agent_safety() -> None:
    target = ROOT / "voxprime/core/agent_safety.py"
    if not target.is_file() or not TRANSCRIPT.is_file():
        return
    text = target.read_text(encoding="utf-8")
    patches = []
    for line in TRANSCRIPT.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        for item in obj.get("message", {}).get("content") or []:
            if item.get("name") != "StrReplace":
                continue
            p = item.get("input", {}).get("path", "")
            if "agent_safety" not in p.lower():
                continue
            old, new = item["input"].get("old_string"), item["input"].get("new_string")
            if old and new is not None:
                patches.append((old, new))
    applied = 0
    for old, new in patches:
        if old in text:
            text = text.replace(old, new, 1)
            applied += 1
    target.write_text(text, encoding="utf-8")
    print("agent_safety transcript patches:", applied)


def build_agent_with_tools() -> None:
    clean = REC / "agent_clean.py"
    if not clean.is_file():
        raise SystemExit("Missing _recovered/agent_clean.py")

    lines = dedupe_lines(clean.read_text(encoding="utf-8").splitlines())
    lines = collapse_repeated_defs(lines)
    text = "\n".join(lines) + "\n"

    text = text.replace("python groundwire_cli.py", "python agent_with_tools.py")
    text = text.replace("class GroundwireAgent:", "class AgentWithTools:")
    text = text.replace("GroundwireAgent()", "AgentWithTools()")
    text = text.replace("agent: GroundwireAgent", "agent: AgentWithTools")

    fixes = {
        "max_steps = 8 if self._looks_like_app_fix_request(routing_input) else 5": (
            "max_steps = 8 if self._looks_like_app_fix_request(user_input) else 5"
        ),
        "elif self.crewai_workflow and self._should_use_crewai(routing_input):": (
            "if self.crewai_workflow and self._should_use_crewai(user_input):"
        ),
        "user_input, vision_images = self._prepare_user_message_with_media(routing_input)": (
            "user_input, vision_images = self._prepare_user_message_with_media(user_input)"
        ),
        'print("Groundwire: ", end="", flush=True)': 'print("VoxPrime: ", end="", flush=True)',
        "from groundwire.": "from voxprime.",
    }
    for old, new in fixes.items():
        text = text.replace(old, new)

    patches = collect_agent_patches()
    text, applied = apply_patches_once(text, patches)
    print("agent_with_tools transcript patches applied:", applied)

    # Ensure streaming thinking helper exists
    if "def _stream_assistant_reply(" not in text:
        text = inject_stream_thinking_helper(text)

    if "install_broker" not in text and "async def _repl_reader" not in text:
        text = inject_message_queue(text)

    (ROOT / "agent_with_tools.py").write_text(text, encoding="utf-8")
    print("wrote agent_with_tools.py", len(text.splitlines()), "lines")


def inject_stream_thinking_helper(text: str) -> str:
    helper = '''

THINKING_SPINNER = os.getenv("VOXPRIME_THINKING_SPINNER", "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
_ANSI_ESCAPE = re.compile(r"\\x1b\\[[0-9;]*m")


def _stream_assistant_reply(agent: "AgentWithTools", response_iter) -> str:
    """Stream tokens; show [THOUGHTS] in dim; spinner while model thinks."""
    full = ""
    in_thoughts = False
    thought_buf = ""
    spin_i = 0
    print("VoxPrime: ", end="", flush=True)
    for chunk in response_iter:
        if "message" not in chunk or "content" not in chunk["message"]:
            continue
        piece = chunk["message"]["content"]
        full += piece
        i = 0
        while i < len(piece):
            if not in_thoughts:
                start = piece.find("[THOUGHTS]", i)
                if start == -1:
                    print(piece[i:], end="", flush=True)
                    break
                if start > i:
                    print(piece[i:start], end="", flush=True)
                in_thoughts = True
                i = start + len("[THOUGHTS]")
                print("\\n\\x1b[90m[Thinking]\\x1b[0m ", end="", flush=True)
            else:
                end = piece.find("[/THOUGHTS]", i)
                if end == -1:
                    seg = piece[i:]
                    thought_buf += seg
                    print(seg, end="", flush=True)
                    break
                seg = piece[i:end]
                thought_buf += seg
                print(seg, end="", flush=True)
                print("\\x1b[0m", end="", flush=True)
                in_thoughts = False
                thought_buf = ""
                i = end + len("[/THOUGHTS]")
        spin_i += 1
    print()
    if SHOW_THINKING_BODY:
        blocks = thinking_display.parse_thinking_from_response(full)
        if blocks:
            thinking_display.display_thinking(blocks, full)
    return full

'''
    anchor = "SHOW_THINKING_BODY = "
    idx = text.find(anchor)
    if idx == -1:
        return text + helper
    line_end = text.find("\n", idx)
    return text[: line_end + 1] + helper + text[line_end + 1 :]


def inject_message_queue(text: str) -> str:
    block = '''

def _print_queued(n: int) -> None:
    if n <= 0:
        return
    word = "message" if n == 1 else "messages"
    print(f"\\x1b[90m  ↳ Queued ({n} {word} waiting)\\x1b[0m")


async def _repl_dispatch(agent: AgentWithTools, user_input: str) -> bool:
    if user_input.lower() in ("quit", "exit"):
        await agent.mcp_client.disconnect()
        print("\\nVoxPrime: Goodbye. Standing by when you need me.")
        return False
    if user_input.lower() == "reset":
        agent.reset()
        print("VoxPrime: Conversation reset. How can I help?")
        return True
    user_input = shortcuts(user_input)
    await agent.chat_stream(user_input)
    print()
    return True


async def _repl_worker(agent: AgentWithTools, inbox: asyncio.Queue, state: dict) -> None:
    while True:
        user_input = await inbox.get()
        if user_input is None:
            break
        state["busy"] = True
        try:
            if not await _repl_dispatch(agent, user_input):
                await inbox.put(None)
                break
        except (KeyboardInterrupt, EOFError):
            print("\\n\\nVoxPrime: Session ended.")
            await inbox.put(None)
            break
        finally:
            state["busy"] = False


async def _repl_reader(broker, inbox: asyncio.Queue, state: dict) -> None:
    while True:
        try:
            user_input = (await broker.read_user("You: ")).strip()
        except EOFError:
            await inbox.put(None)
            break
        if not user_input:
            continue
        await inbox.put(user_input)
        waiting = inbox.qsize()
        if state.get("busy") or waiting > 1:
            _print_queued(waiting)

'''
    marker = "# ---------------------------------------------------------------------------\n# Interactive Loop"
    if marker not in text:
        return text + block
    return text.replace(marker, block + marker, 1)


def restore_pyproject_and_env() -> None:
    py = ROOT / "pyproject.toml"
    if py.is_file():
        t = py.read_text(encoding="utf-8")
        t = t.replace('name = "groundwire"', 'name = "voxprime"')
        t = t.replace("groundwire-mcp", "voxprime")
        t = t.replace('packages = ["groundwire"]', 'packages = ["voxprime"]')
        if "[tool.hatch.build.targets.wheel]" not in t:
            t += "\n[tool.hatch.build.targets.wheel]\npackages = [\"voxprime\"]\n"
        py.write_text(t, encoding="utf-8")

    env_ex = ROOT / ".env.example"
    if env_ex.is_file():
        t = env_ex.read_text(encoding="utf-8")
        t = t.replace("Groundwire", "VoxPrime").replace("GROUNDWIRE_", "VOXPRIME_")
        env_ex.write_text(t, encoding="utf-8")

    mcp_ex = ROOT / ".groundwire/mcp.json.example"
    vp_dir = ROOT / ".voxprime"
    vp_dir.mkdir(exist_ok=True)
    if mcp_ex.is_file():
        shutil.copy2(mcp_ex, vp_dir / "mcp.json.example")


def main() -> None:
    install_modules()
    patch_agent_safety()
    build_agent_with_tools()
    restore_pyproject_and_env()
    # patch chat_stream to use _stream_assistant_reply if still raw loop
    agent_path = ROOT / "agent_with_tools.py"
    t = agent_path.read_text(encoding="utf-8")
    old_loop = '''            print("VoxPrime: ", end="", flush=True)
            for chunk in response:
                if "message" in chunk and "content" in chunk["message"]:
                    content = chunk["message"]["content"]
                    full_response += content
                    print(content, end="", flush=True)
            print()'''
    new_loop = '''            full_response = _stream_assistant_reply(self, response)'''
    if old_loop in t:
        t = t.replace(old_loop, new_loop)
        agent_path.write_text(t, encoding="utf-8")
        print("patched chat_stream to use _stream_assistant_reply")
    print("Restore complete. Run: python agent_with_tools.py")


if __name__ == "__main__":
    main()
