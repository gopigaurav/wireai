# VoxPrime in VS Code / Cursor

You **cannot** replace Cursor’s built-in AI chat or Copilot’s backend with VoxPrime. Those products use their own models and UI.

You **can** get a Copilot/Cursor-*style* sidebar chat that talks to your local VoxPrime agent (Ollama + tools) in both **VS Code** and **Cursor**, because Cursor supports VS Code extensions.

## Architecture

```
┌─────────────────────┐     POST /api/chat (NDJSON stream)     ┌──────────────────┐
│ VS Code / Cursor    │ ──────────────────────────────────────►│ chat_server.py   │
│ extension (sidebar) │     + ide_context: active file, selection│ agent_with_tools │
└─────────────────────┘                                        └────────┬─────────┘
                                                                         │
                                                                         ▼
                                                                  Ollama + MCP tools
                                                                  (read_file, run_command, …)
```

## Quick start

1. **Start the agent API** (from the voxprime repo root, same folder as `agent_with_tools.py`):

   ```powershell
   cd "C:\Personal stuff\Coding\Kubernetes\voice assistent\voxprime"
   python -m voxprime.web.chat_server
   ```

2. **Install the extension** (one-time):

   ```powershell
   cd vscode-extension
   npm install -g @vscode/vsce   # optional, for packaging
   ```

   In VS Code or Cursor: **Extensions** → **…** → **Install from VSIX…**  
   Or for development: **F5** → “Run Extension” (opens Extension Development Host).

   Dev load: open the `vscode-extension` folder → **Run and Debug** → **Run Extension**.

3. Open the **VoxPrime** view in the activity bar (icon) or run command **VoxPrime: Focus Chat**.

4. Chat in the sidebar; the extension sends the **active editor file** and **selection** with each message.

## Settings

| Setting | Default | Purpose |
|--------|---------|---------|
| `voxprime.serverUrl` | `http://127.0.0.1:8765` | Chat API base URL |
| `voxprime.cwd` | (empty) | Working directory for the server process; set to your repo root if tools should run there |

Run `chat_server` with `cd` set to the project you are editing so `read_file` / `run_command` paths match.

## What you get vs full Cursor

| Feature | Cursor native | VoxPrime extension |
|--------|---------------|-------------------|
| Sidebar chat | Yes | Yes |
| Streamed replies | Yes | Yes (NDJSON) |
| Active file context | Yes | Yes (via `ide_context`) |
| Selection in prompt | Yes | Yes |
| @-mentions / @codebase | Yes | Not yet |
| Inline completions | Yes | No |
| Replace Cursor’s model | No | N/A |

## Alternatives

- **Browser only**: `python -m voxprime.web.chat_server` — no IDE context unless you use `/file`.
- **Continue / Cline**: Point at an OpenAI-compatible HTTP API; you would need a thin adapter around VoxPrime (not shipped yet).
- **Env var bridge**: Set `VSCODE_CURRENT_FILE` / `VOXPRIME_ACTIVE_FILE` in a terminal task — works without the extension but is manual.
- **Editor bridge (CLI + Cursor)**: When the VoxPrime extension is enabled, it writes `.voxprime/editor_context.json` on every tab focus. The terminal agent reads this for prompts like “what is this file doing?” (same idea as Cursor’s active tab).

## Permissions

Tool approvals (`run_command`, file writes) still appear in the **terminal where `chat_server` runs**. Approve there with **A** / **y**, or run the CLI with `/no-confirm` for local dev only.
