# TUI removal backlog (restore later)

Removed on user request to return to classic terminal REPL. Pre-TUI features (queue, shell streaming, web chat, markdown terminal, etc.) were kept.

## Deleted paths

| Path | Role |
|------|------|
| `voxprime/tui/chat_app.py` | Textual app: history log, bottom input, worker bridge to `chat_stream` |
| `voxprime/tui/prompt_bridge.py` | `is_tui_active()`, `tui_read_choice()` for permissions while TUI runs |
| `voxprime/tui/__init__.py` | Package marker |

## Dependency

- Removed from `pyproject.toml`: `textual>=0.47.0`
- `uv.lock` may still list `textual` until `uv lock` is run

## `agent_with_tools.py` (revert these to restore TUI)

1. **`main()`** — Default launch was TUI unless `--classic-repl` or `VOXPRIME_CLASSIC_REPL=1`. Restore:
   - `--tui` / `--classic-repl` flags
   - `run_chat_tui(...)` vs `asyncio.run(interactive_loop(...))`

2. **Agent printing hooks** (for TUI log instead of raw `print`):
   - `terminal_sink` / `terminal_sink_flush` on the agent instance
   - `_safe_print` routing through `terminal_sink` when set
   - `_show_thinking_body()` returning `False` when TUI active (compact thinking in status line)

3. **Stream end** — `terminal_sink_flush()` after assistant turn

4. **Startup banner** — Line about “Default UI: Claude-style TUI…”

## `voxprime/core/agent_safety.py`

- `PermissionManager._read_choice`: branch to `tui_read_choice` when `is_tui_active()`

## `agent_with_tools._confirm_destructive_async`

- Same TUI branch for `Proceed? (y/n)` prompts

## TUI design notes (from prior session)

- Textual `ChatApp` with `#log`, `#input`, `#status`
- Worker task called `_repl_dispatch` / `chat_stream` with sinks wired
- Known bug at removal time: `NoMatches('#status')` on shutdown if status widget missing
- Thinking in log looked like “one word per line” — fix was to disable full thinking body when sink set

## Restore checklist

1. `pip install textual` / re-add to `pyproject.toml`
2. Restore `voxprime/tui/*` from git history or this doc + transcript
3. Re-wire `main()`, sinks, and prompt_bridge in safety + destructive confirm
4. Test: permissions during agent run, queue + TUI input, Ctrl+C cleanup

## Git

If committed before removal, recover with:

```bash
git log --oneline -- voxprime/tui/
git show <commit>:voxprime/tui/chat_app.py
```
