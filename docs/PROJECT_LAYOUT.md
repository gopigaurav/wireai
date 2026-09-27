# VoxPrime project layout

```
voxprime/                          # Python package
  agent/                           # Console agent prompts & (future) runtime
    prompts.py                     # build_system_prompt() — core + ask/diagram addenda
  core/                            # Shared libraries (import only from here)
    agent_safety.py                # Permissions, undo, dry-run
    file_reader.py                 # Chunked file reads
    media_ingest.py                # PDF/DOCX/web/images
    thinking_display.py
  mcp/                             # MCP integration
    config.py                      # Load .voxprime/mcp.json
    external_server.py             # stdio MCP subprocess (git, …)
    builtin_tools.py               # In-process tool implementations
    hub.py                         # MCPHub = builtin + external
  tools/                           # FastMCP server tool registrations
  workflows/                       # CrewAI / LangGraph
  config.py

agent_with_tools.py                # CLI entry (interactive agent)
server.py                          # FastMCP SSE server entry
.voxprime/
  mcp.json.example                 # Copy to mcp.json to customize MCP servers
  active_file                      # Session “current file” path
scripts/                           # Maintenance / extract helpers
```

## Git MCP (default)

On agent start, `MCPHub` loads `.voxprime/mcp.json` or uses a default **git** server:

`uvx mcp-server-git --repository <workspace>`

Git **write** tools (`git_add`, `git_commit`, …) use the same allow/skip prompts as shell commands.
