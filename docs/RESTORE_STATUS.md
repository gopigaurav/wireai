# Restore status (pre-cleanup / VoxPrime)

## Restored from chat transcript (`_recovered/`)

- **`agent_with_tools.py`** (~1.7k lines) — main CLI with permissions, media, editor context hooks, streaming, tool loop
- **`voxprime/`** package: `core/`, `agent/`, `mcp/`, `web/`, plus `workflows/`, `tools/`, etc. from git
- **Thinking**: `[THOUGHTS]…[/THOUGHTS]` streamed in gray + `[LLM Thinking]` summary (`VOXPRIME_SHOW_THINKING=1`)
- **Message queue**: `voxprime/core/stdin_broker.py` while the agent runs
- **Live shell**: `voxprime/core/shell_runner.py`
- **VS Code extension** files (from recovery) under `vscode-extension/`
- **`.voxprime/mcp.json.example`**

## Run

```powershell
cd "...\groundwire"   # repo folder on disk (rename to voxprime locally if you prefer)
python agent_with_tools.py
```

MCP server: `python server.py` or `uv run voxprime`

## Re-run full restore

```powershell
python scripts/full_pre_cleanup_restore.py
```

## Not guaranteed bit-identical

The original ~2.2k-line file was never committed to git. Recovery merges transcript snapshots + patches. If something is still missing, check **Cursor Local History** on `agent_with_tools.py` or tell us which command/feature to re-add.
