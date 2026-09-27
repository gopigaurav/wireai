"""Remove extracted blocks from agent_with_tools.py and add imports."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "agent_with_tools.py"
lines = path.read_text(encoding="utf-8").splitlines()

start_prompt = next(i for i, l in enumerate(lines) if l.startswith("SYSTEM_PROMPT"))
end_prompt = next(i for i, l in enumerate(lines) if i > start_prompt and "# MCP Client" in l)

start_mcp = next(i for i, l in enumerate(lines) if "class MCPClient:" in l)
end_mcp = next(i for i, l in enumerate(lines) if i > start_mcp and "# CrewAI Integration" in l)

new_lines = lines[:start_prompt] + lines[end_mcp:]

imports_add = [
    "from voxprime.agent.prompts import SYSTEM_PROMPT",
    "from voxprime.mcp import MCPHub, GIT_WRITE_TOOLS",
]

# Insert after config import block (after media_ingest imports)
insert_at = next(i for i, l in enumerate(new_lines) if l.startswith("from voxprime.core.media_ingest"))
insert_at += 1
while insert_at < len(new_lines) and new_lines[insert_at].strip().startswith(")"):
    insert_at += 1
for imp in reversed(imports_add):
    new_lines.insert(insert_at + 1, imp)

text = "\n".join(new_lines) + "\n"
text = text.replace("MCPClient(", "MCPHub(")
text = text.replace("self.mcp_client = MCPClient", "self.mcp_client = MCPHub")
# list_tool_names method in AgentWithTools - replace body to delegate
path.write_text(text, encoding="utf-8")
print("patched agent_with_tools.py")
