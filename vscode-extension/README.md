# VoxPrime Chat (VS Code / Cursor)

Sidebar chat that streams from your local `python -m voxprime.web.chat_server`.

## Development

1. Start the server from the **voxprime repo root** (where `agent_with_tools.py` lives).
2. Open this folder in VS Code or Cursor.
3. Run **Run and Debug** → **Run Extension** (create `.vscode/launch.json` if missing — “Run Extension” from command palette).
4. In the Extension Development Host window, open the **VoxPrime** activity bar icon.

## launch.json (optional)

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Run Extension",
      "type": "extensionHost",
      "request": "launch",
      "args": ["--extensionDevelopmentPath=${workspaceFolder}"]
    }
  ]
}
```

See [docs/IDE_INTEGRATION.md](../docs/IDE_INTEGRATION.md) for the full picture.
