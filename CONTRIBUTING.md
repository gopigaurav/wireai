# Contributing to Groundwire

## Setup

1. Python 3.11+
2. [Ollama](https://ollama.com/) running locally
3. `pip install -e ".[dev]"` or `pip install -e .` from the repo root
4. Copy `.env.example` → `.env`

## Project structure

- **`groundwire_cli.py`** — CLI entry; keep orchestration here or in `groundwire/` as it grows.
- **`groundwire/`** — importable package only (no repo-root scripts inside).
- **`tests/`** — pytest; add tests for parsers and safety logic when you change them.
- **`vscode-extension/`** — Node-free extension (plain JS); test with **Run Extension** in VS Code/Cursor.

## Code style

- Match existing imports: `from groundwire.core...`
- User-local state lives under **`.groundwire/`**, never committed.
- Tool permissions and destructive confirms stay in `groundwire/core/agent_safety.py`.

## Pull requests

1. One logical change per PR when possible.
2. Run `python -m pytest tests/ -q` if you touched parsers or agent safety.
3. Update `docs/` if you change CLI flags, env vars, or IDE integration.

## Rename / branding

Product name: **Groundwire**. Python package: **`groundwire`**. Config dir: **`.groundwire/`**.
