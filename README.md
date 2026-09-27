# Groundwire

Local coding agent: **Ollama** + **MCP tools**, terminal REPL, optional **VS Code / Cursor** sidebar chat.

## Quick start

```powershell
# 1. Ollama
ollama pull qwen3.5:latest
ollama serve

# 2. Install
cd groundwire   # this repository root
pip install -e .
cp .env.example .env

# 3. CLI agent
python groundwire_cli.py
```

## Chat server + IDE

```powershell
python -m groundwire.web.chat_server
```

Install the extension from `vscode-extension/` (see [docs/IDE_INTEGRATION.md](docs/IDE_INTEGRATION.md)).

## MCP SSE server (optional)

```powershell
python server.py
```

## Layout

| Path | Purpose |
|------|---------|
| `groundwire_cli.py` | Interactive agent (streaming, tools, permissions) |
| `groundwire/` | Python package (`core`, `mcp`, `agent`, `web`, …) |
| `server.py` | FastMCP SSE entry |
| `vscode-extension/` | Editor sidebar chat |
| `docs/` | Integration and layout |
| `.groundwire/` | Local config (gitignored): `mcp.json`, `active_file`, `editor_context.json` |

## Environment

See `.env.example`. Common variables:

- `LLM_MODEL`, `OLLAMA_HOST`
- `GROUNDWIRE_VISION_MODEL` — for image attachments
- `GROUNDWIRE_MULTI_AGENT=1` — optional CrewAI / custom team routing

## Tests

```powershell
python -m pytest tests/ -q
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Add your license file before public contribution (e.g. MIT).
