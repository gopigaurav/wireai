"""Restore Groundwire CLI + core modules from _recovered + transcript patches."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REC = ROOT / "_recovered"
TRANSCRIPT = Path(
    r"C:\Users\gopig\.cursor\projects\c-Personal-stuff-Coding\agent-transcripts"
    r"\93dfba81-c471-46e1-87ed-6aa48fd45992\93dfba81-c471-46e1-87ed-6aa48fd45992.jsonl"
)

MAP = {
    "agent_safety.py": "groundwire/core/agent_safety.py",
    "thinking_display.py": "groundwire/core/thinking_display.py",
    "stdin_broker.py": "groundwire/core/stdin_broker.py",
    "shell_runner.py": "groundwire/core/shell_runner.py",
    "terminal_activity.py": "groundwire/core/terminal_activity.py",
    "terminal_markdown.py": "groundwire/core/terminal_markdown.py",
    "terminal_preview.py": "groundwire/core/terminal_preview.py",
    "tool_parse.py": "groundwire/core/tool_parse.py",
    "wholefile_parse.py": "groundwire/core/wholefile_parse.py",
    "generation_loop.py": "groundwire/core/generation_loop.py",
    "editor_bridge.py": "groundwire/core/editor_bridge.py",
    "workspace_probe.py": "groundwire/core/workspace_probe.py",
    "workspace_paths.py": "groundwire/core/workspace_paths.py",
    "screenshot.py": "groundwire/core/screenshot.py",
    "file_reader.py": "groundwire/file_reader.py",
    "media_ingest.py": "groundwire/media_ingest.py",
    "prompts.py": "groundwire/agent/prompts.py",
    "prompt_bridge.py": "groundwire/agent/prompt_bridge.py",
    "hub.py": "groundwire/mcp/hub.py",
    "config.py": "groundwire/mcp/config.py",
    "external_server.py": "groundwire/mcp/external_server.py",
    "chat_server.py": "groundwire/web/chat_server.py",
}


def rebrand(text: str) -> str:
    text = text.replace("from voxprime.", "from groundwire.")
    text = text.replace("import voxprime.", "import groundwire.")
    text = text.replace("voxprime-stdin", "groundwire-stdin")
    text = text.replace("voxprime_shell_hooks", "groundwire_shell_hooks")
    text = text.replace(".voxprime/", ".groundwire/")
    text = text.replace('".voxprime"', '".groundwire"')
    text = text.replace("VoxPrime", "Groundwire")
    return text


def dedupe_block_lines(lines: list[str], block: int = 11) -> list[str]:
    """Drop consecutive repeated blocks (patch-replay corruption)."""
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        chunk = lines[i : i + block]
        j = i + block
        while j + block <= n and lines[j : j + block] == chunk:
            j += block
        out.extend(chunk)
        i = j
    return out


def apply_str_replace_patches(path_contains: str, target: Path) -> int:
    if not TRANSCRIPT.is_file() or not target.is_file():
        return 0
    text = target.read_text(encoding="utf-8")
    patches: list[tuple[str, str]] = []
    for line in TRANSCRIPT.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        for item in obj.get("message", {}).get("content") or []:
            if not isinstance(item, dict) or item.get("name") != "StrReplace":
                continue
            p = item.get("input", {}).get("path", "")
            if path_contains not in p.lower():
                continue
            old, new = item["input"].get("old_string"), item["input"].get("new_string")
            if old and new is not None:
                patches.append((rebrand(old), rebrand(new)))
    applied = 0
    for old, new in patches:
        if old in text:
            text = text.replace(old, new, 1)
            applied += 1
    target.write_text(text, encoding="utf-8")
    return applied


def main() -> None:
    for src_name, dest_rel in MAP.items():
        src = REC / src_name
        if not src.is_file():
            print("skip missing", src_name)
            continue
        dest = ROOT / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(rebrand(src.read_text(encoding="utf-8")), encoding="utf-8")
        print("installed", dest_rel)

    for pkg in ("groundwire/core", "groundwire/agent", "groundwire/mcp", "groundwire/web"):
        init = ROOT / pkg / "__init__.py"
        if not init.exists():
            init.write_text('"""Groundwire package."""\n', encoding="utf-8")

    n = apply_str_replace_patches("agent_safety", ROOT / "groundwire/core/agent_safety.py")
    print("agent_safety patches", n)

    clean = REC / "agent_clean.py"
    if not clean.is_file():
        raise SystemExit("missing _recovered/agent_clean.py — run recovery first")

    lines = dedupe_block_lines(clean.read_text(encoding="utf-8").splitlines())
    text = rebrand("\n".join(lines) + "\n")
    text = text.replace(
        "max_steps = 8 if self._looks_like_app_fix_request(routing_input) else 5",
        "max_steps = 8 if self._looks_like_app_fix_request(user_input) else 5",
    )
    text = text.replace("class AgentWithTools:", "class GroundwireAgent:")
    text = text.replace("AgentWithTools()", "GroundwireAgent()")
    text = text.replace("agent: AgentWithTools", "agent: GroundwireAgent")

    vision_block = (
        "            if VISION_MODEL:\n"
        '                print(f"[OK] Vision model (images/screenshots): {VISION_MODEL}")\n'
        "            elif not model_supports_vision(LLM_MODEL):\n"
        "                print(\n"
        '                    "[Tip] For screenshots, set VOXPRIME_VISION_MODEL=qwen2.5vl:latest "\n'
        '                    "(ollama pull qwen2.5vl) or use a vision-capable LLM_MODEL"\n'
        "                )\n"
    )
    while text.count(vision_block) > 1:
        text = text.replace(vision_block, "", 1)

    (ROOT / "groundwire_cli.py").write_text(text, encoding="utf-8")
    print("wrote groundwire_cli.py", len(text.splitlines()), "lines")


if __name__ == "__main__":
    main()
