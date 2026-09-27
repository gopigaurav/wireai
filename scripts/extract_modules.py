"""One-off extraction helper (safe to keep for refactors)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
agent = (ROOT / "agent_with_tools.py").read_text(encoding="utf-8").splitlines()

start = next(i for i, l in enumerate(agent) if l.startswith("SYSTEM_PROMPT"))
end = next(i for i, l in enumerate(agent) if i > start and "# MCP Client" in l) - 1
(ROOT / "voxprime/agent").mkdir(parents=True, exist_ok=True)
(ROOT / "voxprime/agent/prompts.py").write_text(
    '"""System prompts for the console agent."""\n\n' + "\n".join(agent[start : end + 1]) + "\n",
    encoding="utf-8",
)

start = next(i for i, l in enumerate(agent) if "class MCPClient:" in l)
end = next(i for i, l in enumerate(agent) if i > start and "# CrewAI Integration" in agent[i])
header = '''"""In-process tool execution (bridge for local tools)."""

import httpx
import os

from voxprime.config import config
from voxprime.core.file_reader import read_file_chunked_text
from voxprime.core.media_ingest import (
    extract_document_text,
    fetch_webpage_markdown,
    ingest_paths,
    model_supports_vision,
)

LLM_MODEL = config.LLM_MODEL


'''
body = "\n".join(agent[start:end])
body = body.replace("class MCPClient:", "class BuiltinToolExecutor:")
(ROOT / "voxprime/mcp").mkdir(parents=True, exist_ok=True)
(ROOT / "voxprime/mcp/builtin_tools.py").write_text(header + body + "\n", encoding="utf-8")
print("extracted prompts and builtin_tools")
