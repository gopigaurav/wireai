"""
VoxPrime Agent with MCP Tool Integration and Real-time Streaming.

Connects to the MCP server (SSE) for tools while chatting with Ollama.
Includes example.py-style safety: undo, dry-run, permissions, destructive confirm.

Run:
  uv run python agent_with_tools.py
  python agent_with_tools.py --no-confirm
  python agent_with_tools.py --dry-run
"""

import asyncio
import httpx
import os
import sys
import json
import re
import nest_asyncio
from dotenv import load_dotenv

# Fix Windows console Unicode encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
from voxprime.shortcut_commands.shortcut import shortcuts
import ollama

from voxprime.config import config
from voxprime.core.agent_safety import (
    GIT_WRITE_TOOLS,
    DryRunManager,
    PermissionManager,
    SessionStats,
    find_similar_file,
    format_tool_description,
    get_undo_manager,
    is_destructive_tool,
)
from voxprime.core.thinking_display import thinking_display
from voxprime.core.file_reader import (
    DEFAULT_LINES_PER_CHUNK,
    load_persisted_active_file,
    persist_active_file,
    read_file_chunked_text,
)
from voxprime.core.media_ingest import (
    classify_path,
    enrich_prompt_with_media,
    extract_document_text,
    fetch_webpage_markdown,
    model_supports_vision,
)
from voxprime.agent.prompts import (
    FILES_IN_CHAT_PREFIX,
    build_system_prompt,
    user_wants_diagram_mode,
)
from voxprime.mcp import MCPHub
from voxprime.core.tool_parse import (
    FILE_WRITE_TOOLS,
    extract_tool_calls,
    is_tool_json_attempt,
)
from voxprime.core.terminal_preview import (
    format_file_tool_preview,
    format_tool_calls_collapsed,
    looks_like_tool_json_stream,
)
from voxprime.core.wholefile_parse import parse_wholefile_writes, resolve_write_path
from voxprime.core.generation_loop import (
    DEFAULT_MAX_REFLECTIONS,
    REFLECTION_TRUNCATED_PROSE,
    REFLECTION_TRUNCATED_TOOL,
    REFLECTION_WHOLEFILE_HINT,
    TOKEN_LIMIT_USER_HINT,
)
from voxprime.core.terminal_activity import TurnActivityLog, describe_tool_activity, spinner_char
from voxprime.core.terminal_markdown import TerminalStreamFormatter

load_dotenv()

# Cap tool output in chat context (full agent_with_tools.py was blowing the window)
TOOL_RESULT_MAX_CHARS = int(os.getenv("VOXPRIME_TOOL_RESULT_MAX_CHARS", "12000"))
SHOW_THINKING_BODY = os.getenv("VOXPRIME_SHOW_THINKING", "1").strip() not in ("0", "false", "no")
THINKING_SPINNER = os.getenv("VOXPRIME_THINKING_SPINNER", "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

# Prompts that mean "the file open in the editor / session active file"
_CURRENT_FILE_RE = re.compile(
    r"(?:"
    r"\bcurrent\s+file\b|\bthis\s+file\b|"
    r"\bwhat\s+(?:is|does)\s+(?:this|the)\s+file\b|"
    r"\bwhat\s+(?:is|'?s)\s+this\s+file\s+doing\b|"
    r"\bwhat\s+does\s+this\s+file\s+do\b|"
    r"\bfile\s+i\s*'?m\s+viewing\b|\bfile\s+iam\s+viewing\b|\bfile\s+i\s+am\s+viewing\b|"
    r"\b(?:analy[sz]e|review|explain|read)\s+(?:the\s+)?(?:current\s+)?file\b|"
    r"\b(?:analy[sz]e|review)\s+(?:what\s+)?i\s*'?m\s+viewing\b|"
    r"\bviewing\s+(?:the\s+)?file\b|\bthe\s+file\s+i\s*'?m\s+viewing\b"
    r")",
    re.IGNORECASE,
)
# ---------------------------------------------------------------------------
# CrewAI Integration via Workflows
# ---------------------------------------------------------------------------

try:
    from voxprime.workflows.crewai_langgraph_workflow import create_integrated_workflow
    WORKFLOW_AVAILABLE = True
except ImportError:
    WORKFLOW_AVAILABLE = False
    create_integrated_workflow = None

# Custom multi-agent system (no CrewAI dependencies)
try:
    import sys
    from pathlib import Path
    # Add multi-agent-custom to path
    multi_agent_path = Path(__file__).parent.parent / "multi-agent-custom"
    if multi_agent_path.exists():
        sys.path.insert(0, str(multi_agent_path))
    from agents import AgentRouter
    CUSTOM_AGENTS_AVAILABLE = True
except ImportError:
    CUSTOM_AGENTS_AVAILABLE = False
    AgentRouter = None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/sse")
LLM_MODEL = config.LLM_MODEL
LLM_BASE_URL = config.LLM_BASE_URL
VISION_MODEL = config.VISION_MODEL or os.getenv("VOXPRIME_VISION_MODEL", "").strip()


def _multi_agent_enabled() -> bool:
    """MVP: single Ollama agent + MCP tools. Set VOXPRIME_MULTI_AGENT=1 to enable teams."""
    return os.getenv("VOXPRIME_MULTI_AGENT", "0").strip().lower() in ("1", "true", "yes")

# Special command to trigger CrewAI team
CREWAI_TRIGGER_PHRASES = [
    "team_collaborate",
    "delegate to team",
    "use the team",
    "/team",
]

# Special command to trigger Custom multi-agent team
CUSTOM_TEAM_TRIGGER_PHRASES = [
    "/custom-team",
]

# Special command to trigger Collaborative multi-agent mode (parallel execution)
COLLABORATIVE_TEAM_TRIGGER_PHRASES = [
    "/custom-multi-simul",
    "/collaborative",
]

# Special command to trigger Executor agent (run code + test + fix loop)
EXECUTOR_TRIGGER_PHRASES = [
    "/execute",
    "/run-code",
    "/test-code",
]

# CrewAI Integration via Workflows Module
# ---------------------------------------------------------------------------

class CrewAIWorkflow:
    """
    Wrapper for the CrewAI workflow from voxprime.workflows.
    Provides direct access without HTTP overhead.
    """

    def __init__(self):
        if not WORKFLOW_AVAILABLE:
            raise ImportError("CrewAI workflow not available")
        self.workflow = create_integrated_workflow()
        print(f"[OK] CrewAI workflow loaded from voxprime.workflows")

    def execute(self, task_description: str) -> str:
        """
        Execute a task using the CrewAI + LangGraph workflow.

        Args:
            task_description: What needs to be done

        Returns:
            The workflow output
        """
        import nest_asyncio
        from langchain_core.messages import HumanMessage

        # Allow running async in already running event loop
        try:
            nest_asyncio.apply()
        except:
            pass

        print(f"\n[CrewAI Workflow] Processing: {task_description[:50]}...")

        try:
            # Create initial state
            initial_state = {
                "messages": [HumanMessage(content=task_description)],
                "current_agent": "",
                "task_description": task_description,
                "task_output": "",
                "context": {},
                "needs_review": False,
            }

            # Run workflow synchronously
            result = self.workflow.invoke(initial_state)

            # Extract response
            messages = result.get("messages", [])
            for msg in reversed(messages):
                if hasattr(msg, 'content'):
                    return f"[{result.get('current_agent', 'TEAM')}] {msg.content}"

            return result.get("task_output", "Task completed.")

        except Exception as e:
            return f"[Error] CrewAI workflow failed: {str(e)}"


# ---------------------------------------------------------------------------
# Agent with Tool Support and Streaming
# ---------------------------------------------------------------------------

class AgentWithTools:
    """Console agent that can call MCP tools with real-time streaming."""

    def __init__(self):
        self.client = None
        self.mcp_client = None
        self.crewai_workflow = None
        self.custom_agent_router = None
        self.context = []
        self.created_files = {}  # Track files created in this conversation: {filename: is_continuation}
        # example.py-style safety layer (undo, dry-run, permissions)
        self.undo = get_undo_manager()
        self.dry_run = DryRunManager()
        self.permissions = PermissionManager()
        self.session_stats = SessionStats()
        self.turn_activity = TurnActivityLog()
        self.web_event_sink = None
        self.skip_confirm = False
        # Live IDE env beats stale .voxprime/active_file (Cursor / VS Code terminal)
        self.session_active_file = (
            self._active_editor_file() or load_persisted_active_file()
        )
        self.multi_agent_enabled = _multi_agent_enabled()
        self._init_llm()
        self._init_mcp()
        if self.multi_agent_enabled:
            self._init_crewai()
            self._init_custom_agents()
        else:
            self.crewai_workflow = None
            self.custom_agent_router = None

    def _init_llm(self):
        """Initialize Ollama client."""
        try:
            self.client = ollama.Client(host=LLM_BASE_URL)
            self.context.append({"role": "system", "content": build_system_prompt()})
            print(f"[OK] Connected to Ollama ({LLM_BASE_URL})")
            print(f"[OK] Using model: {LLM_MODEL}")
            if VISION_MODEL:
                print(f"[OK] Vision model (images/screenshots): {VISION_MODEL}")
            elif not model_supports_vision(LLM_MODEL):
                print(
                    "[Tip] For screenshots, set VOXPRIME_VISION_MODEL=qwen2.5vl:latest "
                    "(ollama pull qwen2.5vl) or use a vision-capable LLM_MODEL"
                )
        except ImportError:
            print("[ERROR] ollama package not installed.")
            sys.exit(1)
        except Exception as e:
            print(f"[ERROR] Failed to connect to Ollama: {e}")
            sys.exit(1)

    def _init_mcp(self):
        """Initialize MCP client."""
        self.mcp_client = MCPHub(MCP_SERVER_URL)

    def _init_crewai(self):
        """Initialize CrewAI workflow from voxprime.workflows."""
        if WORKFLOW_AVAILABLE:
            try:
                self.crewai_workflow = CrewAIWorkflow()
            except Exception as e:
                print(f"[WARN] CrewAI workflow not available: {e}")
                self.crewai_workflow = None
        else:
            print("[WARN] CrewAI workflow not imported - multi-agent disabled")
            self.crewai_workflow = None

    def _strip_ansi(self, text: str) -> str:
        return _ANSI_ESCAPE.sub("", text).replace("\r", "")

    def _emit_web(self, event: dict) -> None:
        sink = self.web_event_sink
        if not sink:
            return
        try:
            sink(event)
        except Exception:
            pass

    def _safe_print(self, text: str, end: str = "", flush: bool = True) -> None:
        try:
            print(text, end=end, flush=flush)
        except UnicodeEncodeError:
            print(
                text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
                    sys.stdout.encoding or "utf-8", errors="replace"
                ),
                end=end,
                flush=flush,
            )

    def _chunk_message_parts(self, chunk) -> tuple[str, str]:
        """Extract thinking + content from an Ollama stream chunk (dict or ChatResponse)."""
        message = None
        if hasattr(chunk, "message"):
            message = chunk.message
        elif isinstance(chunk, dict):
            message = chunk.get("message")
        if message is None:
            return "", ""

        def _field(obj, key: str) -> str:
            if isinstance(obj, dict):
                val = obj.get(key)
            else:
                val = getattr(obj, key, None)
            return val if isinstance(val, str) else (str(val) if val else "")

        return _field(message, "thinking"), _field(message, "content")

    def _messages_with_vision(self, messages: list, vision_images: list[str] | None) -> list:
        if not vision_images:
            return messages
        out = [dict(m) for m in messages]
        for i in range(len(out) - 1, -1, -1):
            if out[i].get("role") == "user":
                out[i] = {**out[i], "images": vision_images}
                break
        return out

    def _parse_attach_command(self, user_input: str) -> tuple[str, list[str]]:
        """`/attach a.pdf b.png -- question` or `/attach a.pdf question`."""
        if not user_input.strip().lower().startswith("/attach "):
            return user_input, []
        rest = user_input.strip()[8:].strip()
        if not rest:
            return "Please describe what to do with the attachments.", []

        if " -- " in rest:
            path_part, question = rest.split(" -- ", 1)
            paths = [p.strip() for p in path_part.split(",") if p.strip()]
            return question.strip() or "Analyze the attached files.", paths

        tokens = rest.split()
        paths: list[str] = []
        question_tokens: list[str] = []
        for tok in tokens:
            resolved = self._resolve_workspace_file(tok) or (
                tok if os.path.isfile(tok) else None
            )
            if resolved and os.path.isfile(resolved) and classify_path(resolved) != "unknown":
                paths.append(resolved)
            else:
                question_tokens.append(tok)
        question = " ".join(question_tokens) if question_tokens else "Analyze the attached files."
        return question, paths

    def _prepare_user_message_with_media(self, user_input: str) -> tuple[str, list[str]]:
        user_input, attach_paths = self._parse_attach_command(user_input)
        text, images = enrich_prompt_with_media(
            user_input,
            LLM_MODEL,
            extra_paths=attach_paths,
            fetch_urls=True,
        )
        vision_ok = model_supports_vision(LLM_MODEL) or bool(VISION_MODEL)
        if images and not vision_ok:
            print(
                f"\n[Note] Images attached but `{LLM_MODEL}` may not support vision. "
                "Set VOXPRIME_VISION_MODEL=qwen2.5vl:latest (ollama pull qwen2.5vl).\n"
            )
        return text, images

    def _chat_model_for_turn(self, vision_images: list[str] | None) -> str:
        if vision_images and VISION_MODEL:
            return VISION_MODEL
        if vision_images and model_supports_vision(LLM_MODEL):
            return LLM_MODEL
        return LLM_MODEL

    async def _stream_ollama_response(
        self,
        messages: list,
        label: str = "VoxPrime",
        options: dict | None = None,
        vision_images: list[str] | None = None,
    ) -> tuple[str, str]:
        """
        Stream assistant reply to the terminal.
        Returns (full_content, full_thinking) including Ollama native `message.thinking`.
        """
        opts = options or {
            "num_predict": 8192,
            "num_ctx": 16384,
            "temperature": 0.7,
        }
        api_messages = self._messages_with_vision(messages, vision_images)
        chat_model = self._chat_model_for_turn(vision_images)
        if vision_images and chat_model != LLM_MODEL:
            self._safe_print(
                f"\x1b[90m[vision] Using {chat_model} for this turn\x1b[0m\n"
            )
        import threading

        loop = asyncio.get_running_loop()
        chunk_queue: asyncio.Queue = asyncio.Queue()
        stream_errors: list[BaseException] = []

        def _ollama_producer() -> None:
            try:
                stream = self.client.chat(
                    model=chat_model,
                    messages=api_messages,
                    stream=True,
                    options=opts,
                )
                for chunk in stream:
                    loop.call_soon_threadsafe(chunk_queue.put_nowait, chunk)
            except BaseException as exc:
                stream_errors.append(exc)
            finally:
                loop.call_soon_threadsafe(chunk_queue.put_nowait, None)

        threading.Thread(
            target=_ollama_producer, daemon=True, name="ollama-stream"
        ).start()

        full_content = ""
        full_thinking = ""
        thinking_marker_open = False
        thinking_body_started = False
        saw_thinking = False
        suppress_tool_json_stream = False
        payload_spin_idx = 0
        md_formatter = TerminalStreamFormatter()

        self._emit_web({"type": "assistant_start", "label": label})
        self._safe_print(f"\n{label}: ", end="")

        def _open_thinking_marker() -> None:
            nonlocal thinking_marker_open
            if not thinking_marker_open:
                spin = THINKING_SPINNER[0] if THINKING_SPINNER else "⠋"
                self._safe_print(f"\n\x1b[33m{spin} Thinking...\x1b[0m", end="")
                self._emit_web({"type": "status", "text": "Thinking…"})
                thinking_marker_open = True

        def _close_thinking_marker() -> None:
            nonlocal thinking_marker_open, thinking_body_started
            if thinking_marker_open:
                self._safe_print("\n\x1b[32m✓\x1b[0m Done thinking.\n")
                self._emit_web({"type": "status", "text": ""})
                thinking_marker_open = False
                thinking_body_started = False

        while True:
            chunk = await chunk_queue.get()
            if chunk is None:
                break
            thinking, content = self._chunk_message_parts(chunk)
            if thinking:
                saw_thinking = True
                _open_thinking_marker()
                full_thinking += thinking
                if SHOW_THINKING_BODY:
                    if not thinking_body_started:
                        self._safe_print("\n\x1b[90m", end="")
                        thinking_body_started = True
                    self._safe_print(thinking, end="")
                    self._emit_web({"type": "thinking_delta", "text": thinking})
            if content:
                if saw_thinking or thinking_marker_open:
                    if thinking_body_started:
                        self._safe_print("\x1b[0m", end="")
                    _close_thinking_marker()
                elif not full_content:
                    _open_thinking_marker()
                    _close_thinking_marker()
                full_content += content
                if not suppress_tool_json_stream and looks_like_tool_json_stream(
                    full_content
                ):
                    suppress_tool_json_stream = True
                    self._safe_print(
                        "\n\x1b[90m[tool call — preview below, not full JSON]\x1b[0m\n",
                        end="",
                    )
                    self._emit_web(
                        {
                            "type": "status",
                            "text": "Tool call — preview below (not full JSON)",
                        }
                    )
                if not suppress_tool_json_stream:
                    formatted = md_formatter.feed(content)
                    if formatted:
                        self._safe_print(formatted, end="")
                    self._emit_web({"type": "assistant_delta", "text": content})
                else:
                    n = len(full_content)
                    ch = spinner_char(payload_spin_idx, THINKING_SPINNER)
                    payload_spin_idx += 1
                    self._safe_print(
                        f"\r\x1b[33m{ch}\x1b[0m "
                        f"\x1b[90mReceiving file tool payload ({n:,} chars)\x1b[0m",
                        end="",
                        flush=True,
                    )
                    self._emit_web(
                        {
                            "type": "status",
                            "text": f"{ch} Receiving file tool payload ({n:,} chars)",
                        }
                    )

        if stream_errors:
            raise stream_errors[0]

        if suppress_tool_json_stream:
            self._safe_print("\n")
            calls = extract_tool_calls(full_content)
            if calls:
                preview = format_tool_calls_collapsed(calls)
                self._safe_print(preview)
                self._emit_web(
                    {
                        "type": "status",
                        "text": self._strip_ansi(preview),
                    }
                )
            else:
                self._safe_print(
                    "\n\x1b[33m[warn] Tool JSON could not be parsed; "
                    "try a shorter file or ask to retry.\x1b[0m\n"
                )
                self._emit_web(
                    {
                        "type": "status",
                        "text": "Tool JSON could not be parsed; try a shorter file or retry.",
                    }
                )

        if thinking_marker_open:
            if thinking_body_started:
                self._safe_print("\x1b[0m", end="")
            _close_thinking_marker()
        tail = md_formatter.flush()
        if tail:
            self._safe_print(tail, end="")
        self._safe_print("\n")
        self._emit_web({"type": "assistant_end"})

        if full_content:
            blocks = thinking_display.parse_thinking_from_response(full_content)
            if blocks:
                thinking_display.display_thinking(blocks, full_content)

        return full_content, full_thinking

    def _truncate_tool_result(self, text: str) -> str:
        if len(text) <= TOOL_RESULT_MAX_CHARS:
            return text
        omitted = len(text) - TOOL_RESULT_MAX_CHARS
        return (
            text[:TOOL_RESULT_MAX_CHARS]
            + f"\n\n... [truncated {omitted} characters — ask to read a specific section]"
        )

    def _active_editor_file(self) -> str | None:
        from voxprime.core.editor_bridge import load_focused_editor_file

        bridged = load_focused_editor_file()
        if bridged:
            return bridged
        for key in (
            "VSCODE_CURRENT_FILE",
            "VOXPRIME_ACTIVE_FILE",
            "CURSOR_ACTIVE_FILE",
            "CURSOR_FILE",
        ):
            path = os.environ.get(key, "").strip()
            if path and os.path.isfile(path):
                return os.path.abspath(path)
        return None

    def _resolve_editor_focus_file(self) -> str | None:
        """File open in the IDE (Cursor-style) — not stale /file session state."""
        ctx = getattr(self, "_turn_ide_context", None) or {}
        active = (ctx.get("activeFile") or ctx.get("active_file") or "").strip()
        if active and os.path.isfile(active):
            return os.path.abspath(active)
        return self._active_editor_file()

    def _max_chunks_for_path(self, path: str) -> int | None:
        from voxprime.core.file_reader import count_lines

        n_lines = count_lines(path)
        return None if n_lines <= 400 else 1

    def _resolve_workspace_file(self, name: str) -> str | None:
        if not name:
            return None
        candidate = name.strip().strip('"').strip("'")
        if os.path.isabs(candidate) and os.path.isfile(candidate):
            return candidate
        for base in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
            path = os.path.join(base, candidate)
            if os.path.isfile(path):
                return os.path.abspath(path)
        return find_similar_file(os.path.join(os.getcwd(), candidate))

    def _wants_current_file(self, user_input: str) -> bool:
        return bool(_CURRENT_FILE_RE.search(user_input))

    def _is_file_analysis_request(self, user_input: str) -> bool:
        """User wants prose analysis of code — not diagrams or Excalidraw."""
        if self._wants_current_file(user_input):
            return True
        if not re.search(
            r"\b(analy[sz]e|review|explain|summarize|understand|break\s*down|walk\s*through|improve(?:ment)?|refactor|suggest)\b",
            user_input,
            re.I,
        ):
            return False
        if self._explicit_filename_in_message(user_input):
            return True
        if self._resolve_active_file_path() and not re.search(
            r"\b(excalidraw|diagram|draw|blueprint|flowchart)\b", user_input, re.I
        ):
            from voxprime.core.workspace_probe import resolve_analysis_scope_directory

            scope = resolve_analysis_scope_directory(user_input, os.getcwd())
            active = self._resolve_active_file_path()
            if scope and active and not self._path_is_under(scope, active):
                return True
            if not scope:
                return True
        return False

    def _path_is_under(self, directory: str, file_path: str) -> bool:
        d = os.path.normcase(os.path.abspath(directory))
        f = os.path.normcase(os.path.abspath(file_path))
        return f == d or f.startswith(d + os.sep)

    def _explicit_filename_in_message(self, user_input: str) -> str | None:
        """Return a concrete filename if the user named one (not 'current file')."""
        if _CURRENT_FILE_RE.search(user_input) and not re.search(
            r"[\w./\\-]+\.\w{1,10}", user_input
        ):
            return None
        m = re.search(
            r"(?:analy[sz]e|read|review|explain|open)\s+(?:the\s+)?(?:file\s+)?[`'\"]?"
            r"([\w./\\:-]+\.\w{1,10})[`'\"]?",
            user_input,
            re.IGNORECASE,
        )
        if m:
            return m.group(1)
        return None

    def _resolve_active_file_path(self) -> str | None:
        for candidate in (
            self._active_editor_file(),
            self.session_active_file,
            load_persisted_active_file(),
        ):
            if candidate and os.path.isfile(candidate):
                return os.path.abspath(candidate)
        return None

    def _looks_like_app_fix_request(self, text: str) -> bool:
        """Fix/debug in a part of the repo (Cursor-style — investigate, don't interrogate)."""
        low = (text or "").lower()
        if re.search(
            r"\b(fix|debug|troubleshoot|repair|solve|investigate)\b",
            low,
        ):
            if re.search(
                r"\b(issue|bug|error|broken|problem|wrong|fails?|not working)\b",
                low,
            ):
                return True
            from voxprime.core.workspace_probe import folders_mentioned_in_message

            if folders_mentioned_in_message(text, os.getcwd()):
                return True
            if re.search(r"\b(in|under|inside|for)\s+[\w./-]+", low):
                return True
        if re.search(r"\b(fix|debug)\b", low) and re.search(
            r"\b(client|app|server|api|ui|module|package|service)\b", low
        ):
            return True
        return False

    def _looks_like_greenfield_app_request(self, text: str) -> bool:
        """User wants a new app/site/client (stack comes from their words + repo)."""
        low = (text or "").lower()
        if not re.search(r"\b(create|build|scaffold|set up|setup|make|add)\b", low):
            return False
        return bool(
            re.search(
                r"\b(app|application|frontend|front-end|website|web\s*app|ui|client|spa|interface)\b",
                low,
            )
        )

    _MANIFEST_BASENAMES = frozenset(
        {
            "package.json",
            "pyproject.toml",
            "cargo.toml",
            "go.mod",
            "composer.json",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
        }
    )
    _ENTRY_BASENAMES = frozenset(
        {
            "index.html",
            "main.py",
            "app.py",
            "main.go",
            "main.rs",
            "index.js",
            "index.tsx",
            "main.tsx",
            "main.jsx",
            "app.tsx",
            "app.jsx",
        }
    )

    def _dir_has_entry_point(self, directory: str) -> bool:
        try:
            for name in os.listdir(directory):
                if name in self._ENTRY_BASENAMES:
                    return True
                if name in ("src", "app", "public") and os.path.isdir(
                    os.path.join(directory, name)
                ):
                    sub = os.path.join(directory, name)
                    for child in os.listdir(sub):
                        if child in self._ENTRY_BASENAMES:
                            return True
        except OSError:
            return False
        return False

    def _project_setup_incomplete(self, routing_input: str) -> bool:
        paths = getattr(self, "_turn_created_paths", None) or []
        if not paths or not self._looks_like_greenfield_app_request(routing_input):
            return False
        basenames = [os.path.basename(p).lower() for p in paths]
        if len(paths) <= 2 and all(b in self._MANIFEST_BASENAMES for b in basenames):
            return True
        for p in paths:
            if os.path.basename(p).lower() in self._MANIFEST_BASENAMES:
                root = os.path.dirname(p) or os.getcwd()
                if not self._dir_has_entry_point(root):
                    return True
        return False

    def _tool_result_followup(
        self, tool_name: str, result_str: str, routing_input: str
    ) -> str:
        """Context after a tool runs (Aider-style: continue work, don't force early summary)."""
        body = f"Tool `{tool_name}` result:\n{self._truncate_tool_result(result_str)}"
        if self._looks_like_greenfield_app_request(routing_input):
            body += (
                "\n\nContinue the user's application request. If required files are still "
                "missing for a minimal runnable project in the stack they asked for, reply "
                "with ONLY the next single tool JSON. Do not ask whether to continue."
            )
        elif self._looks_like_app_fix_request(routing_input):
            body += (
                "\n\nContinue fixing: inspect with read_file/list_directory if needed, "
                "run short diagnostic run_command from the project manifest, edit_file to "
                "fix, then re-run the diagnostic. Reply with ONLY the next single tool JSON "
                "until fixed or blocked. No tutorials or code fences in chat."
            )
        else:
            body += (
                "\n\nIf the user's request is complete, answer in prose. Otherwise use the "
                "next tool (one per message)."
            )
        return body

    def _looks_like_prose_instead_of_tools(self, text: str) -> bool:
        """Model replied with a plan/tutorial instead of tool JSON."""
        if not text or self._extract_tool_calls(text):
            return False
        if is_tool_json_attempt(text):
            return False
        low = text.lower()
        markers = (
            "### ",
            "action 1:",
            "action 2:",
            "implementation checklist",
            "would you like me to",
            "--- javascript ---",
            "--- python ---",
            "--- jsx ---",
            "phase 1:",
            "detailed breakdown",
        )
        if any(m in low for m in markers):
            return True
        if len(text) > 1200 and re.search(
            r"```\w+", text
        ) and not parse_wholefile_writes(text):
            return True
        return False

    def _fix_investigation_nudge(self, routing_input: str) -> str:
        from voxprime.core.workspace_probe import resolve_fix_scope_directory

        scope = resolve_fix_scope_directory(routing_input, os.getcwd())
        scope_hint = ""
        if scope:
            rel = os.path.relpath(scope, os.getcwd())
            scope_hint = (
                f" Scope directory: `{rel}`. Stay inside this folder unless the user "
                "named another path."
            )
        return (
            "[System] Fix/debug request — you must act like a Cursor/Claude Code agent, "
            "not write a tutorial."
            f"{scope_hint} "
            "Your next message must be ONLY one tool JSON: prefer `run_command` with a "
            "short build/test/lint script from package.json (correct working directory), "
            "or `read_file` / `list_directory` if you still need context. "
            "Do not paste implementation code in chat; use create_file/edit_file tools. "
            "Do not ask the user to describe the bug before you inspect and run diagnostics."
        )

    def _discover_fix_context_files(self, user_input: str) -> tuple[list[str], str]:
        from voxprime.core.workspace_probe import discover_investigation_files

        ctx = getattr(self, "_turn_ide_context", None) or {}
        workspace = (
            (ctx.get("workspaceFolder") or ctx.get("workspace") or "").strip()
            or os.getcwd()
        )
        active = self._resolve_active_file_path()
        return discover_investigation_files(
            workspace_root=workspace,
            user_message=user_input,
            active_file=active,
        )

    def _wants_scoped_analysis(self, text: str) -> bool:
        return bool(
            re.search(
                r"\b(analy[sz]e|review|explain|summarize|understand|break\s*down|walk\s*through|inspect|overview)\b",
                text or "",
                re.I,
            )
        )

    def _attach_files_to_prompt(
        self,
        user_input: str,
        paths: list[str],
        *,
        probe_reason: str = "",
        context_mode: str = "fix",
        scope_dir: str | None = None,
    ) -> str:
        """Inject workspace context (Cursor-style): scoped listing + a few seed files."""
        from voxprime.core.file_reader import read_file_chunked_text
        from voxprime.core.workspace_probe import list_dir_summary

        max_chunks = 1 if context_mode == "analysis" else 2
        blocks: list[str] = []
        if scope_dir and os.path.isdir(scope_dir):
            rel = os.path.relpath(scope_dir, os.getcwd())
            blocks.append(
                f"### Directory listing `{rel}`\n{list_dir_summary(scope_dir)}"
            )
        for path in paths:
            if not os.path.isfile(path):
                continue
            body = read_file_chunked_text(
                path,
                lines_per_chunk=DEFAULT_LINES_PER_CHUNK,
                max_chunks=max_chunks,
            )
            blocks.append(f"### `{path}`\n{body}")
        if not blocks:
            return user_input
        reason = probe_reason or "workspace probe"
        n_files = sum(1 for p in paths if os.path.isfile(p))
        print(
            f"\n[File context] Scope context ({reason}): "
            f"{n_files} file(s) attached"
            + (f", listing `{os.path.relpath(scope_dir, os.getcwd())}`" if scope_dir else "")
        )
        for path in paths:
            if os.path.isfile(path):
                print(f"  • {os.path.relpath(path, os.getcwd())}")
        print()
        if context_mode == "analysis":
            system = (
                "[System: Scoped analysis (Cursor-style). Use the directory listing and "
                "attached files as entry points. read_file / list_directory other paths "
                "only under this scope. Do not analyze unrelated files from the session.]"
            )
        else:
            system = (
                "[System: Fix/debug request (Cursor-style). Files below were auto-selected from "
                "your message, named folders, manifests, and entry files. Inspect them first; "
                "then use list_directory/read_file/search_files as needed; run short diagnostic "
                "run_command from the project manifest scripts in the app directory; fix with "
                "edit_file; re-run diagnostics to confirm. Do not ask the user to restate the "
                "bug before inspecting.]"
            )
        return (
            f"{user_input}\n\n"
            f"{FILES_IN_CHAT_PREFIX}\n\n"
            f"{system}\n\n"
            + "\n\n".join(blocks)
        )

    def _attach_file_chunks_to_prompt(
        self, user_input: str, path: str, max_chunks: int | None = None
    ) -> str:
        """Load file in line chunks (default 1000 lines) into the user message."""
        self.session_active_file = path
        persist_active_file(path)
        from voxprime.core.file_reader import chunk_ranges, count_lines

        lines_per = DEFAULT_LINES_PER_CHUNK
        n_lines = count_lines(path)
        n_chunks = len(chunk_ranges(n_lines, lines_per))
        if max_chunks is None:
            max_chunks = n_chunks if n_chunks <= 3 else 2
        else:
            max_chunks = min(max_chunks, n_chunks)
        if max_chunks == 1 and n_chunks > 1:
            print(
                f"\n[File context] Large file — loaded chunk 1/{n_chunks} only "
                f"(use read_file start_line/end_line for more)\n"
            )

        body = read_file_chunked_text(
            path, lines_per_chunk=lines_per, max_chunks=max_chunks
        )
        print(
            f"\n[File context] Loaded `{path}` ({n_lines} lines, "
            f"chunks of {lines_per}, showing {min(max_chunks, n_chunks)}/{n_chunks})\n"
        )
        return (
            f"{user_input}\n\n"
            f"{FILES_IN_CHAT_PREFIX}\n\n"
            f"Active file path: `{path}`\n"
            f"(When they say 'current file' or 'this file', they mean this path.)\n\n"
            f"{body}"
        )

    def _update_system_prompt(
        self, routing_input: str, *, progressive_diagram: bool = False
    ) -> None:
        """Refresh system message for this turn (core + ask/diagram addenda)."""
        file_analysis = self._is_file_analysis_request(routing_input)
        diagram = user_wants_diagram_mode(routing_input) and not file_analysis
        content = build_system_prompt(
            file_analysis=file_analysis,
            diagram=diagram,
            progressive_diagram=progressive_diagram,
            investigate_fix=self._looks_like_app_fix_request(routing_input),
        )
        if self.context and self.context[0].get("role") == "system":
            self.context[0]["content"] = content
        else:
            self.context.insert(0, {"role": "system", "content": content})

    def _apply_turn_ide_context(self, user_input: str) -> str:
        """Merge active file / selection from VS Code or Cursor extension (HTTP API)."""
        ctx = getattr(self, "_turn_ide_context", None) or {}
        active = (ctx.get("activeFile") or ctx.get("active_file") or "").strip()
        if active and os.path.isfile(active):
            self.session_active_file = os.path.abspath(active)
            persist_active_file(self.session_active_file)
        workspace = (ctx.get("workspaceFolder") or ctx.get("workspace") or "").strip()
        selection = (ctx.get("selection") or ctx.get("selectedText") or "").strip()
        if selection:
            label = active or "editor"
            cap = selection if len(selection) <= 8000 else selection[:8000] + "\n… [selection truncated]"
            user_input = (
                f"{user_input}\n\n[Editor selection from `{label}`]:\n```\n{cap}\n```"
            )
        if workspace:
            user_input = (
                f"{user_input}\n\n[System: IDE workspace root is `{workspace}`. "
                "Paths are relative to this folder unless absolute.]"
            )
        return user_input

    def _enrich_user_input_with_editor_context(self, user_input: str) -> str:
        """Resolve current file + inject chunked content when appropriate."""
        user_input = self._apply_turn_ide_context(user_input)
        from voxprime.core.workspace_probe import (
            discover_analysis_attachments,
            resolve_analysis_scope_directory,
        )

        scope_dir = resolve_analysis_scope_directory(user_input, os.getcwd())
        if scope_dir and self._wants_scoped_analysis(user_input):
            paths, reason = discover_analysis_attachments(scope_dir, os.getcwd())
            return self._attach_files_to_prompt(
                user_input,
                paths,
                probe_reason=reason,
                context_mode="analysis",
                scope_dir=scope_dir,
            )
        if self._looks_like_app_fix_request(user_input):
            from voxprime.core.workspace_probe import (
                _list_dir_summary,
                folders_mentioned_in_message,
                resolve_fix_scope_directory,
            )

            fix_scope = resolve_fix_scope_directory(user_input, os.getcwd())
            probe, reason = self._discover_fix_context_files(user_input)
            if probe:
                return self._attach_files_to_prompt(
                    user_input,
                    probe,
                    probe_reason=reason,
                    scope_dir=fix_scope,
                )
            folders = folders_mentioned_in_message(user_input, os.getcwd())
            if folders:
                blocks = []
                for folder in folders[:2]:
                    rel = os.path.relpath(folder, os.getcwd())
                    blocks.append(
                        f"### Directory listing `{rel}`\n{_list_dir_summary(folder)}"
                    )
                print(
                    f"\n[File context] Listed {len(folders)} folder(s) from your message\n"
                )
                return (
                    f"{user_input}\n\n"
                    f"{FILES_IN_CHAT_PREFIX}\n\n"
                    "[System: Fix/debug in a named folder. Directory listing is below. "
                    "read_file key manifests and sources, then run_command diagnostics "
                    "from that folder's manifest scripts, then edit_file.]\n\n"
                    + "\n\n".join(blocks)
                )
            return (
                f"{user_input}\n\n"
                "[System: Fix/debug request. Use list_directory and search_files to locate "
                "the app root and manifest, read_file, short run_command from manifest "
                "scripts, edit_file, then verify. Do not ask the user to describe the bug first.]"
            )
        explicit = self._explicit_filename_in_message(user_input)
        if explicit:
            resolved = self._resolve_workspace_file(explicit)
            if resolved:
                self.session_active_file = resolved
                persist_active_file(resolved)
                if re.search(
                    r"analy[sz]e|review|explain|summarize|improve|suggest|refactor",
                    user_input,
                    re.I,
                ):
                    return self._attach_file_chunks_to_prompt(user_input, resolved)
                return (
                    f"{user_input}\n\n"
                    f"[System: Active file `{resolved}` — use read_file with this path.]"
                )

        if self._wants_current_file(user_input):
            # Aider/Cursor: "this file" = IDE focus, else session /file / persisted active file
            path = self._resolve_editor_focus_file() or self._resolve_active_file_path()
            if not path:
                return (
                    f"{user_input}\n\n"
                    "[System: User means the file open in the editor, but the agent "
                    "cannot see it yet. In Cursor/VS Code: enable the VoxPrime extension "
                    "(writes .voxprime/editor_context.json on tab focus), or run "
                    "`/file <path>`, or set VOXPRIME_ACTIVE_FILE. Do not guess another file.]"
                )
            self.session_active_file = path
            persist_active_file(path)
            return self._attach_file_chunks_to_prompt(
                user_input, path, max_chunks=self._max_chunks_for_path(path)
            )

        active = self._resolve_editor_focus_file() or self._resolve_active_file_path()
        if active and self._is_file_analysis_request(user_input):
            scope = resolve_analysis_scope_directory(user_input, os.getcwd())
            if scope and not self._path_is_under(scope, active):
                paths, reason = discover_analysis_attachments(scope, os.getcwd())
                return self._attach_files_to_prompt(
                    user_input,
                    paths,
                    probe_reason=reason,
                    context_mode="analysis",
                    scope_dir=scope,
                )
            return self._attach_file_chunks_to_prompt(
                user_input, active, max_chunks=self._max_chunks_for_path(active)
            )
        if active:
            return (
                f"{user_input}\n\n"
                f"[System: Session active file is `{active}` — use /file <path> to change, "
                f"or name the file in your message (e.g. review src/main.py).]"
            )
        return user_input

    def _confirm_destructive(self, tool_name: str, arguments: dict) -> bool:
        if self.skip_confirm or not is_destructive_tool(tool_name, arguments):
            return True
        print("\n⚠️  Destructive action:")
        print(f"   {format_tool_description(tool_name, arguments)}")
        try:
            response = input("   Proceed? (y/n): ").strip().lower()
            return response in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return False

    async def _confirm_destructive_async(self, tool_name: str, arguments: dict) -> bool:
        if self.skip_confirm or not is_destructive_tool(tool_name, arguments):
            return True
        from voxprime.core.stdin_broker import get_broker

        print("\n⚠️  Destructive action:")
        print(f"   {format_tool_description(tool_name, arguments)}")
        try:
            broker = get_broker()
            if broker:
                response = (
                    await broker.read_choice("   Proceed? (y/n): ")
                ).strip().lower()
            else:
                response = input("   Proceed? (y/n): ").strip().lower()
            return response in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return False

    def _backup_before_modify(self, tool_name: str, arguments: dict) -> None:
        if tool_name not in ("edit_file", "write_file", "create_file", "delete_file"):
            return
        path = arguments.get("file_path") or arguments.get("filepath")
        if path and os.path.isfile(path):
            self.undo.save_file_state(path)

    async def _safe_call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Run MCP tool with permissions, dry-run, undo, and fuzzy paths (example.py patterns)."""
        arguments = dict(arguments or {})
        arguments.pop("encoding", None)

        if tool_name in ("list_directory", "create_directory"):
            from voxprime.core.workspace_paths import resolve_directory_path

            arguments["dir_path"] = resolve_directory_path(arguments)

        if tool_name == "read_file" and arguments.get("file_path"):
            fp = arguments["file_path"]
            if not os.path.isfile(fp):
                resolved = self._resolve_workspace_file(fp)
                if resolved:
                    arguments["file_path"] = resolved

        if tool_name in ("read_file", "edit_file") and arguments.get("file_path"):
            corrected = find_similar_file(arguments["file_path"])
            if corrected != arguments["file_path"]:
                print(f"[Fuzzy match] {arguments['file_path']} → {corrected}")
                arguments["file_path"] = corrected

        if self.dry_run.enabled:
            desc = self.dry_run.record(tool_name, arguments)
            self.session_stats.dry_run += 1
            return {"result": f"[dry-run] Would execute: {desc}"}

        needs_permission = tool_name in (
            "write_file",
            "create_file",
            "edit_file",
            "delete_file",
            "run_command",
        ) or tool_name in GIT_WRITE_TOOLS
        if needs_permission and not self.skip_confirm:
            if not self.permissions.is_allowed(tool_name, arguments):
                if not await self.permissions.ask_async(tool_name, arguments):
                    self.session_stats.denied += 1
                    return {
                        "error": "Permission denied or skipped by user",
                        "skipped": True,
                    }

        # Extra yes/no for destructive file ops (run_command uses the permission dialog only)
        if not self.skip_confirm and tool_name != "run_command":
            if not await self._confirm_destructive_async(tool_name, arguments):
                self.session_stats.denied += 1
                return {"error": "User declined destructive action"}

        self.turn_activity.record(tool_name, arguments)
        activity_line = describe_tool_activity(tool_name, arguments)
        print(f"\n\x1b[36m▸\x1b[0m {activity_line}")
        self._emit_web({"type": "activity", "line": activity_line})

        self._backup_before_modify(tool_name, arguments)

        if tool_name == "run_command":
            from voxprime.core.shell_runner import (
                DEV_SERVER_CAP,
                CommandHooks,
                looks_like_dev_server,
                shell_run_hooks,
            )

            cmd = str(arguments.get("command", ""))
            if looks_like_dev_server(cmd):
                print(
                    f"\n\x1b[33m[Note]\x1b[0m Dev server command — streams output, "
                    f"then auto-stops after {DEV_SERVER_CAP}s so chat is not blocked.\n"
                )
            hooks = CommandHooks(
                on_status=lambda s: self._emit_web(
                    {"type": "status", "text": self._strip_ansi(s)}
                ),
            )
            with shell_run_hooks(hooks):
                result = await self.mcp_client.call_tool(tool_name, **arguments)
        else:
            result = await self.mcp_client.call_tool(tool_name, **arguments)

        self.session_stats.tool_calls += 1
        return result

    def list_tool_names(self) -> list[str]:
        """Built-in tools plus external MCP servers (e.g. git)."""
        if hasattr(self.mcp_client, "list_tool_names"):
            return self.mcp_client.list_tool_names()
        return []

    async def run_agentic_goal(self, goal: str, max_iterations: int = 15) -> None:
        """Autonomous loop inspired by example.py AgenticLoop (uses chat_stream per step)."""
        print(f"\n[Agentic mode] Goal: {goal}\n")
        for i in range(1, max_iterations + 1):
            print(f"--- Iteration {i}/{max_iterations} ---")
            prompt = (
                f"Autonomous step toward this goal: {goal}\n"
                "Take exactly ONE tool action if needed, or reply [GOAL_COMPLETE] and a short summary if done."
            )
            await self.chat_stream(prompt)
            last = self.context[-1]["content"] if self.context else ""
            if "[GOAL_COMPLETE]" in last.upper() or "goal complete" in last.lower():
                print("\n[Agentic mode] Goal marked complete.")
                return
        print("\n[Agentic mode] Max iterations reached.")

    def _init_custom_agents(self):
        """Initialize custom multi-agent system (no CrewAI dependencies)."""
        if CUSTOM_AGENTS_AVAILABLE and AgentRouter:
            try:
                self.custom_agent_router = AgentRouter(model=LLM_MODEL)
                print(f"[OK] Custom multi-agent system loaded (Researcher, Coder, Writer)")
            except Exception as e:
                print(f"[WARN] Custom agent router failed: {e}")
                self.custom_agent_router = None
        else:
            print("[INFO] Custom multi-agent system not available")
            self.custom_agent_router = None

    def _extract_tool_calls(self, content: str) -> list:
        """First tool call only (sequential agent steps)."""
        return extract_tool_calls(content)

    def _should_request_continuation(self, full_response: str) -> bool:
        """Prose/code continuation only — never loop on broken tool JSON."""
        if self._extract_tool_calls(full_response):
            return False
        if is_tool_json_attempt(full_response):
            return False
        return self._is_output_incomplete(full_response)

    def _print_token_limit_help(self) -> None:
        print(f"\n\x1b[33m[VoxPrime]\x1b[0m {TOKEN_LIMIT_USER_HINT}\n")

    def _apply_wholefile_writes(self, writes: list[tuple[str, str]]) -> list[str]:
        """Aider-style: filename line + fence → write disk, show collapsed preview."""
        from pathlib import Path

        written: list[str] = []
        for rel_path, body in writes:
            path = resolve_write_path(rel_path, os.getcwd())
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(body, encoding="utf-8")
            self.created_files[path] = False
            print(
                format_file_tool_preview(
                    "create_file",
                    {"file_path": path, "content": body},
                ),
                end="",
            )
            print(f"\n\x1b[32m✓\x1b[0m Saved whole-file block → {path}\n")
            written.append(path)
        return written

    def _try_wholefile_writes_from_response(
        self, full_response: str, routing_input: str
    ) -> bool:
        """Apply filename+fence blocks from model output (tool-loop fallback)."""
        writes = parse_wholefile_writes(full_response)
        if not writes:
            return False
        paths = self._apply_wholefile_writes(writes)
        summary = "Saved whole-file block(s):\n" + "\n".join(f"- `{p}`" for p in paths)
        self.context.append(
            {
                "role": "user",
                "content": self._tool_result_followup(
                    "create_file", summary, routing_input
                ),
            }
        )
        return True

    async def _reflect_generation(
        self,
        base_messages: list,
        assistant_content: str,
        user_instruction: str,
        *,
        label: str = "VoxPrime (retry)",
    ) -> str:
        """One reflection turn without polluting session context (Aider reflected_message)."""
        msgs = list(base_messages) + [
            {"role": "assistant", "content": assistant_content},
            {"role": "user", "content": user_instruction},
        ]
        response, _ = await self._stream_ollama_response(
            msgs,
            label=label,
            options={
                "num_predict": 6144,
                "num_ctx": 16384,
                "temperature": 0.35,
            },
        )
        return response

    async def _run_generation_with_reflections(
        self, full_response: str
    ) -> tuple[str, bool]:
        """
        Capped reflection loop: tool JSON recovery, whole-file parse, prose continuation.
        Returns (final_text, True if whole-file writes were applied).
        """
        base = list(self.context)
        reflections = 0
        while reflections < DEFAULT_MAX_REFLECTIONS:
            if self._extract_tool_calls(full_response):
                return full_response, False

            writes = parse_wholefile_writes(full_response)
            if writes:
                paths = self._apply_wholefile_writes(writes)
                summary = (
                    "Saved design document(s) on disk:\n"
                    + "\n".join(f"- `{p}`" for p in paths)
                    + "\n\nOpen the file(s) in your editor to review."
                )
                return summary, True

            if is_tool_json_attempt(full_response):
                reflections += 1
                print(
                    "\n\x1b[33m[VoxPrime]\x1b[0m Tool JSON incomplete — "
                    f"reflection {reflections}/{DEFAULT_MAX_REFLECTIONS}…\n"
                )
                full_response = await self._reflect_generation(
                    base,
                    full_response,
                    REFLECTION_TRUNCATED_TOOL + "\n\n" + REFLECTION_WHOLEFILE_HINT,
                    label="VoxPrime (tool recovery)",
                )
                continue

            if self._should_request_continuation(full_response):
                reflections += 1
                print(
                    f"\n\x1b[90m[Reflection {reflections}/{DEFAULT_MAX_REFLECTIONS}] "
                    "Continuing truncated output…\x1b[0m\n"
                )
                full_response = await self._reflect_generation(
                    base,
                    full_response,
                    REFLECTION_TRUNCATED_PROSE + "\n\n" + REFLECTION_WHOLEFILE_HINT,
                    label="VoxPrime (continue)",
                )
                continue

            break

        if is_tool_json_attempt(full_response) and not self._extract_tool_calls(
            full_response
        ):
            self._print_token_limit_help()
        elif self._is_output_incomplete(full_response):
            self._print_token_limit_help()

        return full_response, False

    def _is_output_incomplete(self, content: str) -> bool:
        """Detect whether output is cut off by token limit, ignoring text inside JSON strings."""
        in_string = False
        escape = False
        brace_depth = 0
        bracket_depth = 0

        for ch in content:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth = max(brace_depth - 1, 0)
            elif ch == "[":
                bracket_depth += 1
            elif ch == "]":
                bracket_depth = max(bracket_depth - 1, 0)

        if in_string:
            return True
        if brace_depth > 0 or bracket_depth > 0:
            return True

        incomplete_endings = [
            "...",  # Trailing ellipsis
            '"content": "',  # Incomplete string start
            '{"',  # Incomplete object
            '["',  # Incomplete array
            'def ',  # Incomplete function
            'class ',  # Incomplete class
            '<!--',  # Incomplete HTML comment
        ]
        trimmed = content.rstrip()
        for ending in incomplete_endings:
            if trimmed.endswith(ending):
                return True

        return False

    def _complete_incomplete_json(self, content: str) -> str:
        """Attempt to complete incomplete JSON structure by matching braces outside strings."""
        content = content.rstrip()
        in_string = False
        escape = False
        brace_depth = 0
        bracket_depth = 0

        for ch in content:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth = max(brace_depth - 1, 0)
            elif ch == "[":
                bracket_depth += 1
            elif ch == "]":
                bracket_depth = max(bracket_depth - 1, 0)

        closing = "]" * bracket_depth + "}" * brace_depth
        if closing:
            if content.endswith('"') and not content.endswith('\\"'):
                content += '"'
            content += closing
        return content

    def _should_use_crewai(self, user_input: str) -> bool:
        """Check if request should be routed to CrewAI team."""
        # Check for explicit trigger phrases
        for phrase in CREWAI_TRIGGER_PHRASES:
            if phrase in user_input.lower():
                return True

        # Check for complex multi-step tasks
        complex_task_indicators = [
            "build a",
            "create an app",
            "create a full",
            "develop a",
            "design a system",
            "analyze this codebase",
            "write a complete",
            "implement a full",
        ]
        for indicator in complex_task_indicators:
            if indicator in user_input.lower():
                return True

        return False

    def _should_use_custom_agents(self, user_input: str) -> bool:
        """Check if request should be routed to custom multi-agent system."""
        # Check for explicit trigger phrases
        for phrase in CUSTOM_TEAM_TRIGGER_PHRASES:
            if phrase in user_input.lower():
                return True
        return False

    def _should_use_collaborative_agents(self, user_input: str) -> bool:
        """Check if request should use collaborative multi-agent mode (parallel execution)."""
        # Check for explicit trigger phrases
        for phrase in COLLABORATIVE_TEAM_TRIGGER_PHRASES:
            if phrase in user_input.lower():
                return True
        return False

    def _should_use_executor_agent(self, user_input: str) -> bool:
        """Check if request should use executor agent (run code + test + fix loop)."""
        # Check for explicit trigger phrases
        for phrase in EXECUTOR_TRIGGER_PHRASES:
            if phrase in user_input.lower():
                return True
        # Also check for natural language execution requests
        execution_patterns = [
            "execute this",
            "run this code",
            "test this",
            "can you run",
            "can you execute",
            "run and test",
        ]
        for pattern in execution_patterns:
            if pattern in user_input.lower():
                return True
        return False

    def _is_detailed_diagram_request(self, user_input: str) -> bool:
        """Detect if user wants a very detailed/comprehensive diagram that needs progressive enhancement."""
        if self._is_file_analysis_request(user_input):
            return False

        user_lower = user_input.lower()

        # Only explicit diagram intent — not generic words that appear in source files
        diagram_keywords = [
            "excalidraw",
            "diagram",
            "visualize",
            "draw",
            "blueprint",
            "flowchart",
            "architecture diagram",
            "system design diagram",
        ]
        is_diagram = any(keyword in user_lower for keyword in diagram_keywords)
        
        if not is_diagram:
            return False
        
        # Check for detailed/comprehensive keywords
        detailed_keywords = [
            "very detailed",
            "comprehensive",
            "deeply",
            "detailed",
            "internal working",
            "internal workings",
            "deep dive",
            "step-by-step internal",
            "thorough",
            "complete with",
            "all details",
            "full internal",
            "detailed internal",
            "extensive",
            "in-depth",
            "detailed breakdown",
            "complete breakdown",
        ]
        
        for keyword in detailed_keywords:
            if keyword in user_lower:
                return True
        
        return False

    async def chat_stream(self, user_input: str, ide_context: dict | None = None):
        """Chat with streaming + proper multi-step tool execution + continuation for token limits."""

        routing_input = user_input.strip()
        self._turn_ide_context = ide_context or {}
        self.turn_activity.reset()

        if not self.multi_agent_enabled:
            pass  # MVP: always use single agent + tools below
        # Check if this should use executor agent (run code + test + fix loop)
        elif self.custom_agent_router and self._should_use_executor_agent(routing_input):
            print("\n[Executor Mode] Running code with test/fix loop...")
            try:
                # Strip trigger if present
                task = user_input
                for trigger in EXECUTOR_TRIGGER_PHRASES:
                    task = task.replace(trigger, "").strip()
                self.custom_agent_router.execute(task)
                return
            except Exception as e:
                print(f"\n[Error] Executor agent failed: {e}. Falling back to standard agent.")
                # Fall through to standard agent

        # Check if this should use collaborative multi-agent mode (parallel execution)
        elif self.custom_agent_router and self._should_use_collaborative_agents(routing_input):
            print("\n[Collaborative Mode] Multiple agents working in parallel...")
            try:
                # Strip the trigger and execute with collaborative agents
                task = user_input.replace("/custom-multi-simul", "").replace("/collaborative", "").strip()
                self.custom_agent_router.execute_collaborative(task)
                return
            except Exception as e:
                print(f"\n[Error] Collaborative agent system failed: {e}. Falling back to standard agent.")
                # Fall through to standard agent

        # Check if this should go to custom multi-agent system
        elif self.custom_agent_router and self._should_use_custom_agents(routing_input):
            print("\n[Custom multi-agent system] Processing request...")
            try:
                # Strip the trigger and execute with custom agents
                task = user_input.replace("/custom-team", "").strip()
                self.custom_agent_router.execute(task)
                return
            except Exception as e:
                print(f"\n[Error] Custom agent system failed: {e}. Falling back to standard agent.")
                # Fall through to standard agent

        # Check if this should go to CrewAI workflow
        elif self.crewai_workflow and self._should_use_crewai(routing_input):
            print("\n[Complex task detected - routing to CrewAI workflow...]")
            try:
                result = self.crewai_workflow.execute(user_input)
                print(f"\nVoxPrime: {result}")
                return
            except Exception as e:
                print(f"\n[Error] CrewAI workflow failed: {e}. Falling back to standard agent.")
                # Fall through to standard agent

        is_detailed_diagram = self._is_detailed_diagram_request(routing_input)
        self._update_system_prompt(
            routing_input, progressive_diagram=is_detailed_diagram
        )

        # Media/URL parsing only on the user's message — not injected file chunks (avoids fetching MCP URLs in code).
        user_input, vision_images = self._prepare_user_message_with_media(routing_input)
        user_input = self._enrich_user_input_with_editor_context(user_input)
        self.context.append({"role": "user", "content": user_input})

        self._turn_created_paths: list[str] = []
        self._setup_nudge_count = 0
        self._fix_nudge_count = 0
        self._wholefile_nudge_count = 0
        self._tool_json_recovery_attempts = 0
        self._tool_json_recovery_max = int(
            os.getenv("VOXPRIME_TOOL_JSON_RECOVERY", "4")
        )
        if self._looks_like_greenfield_app_request(routing_input):
            max_steps = 14
        elif self._looks_like_app_fix_request(routing_input):
            max_steps = 12
        else:
            max_steps = 5
        step = 0
        continuation_count = 0
        if is_detailed_diagram:
            print("\n[Progressive Enhancement Mode] Generating detailed diagram in phases...")
            print("  Phase 1: Generating intermediate/core-level architecture...")
            
            # Modify the prompt to ask for phase 1 (intermediate level) first
            phase1_instruction = """

---PHASE 1 (progressive diagram)---
Use create_file to write a valid .excalidraw with core components, main flows, and layer groupings.
Do NOT paste Excalidraw JSON in chat. Phase 2 will enhance the file on disk if needed.
---END PHASE 1---
"""
            
            # Update the last context message to include the phase 1 instruction
            if self.context and self.context[-1]["role"] == "user":
                self.context[-1]["content"] = user_input + phase1_instruction

        try:
            # -------------------------------
            # STEP 1: Initial response
            # -------------------------------
            full_response, _ = await self._stream_ollama_response(
                self.context, vision_images=vision_images
            )
            vision_images = []

            full_response, wholefile_applied = await self._run_generation_with_reflections(
                full_response
            )

            self.context.append({
                "role": "assistant",
                "content": full_response
            })

            if wholefile_applied:
                return

            # -------------------------------
            # STEP 2: Tool loop
            # -------------------------------
            while step < max_steps:
                step += 1

                tool_calls = self._extract_tool_calls(full_response)

                if not tool_calls:
                    if self._try_wholefile_writes_from_response(
                        full_response, routing_input
                    ):
                        full_response, _ = await self._stream_ollama_response(
                            self.context
                        )
                        self.context.append(
                            {"role": "assistant", "content": full_response}
                        )
                        continue
                    if is_tool_json_attempt(full_response):
                        if self._tool_json_recovery_attempts < self._tool_json_recovery_max:
                            self._tool_json_recovery_attempts += 1
                            print(
                                "\n\x1b[33m[VoxPrime]\x1b[0m Tool JSON incomplete — "
                                f"recovery {self._tool_json_recovery_attempts}/"
                                f"{self._tool_json_recovery_max}…\n"
                            )
                            base = list(self.context)
                            if base and base[-1].get("role") == "assistant":
                                base = base[:-1]
                            full_response = await self._reflect_generation(
                                base,
                                full_response,
                                REFLECTION_TRUNCATED_TOOL
                                + "\n\n"
                                + REFLECTION_WHOLEFILE_HINT,
                                label="VoxPrime (tool recovery)",
                            )
                            if self.context and self.context[-1].get(
                                "role"
                            ) == "assistant":
                                self.context[-1]["content"] = full_response
                            else:
                                self.context.append(
                                    {
                                        "role": "assistant",
                                        "content": full_response,
                                    }
                                )
                            continue
                        if self._try_wholefile_writes_from_response(
                            full_response, routing_input
                        ):
                            full_response, _ = await self._stream_ollama_response(
                                self.context
                            )
                            self.context.append(
                                {"role": "assistant", "content": full_response}
                            )
                            continue
                        if (
                            self._wholefile_nudge_count < 2
                            and step < max_steps
                            and (
                                self._looks_like_app_fix_request(routing_input)
                                or self._looks_like_greenfield_app_request(
                                    routing_input
                                )
                                or self._project_setup_incomplete(routing_input)
                            )
                        ):
                            self._wholefile_nudge_count += 1
                            self._tool_json_recovery_attempts = 0
                            print(
                                "\n\x1b[33m[VoxPrime]\x1b[0m Tool JSON failed — "
                                "retrying with whole-file fence format…\n"
                            )
                            self.context.append(
                                {
                                    "role": "user",
                                    "content": (
                                        "[System] Your last tool JSON could not be parsed. "
                                        "Reply with ONLY the whole-file format (no JSON):\n\n"
                                        + REFLECTION_WHOLEFILE_HINT
                                    ),
                                }
                            )
                            full_response, _ = await self._stream_ollama_response(
                                self.context
                            )
                            self.context.append(
                                {"role": "assistant", "content": full_response}
                            )
                            continue
                        print(
                            "\n\x1b[31m[Error]\x1b[0m Could not parse tool JSON — "
                            "no file was written. Try a smaller file or whole-file fence format.\n"
                        )
                        break
                    if (
                        self._project_setup_incomplete(routing_input)
                        and self._setup_nudge_count < 4
                        and step < max_steps
                    ):
                        self._setup_nudge_count += 1
                        print(
                            "\n\x1b[90m[VoxPrime] Application setup incomplete — "
                            "continuing tool loop…\x1b[0m\n"
                        )
                        self.context.append(
                            {
                                "role": "user",
                                "content": (
                                    "[System] The user asked for a working application. "
                                    "Only part of the project exists on disk. Reply with ONLY "
                                    "one tool JSON (create_file or run_command) for the next "
                                    "required file or step. Match the stack they requested. "
                                    "Do not ask the user to confirm."
                                ),
                            }
                        )
                        full_response, _ = await self._stream_ollama_response(
                            self.context
                        )
                        self.context.append(
                            {"role": "assistant", "content": full_response}
                        )
                        continue
                    if (
                        self._looks_like_app_fix_request(routing_input)
                        and self._fix_nudge_count < 4
                        and step < max_steps
                        and (
                            self._looks_like_prose_instead_of_tools(full_response)
                            or self._fix_nudge_count == 0
                        )
                    ):
                        self._fix_nudge_count += 1
                        print(
                            "\n\x1b[90m[VoxPrime] Fix mode — expecting tools "
                            "(read_file / run_command / edit_file), not a tutorial…\x1b[0m\n"
                        )
                        self.context.append(
                            {
                                "role": "user",
                                "content": self._fix_investigation_nudge(routing_input),
                            }
                        )
                        full_response, _ = await self._stream_ollama_response(
                            self.context
                        )
                        self.context.append(
                            {"role": "assistant", "content": full_response}
                        )
                        continue
                    break

                for tool_name, arguments in tool_calls:
                    if tool_name in FILE_WRITE_TOOLS:
                        preview = format_file_tool_preview(tool_name, arguments)
                        print(preview, end="")
                        self._emit_web(
                            {
                                "type": "status",
                                "text": self._strip_ansi(preview),
                            }
                        )

                    # Handle file creation continuations
                    if tool_name == "create_file" and continuation_count > 0:
                        file_path = arguments.get("file_path", "")
                        if file_path in self.created_files:
                            # This is a continuation - read existing file and append
                            try:
                                with open(file_path, 'r', encoding='utf-8') as f:
                                    existing_content = f.read()
                                new_content = existing_content + arguments.get("content", "")
                                arguments = {"file_path": file_path, "content": new_content}
                                tool_name = "edit_file"
                                print(f"[Continuing file: {file_path}]")
                            except Exception as e:
                                print(f"[Warning: Could not read existing file for continuation: {e}]")

                    result = await self._safe_call_tool(tool_name, arguments)

                    if "error" in result:
                        result_str = f"Error: {result['error']}"
                        print(f"\n\x1b[31m[Result: {result_str}]\x1b[0m\n")
                        self._emit_web({"type": "status", "text": result_str})
                    else:
                        result_str = str(result.get("result", ""))
                        if tool_name in FILE_WRITE_TOOLS:
                            print(f"\n\x1b[32m✓\x1b[0m {result_str}\n")
                            self._emit_web({"type": "status", "text": f"✓ {result_str}"})
                        # Track created files
                        if tool_name == "create_file":
                            file_path = arguments.get("file_path", "")
                            if file_path:
                                self.created_files[file_path] = False  # Not a continuation yet
                                self._turn_created_paths.append(file_path)
                                if not os.path.isfile(file_path):
                                    resolved = self._resolve_workspace_file(
                                        file_path
                                    ) or file_path
                                    if not os.path.isfile(resolved):
                                        print(
                                            f"\n\x1b[31m[Error]\x1b[0m File not found "
                                            f"after create_file: {file_path}\n"
                                        )
                        elif tool_name == "edit_file":
                            file_path = arguments.get("file_path", "")
                            if file_path:
                                self.created_files[file_path] = True  # Mark as continued

                    if "error" not in result and tool_name not in FILE_WRITE_TOOLS:
                        if tool_name == "run_command":
                            code = result.get("exit_code", 0)
                            print(
                                f"\x1b[90m  ↳ shell recorded for the model "
                                f"(exit {code}; output streamed above)\x1b[0m\n"
                            )
                        else:
                            print(
                                f"[Result: {result_str[:200]}...]\n"
                                if len(str(result_str)) > 200
                                else f"[Result: {result_str}]\n"
                            )

                    self.context.append({
                        "role": "user",
                        "content": self._tool_result_followup(
                            tool_name, result_str, routing_input
                        ),
                    })

                full_response, _ = await self._stream_ollama_response(self.context)

                self.context.append({
                    "role": "assistant",
                    "content": full_response,
                })

            activity_block = self.turn_activity.format_block()
            if activity_block:
                print(activity_block)

        except Exception as e:
            print(f"\n[Error: {str(e)}]")

        # ✅ PHASE 2: Auto-enhance detailed diagrams (after main try-except)
        if is_detailed_diagram and self.created_files:
            excalidraw_files = [f for f in self.created_files.keys() if f.endswith('.excalidraw')]
            if excalidraw_files:
                print("\n[Progressive Enhancement Mode] Phase 2: Enhancing with internal details...")
                
                for excalidraw_file in excalidraw_files:
                    print(f"  Reading created diagram: {excalidraw_file}")
                    
                    # Read the created file
                    try:
                        with open(excalidraw_file, 'r', encoding='utf-8') as f:
                            existing_content = f.read()
                        print(f"  Generating enhancements for: {excalidraw_file}")
                    except Exception as e:
                        print(f"  [Warning] Could not read file for enhancement: {e}")
                        continue

                    existing_summary = []
                    try:
                        existing_json = json.loads(existing_content)
                        element_count = len(existing_json.get('elements', []))
                        existing_summary.append(f"Existing element count: {element_count}")
                        sample_names = []
                        for element in existing_json.get('elements', []):
                            name = element.get('name') or element.get('type')
                            if name and len(sample_names) < 12:
                                sample_names.append(name)
                        if sample_names:
                            existing_summary.append(f"Sample elements: {', '.join(sample_names)}")
                    except Exception:
                        existing_summary.append("Existing file contains Excalidraw JSON; summary unavailable.")

                    existing_summary_text = "\n".join(existing_summary)

                    # Phase 2: Simple enhancement flow
                    # System has already read the file, now pass content to LLM and ask for edit only
                    phase2_prompt = f"""
                        You have successfully created an Excalidraw diagram file '{excalidraw_file}' with the core architecture.

                        Here is the file content you created:
                        ```json
                        {existing_content}
                        ```

                        Diagram summary:
                        {existing_summary_text}

                        ENHANCEMENT TASK: Add ENTERPRISE-GRADE internal architecture details that match how companies like Google, Amazon, Netflix, Meta, and Microsoft implement production systems.

                        1. **PRESERVE all existing elements** - do not remove or modify them, only ADD new components.

                        2. **INFRASTRUCTURE & DEPLOYMENT LAYER** - Add these components:
                        - Kubernetes clusters (control plane + worker nodes)
                        - Container orchestration layers
                        - Auto-scaling groups and scaling policies
                        - Infrastructure-as-Code (Terraform/CloudFormation)
                        - CI/CD pipelines (build, test, deploy stages)
                        - Artifact repositories (Docker registry, package managers)
                        - Blue-green/Canary deployment infrastructure

                        3. **SERVICE MESH & NETWORKING**:
                        - Service mesh control plane (Istio/Linkerd)
                        - Sidecar proxies for each service
                        - gRPC communication paths between services
                        - Circuit breaker patterns and implementations
                        - Retry logic with exponential backoff
                        - Service discovery and DNS resolution
                        - Load balancing policies (round-robin, least-conn, weighted)
                        - Network segmentation and firewall rules

                        4. **SECURITY LAYERS** - Enterprise-grade:
                        - mTLS (mutual TLS) connections between services
                        - API Gateway with OAuth2/JWT validation
                        - WAF (Web Application Firewall) rules
                        - DDoS protection and rate limiting tiers
                        - Secret management vaults (HashiCorp Vault, AWS Secrets Manager)
                        - Encryption at rest (AES-256) and in-transit
                        - Security scanning and vulnerability assessment
                        - Compliance monitoring (GDPR, SOC2, ISO 27001)

                        5. **OBSERVABILITY & MONITORING** - Production-grade:
                        - Distributed tracing system (Jaeger, Zipkin)
                        - Trace propagation across services
                        - Metrics collection (Prometheus scraping)
                        - Time-series database (InfluxDB, Prometheus)
                        - Centralized logging system (ELK stack, Splunk)
                        - APM (Application Performance Monitoring)
                        - Real-time alerting and incident management
                        - SLO/SLI tracking dashboards
                        - Custom metrics for business logic

                        6. **DATA LAYER - ADVANCED PATTERNS**:
                        - Primary-replica database replication
                        - Read replicas and read pools
                        - Database connection pooling with failover
                        - Cache coherency strategies
                        - Multi-level caching (L1, L2, L3)
                        - Cache invalidation mechanisms (TTL, event-based)
                        - Message queues and event streaming (Kafka, RabbitMQ)
                        - Dead letter queues for failed messages
                        - Database sharding strategy and distribution
                        - ACID transaction handling across services
                        - Saga pattern for distributed transactions

                        7. **RESILIENCE & FAULT TOLERANCE**:
                        - Bulkhead pattern isolation
                        - Timeout configurations for each service
                        - Fallback mechanisms and graceful degradation
                        - Health check endpoints and monitoring
                        - Self-healing mechanisms
                        - Chaos engineering testing infrastructure
                        - Multi-region failover and disaster recovery
                        - Backup and restore automation
                        - RTO/RPO targets and monitoring

                        8. **PERFORMANCE OPTIMIZATION**:
                        - CDN with edge locations and caching
                        - Origin shield for origin protection
                        - Query optimization and indexing strategy
                        - Connection pooling and resource management
                        - Lazy loading and pagination patterns
                        - Rate limiting per customer/tier
                        - Request deduplication
                        - Batching and aggregation layers

                        9. **DATA FLOW & REQUEST PATHS** - Show:
                        - Critical request path (happy path)
                        - Fallback paths and error handling flows
                        - Batch processing pipelines
                        - Asynchronous job processing
                        - Event-driven triggers
                        - Data synchronization between systems
                        - Webhook and notification flows
                        - Real-time vs batch data processing

                        10. **OPERATIONAL COMPONENTS**:
                        - Deployment orchestration system
                        - Feature flag management
                        - Configuration management (dynamic config)
                        - A/B testing framework
                        - Telemetry and data collection
                        - Audit logging for compliance
                        - Backup and archival systems
                        - Cost monitoring and optimization

                        11. **CONNECTIONS - SHOW DETAILS**:
                        - Label each connection with protocol (gRPC, HTTP/2, WebSocket)
                        - Show sync vs async communication
                        - Indicate timeout values
                        - Show retry counts and backoff strategies
                        - Indicate circuit breaker states
                        - Show data transformation steps
                        - Mark security boundaries (mTLS, TLS)
                        - Indicate throughput and latency SLOs

                        12. **SCALE INDICATORS**:
                        - Indicate which components scale horizontally
                        - Show duplication for high availability (3x for critical services)
                        - Mark single points of failure
                        - Show redundancy levels (2N, 3N, etc.)

                        Make this production-ready, showing enterprise-scale architecture patterns used by FAANG companies.

                        4. **Return only ONE tool call** with the enhanced diagram:
                        {{"tools": [{{"name": "edit_file", "args": {{"file_path": "{excalidraw_file}", "content": "..."}}}}]}}
                        """
                    
                    # Generate phase 2 enhancements
                    phase2_response = ""
                    try:
                        phase2_response, _ = await self._stream_ollama_response(
                            self.context + [{"role": "user", "content": phase2_prompt}],
                            label="VoxPrime [Phase 2]",
                        )

                        # Extract and execute the edit_file tool call
                        tool_calls = self._extract_tool_calls(phase2_response)
                        print(tool_calls)
                        if tool_calls:
                            for tool_name, arguments in tool_calls:
                                if tool_name == "read_file":
                                    print(f"\n[Calling: {tool_name} (Phase 2 - Read)]")
                                    result = await self._safe_call_tool(tool_name, arguments)
                                    result_str = str(result.get("result", ""))
                                    print(f"[Result: File read - {len(result_str)} chars]\n")
                                elif tool_name == "edit_file":
                                    print(f"\n[Calling: {tool_name} (Phase 2 - Enhance)]")
                                    result = await self._safe_call_tool(tool_name, arguments)
                                    result_str = str(result.get("result", ""))
                                    print(f"[Result: Enhanced diagram saved]\n")
                                    print(f"✓ Phase 2 complete: {excalidraw_file} enhanced with internal details\n")
                        else:
                            print("\n[Warning] Phase 2 did not return any tool calls.")
                    except Exception as e:
                        print(f"\n[Warning] Phase 2 enhancement failed: {e}\n")



    def reset(self):
        """Reset conversation context."""
        self.context = [{"role": "system", "content": build_system_prompt()}]
        self.created_files = {}  # Reset file tracking
        self.permissions.reset_conversation_permissions()


# ---------------------------------------------------------------------------
# Interactive Loop
# ---------------------------------------------------------------------------

def _print_repl_help() -> None:
    print(
        """
Commands:
  quit, exit          Leave the session
  reset               Clear conversation context
  /help               Show this help
  /tools              List all tools (builtin + MCP)
  /mcp                Show external MCP status (git, …)
  /stats              Session tool-call statistics
  /undo               Restore last file from backup
  /dry-run            Preview tool actions without executing
  /dry-run-off        Turn dry-run off
  /dry-run-show       List actions recorded in dry-run mode
  /no-confirm         Auto-approve shell + skip destructive prompts (session)
  /reset-permissions  Clear file & command allow lists
  /agentic <goal>     Autonomous multi-step loop toward a goal (single agent)
  (Multi-agent /team, /custom-team, … — off by default; VOXPRIME_MULTI_AGENT=1)
Shortcuts: time, weather <city> (see shortcut_commands)

  /file <path>        Set session "current file" (saved in .voxprime/active_file)
  /roadmap            Gaps vs Claude Code–style agent
  /chat-web           Open browser chat UI (run: python -m voxprime.web.chat_server)
  IDE sidebar         vscode-extension/ + docs/IDE_INTEGRATION.md (VS Code & Cursor)

Editor file: /file, or env VOXPRIME_ACTIVE_FILE / VSCODE_CURRENT_FILE
Hide thinking text: VOXPRIME_SHOW_THINKING=0 (spinners still show)
While VoxPrime is working, type another line + Enter to queue (no extra prompt)
Assistant options/code blocks: highlighted in terminal (VOXPRIME_FORMAT_MARKDOWN=0 to disable)

Tools vs Cursor IDE:
  Cursor runs grep/read in the IDE automatically. Here, nothing runs until the model
  emits a tools JSON block. Each step prints a cyan ▸ line (Read, Grepped, Run, …).
  Shell: approve with A (once), AA (same command prefix), or AS (any command until `reset`).
  Use prompts like "search the repo for X and read foo.py" to trigger read_file /
  search_files. Destructive deletes ask Proceed? (y/n).

Attachments (PDF, DOCX, images, web):
  /attach report.pdf -- summarize
  /attach screenshot.png -- what error is shown?
  /screenshot [-- your question]   Paste from clipboard (needs: pip install pillow)
  @diagram.png in the message
  Paste a URL in your message (auto-fetched)

Screenshots (like Cursor/Claude):
  1. ollama pull qwen2.5vl   (or llava)
  2. In .env: VOXPRIME_VISION_MODEL=qwen2.5vl:latest
  3. Win+Shift+S → save PNG → /attach shot.png -- analyze
     Or /screenshot -- analyze this UI
"""
    )


def _print_claude_code_roadmap() -> None:
    print(
        """
VoxPrime vs Claude Code — major gaps (priority order):

  IDE / editor     No native Cursor/VS Code extension; no selection, tabs, or @-mentions
  MCP              Tools run in-process; not full MCP SSE client to server.py
  Agent loop       No durable task loop, checkpoints, or subagents like Claude Code tasks
  Git              No integrated commit/PR flow, branch awareness, or diff-only edits
  Search           No repo-wide semantic index (only glob read_file / search_files)
  Terminal         run_command exists; no sandboxed PTY, background jobs, or output streaming
  Permissions      Basic file allow/deny; no per-tool policy files or enterprise rules
  Multi-file edits No atomic multi-file patches; edit_file is full-file overwrite
  Hooks / API      No HTTP agent API, hooks, or CI integration (example.py had --http)
  Context          Chunked reads added; no automatic @codebase / dependency graph
  Models           Ollama-only here; no cloud model routing or fallbacks

Already in VoxPrime: streaming + thinking UI, undo/dry-run, MCP git tools,
voice pipeline (separate), Excalidraw flows, shortcuts, local Ollama.

Next milestones: real MCP tools, ripgrep search_code, git tool, continuation loop,
IDE env sync (active file from Cursor), subagent /plan mode.
"""
    )


def _print_multi_agent_disabled() -> None:
    print(
        "[INFO] Multi-agent mode is disabled (MVP). "
        "Plain chat uses Ollama + MCP tools. Enable with --multi-agent or VOXPRIME_MULTI_AGENT=1."
    )


def _print_queued(n: int) -> None:
    if n <= 0:
        return
    word = "message" if n == 1 else "messages"
    print(f"\n\x1b[90m  ↳ Queued ({n} {word} waiting)\x1b[0m")


async def _repl_dispatch(agent: AgentWithTools, user_input: str) -> bool:
    """Handle one REPL line. Returns False to exit the session."""
    if user_input.lower() in ("quit", "exit"):
        try:
            await agent.mcp_client.disconnect()
        except Exception:
            pass
        print("\nVoxPrime: Goodbye, boss. Standing by when you need me.")
        return False

    if user_input.lower() == "reset":
        agent.reset()
        print("VoxPrime: Conversation reset. How can I help?")
        return True

    if user_input.lower() in ("/help", "help"):
        _print_repl_help()
        return True

    if user_input.lower() in ("/chat-web", "/chat-ui"):
        import webbrowser

        port = int(os.getenv("VOXPRIME_CHAT_PORT", "8765"))
        url = f"http://127.0.0.1:{port}/"
        print(
            f"Start the chat server in another terminal:\n"
            f"  python -m voxprime.web.chat_server --port {port}\n"
            f"Then open {url}"
        )
        webbrowser.open(url)
        return True

    if user_input.lower() == "/roadmap":
        _print_claude_code_roadmap()
        return True

    if user_input.lower().startswith("/file "):
        path_arg = user_input[6:].strip().strip('"')
        resolved = agent._resolve_workspace_file(path_arg) or (
            path_arg if os.path.isfile(path_arg) else None
        )
        if resolved:
            agent.session_active_file = os.path.abspath(resolved)
            persist_active_file(agent.session_active_file)
            print(f"[OK] Active file: {agent.session_active_file}")
        else:
            print(f"[Error] File not found: {path_arg}")
        return True

    if user_input.lower() == "/file":
        cur = agent._resolve_active_file_path()
        print(f"Active file: {cur or '(not set — use /file <path>)'}")
        return True

    if user_input.lower() == "/tools":
        print("Tools:", ", ".join(agent.list_tool_names()))
        return True

    if user_input.lower() == "/mcp":
        names = agent.list_tool_names()
        git_tools = [t for t in names if t.startswith("git_")]
        print(f"MCP tools ({len(names)} total)")
        if git_tools:
            print("  Git MCP:", ", ".join(git_tools))
        else:
            print("  Git MCP: not connected (see .voxprime/mcp.json.example)")
        return True

    if user_input.lower() == "/stats":
        print(agent.session_stats.summary())
        return True

    if user_input.lower() == "/undo":
        ok, msg = agent.undo.undo_last()
        print(msg if ok else f"[Undo failed] {msg}")
        return True

    if user_input.lower() == "/dry-run":
        agent.dry_run.enable()
        return True

    if user_input.lower() in ("/dry-run-off", "/dryrun-off"):
        agent.dry_run.disable()
        return True

    if user_input.lower() in ("/dry-run-show", "/dryrun-show"):
        agent.dry_run.show_planned()
        return True

    if user_input.lower() == "/no-confirm":
        agent.skip_confirm = True
        print("[OK] Auto-approve: shell commands and file writes run without prompts.")
        return True

    if user_input.lower() in ("/reset-permissions", "/reset-perms"):
        agent.permissions.reset_all()
        print("[OK] File and command permissions reset.")
        return True

    if user_input.lower().startswith("/screenshot"):
        from pathlib import Path
        from voxprime.core.screenshot import capture_clipboard_to_png

        rest = user_input[len("/screenshot") :].strip()
        if rest.startswith("--"):
            question = rest[2:].strip() or "Describe this screenshot in detail."
        else:
            question = rest or "Describe this screenshot in detail."
        shot_dir = Path(os.getcwd()) / ".voxprime"
        shot_path = shot_dir / "clipboard_screenshot.png"
        ok, msg = capture_clipboard_to_png(shot_path)
        if not ok:
            print(f"[Error] {msg}")
            print()
            return True
        print(f"[OK] Screenshot saved: {msg}")
        await agent.chat_stream(f"/attach {msg} -- {question}")
        print()
        return True

    if user_input.lower().startswith("/agentic "):
        goal = user_input[9:].strip()
        if goal:
            await agent.run_agentic_goal(goal)
        else:
            print("Usage: /agentic <goal description>")
        print()
        return True

    if user_input.lower().startswith("/team "):
        if not agent.multi_agent_enabled:
            _print_multi_agent_disabled()
            print()
            return True
        task = user_input[6:].strip()
        if agent.crewai_workflow:
            print("\n[CrewAI Workflow] Executing task with specialist team...")
            result = agent.crewai_workflow.execute(task)
            print(f"\nVoxPrime: {result}")
        else:
            print("\n[Error] CrewAI workflow not available.")
        print()
        return True

    if user_input.lower().startswith("/custom-team "):
        if not agent.multi_agent_enabled:
            _print_multi_agent_disabled()
            print()
            return True
        task = user_input[13:].strip()
        if agent.custom_agent_router:
            print("\n[Custom Agents] Executing task with specialist team...")
            agent.custom_agent_router.execute(task)
        else:
            print("\n[Error] Custom multi-agent system not available.")
        print()
        return True

    if user_input.lower().startswith("/custom-multi-simul "):
        if not agent.multi_agent_enabled:
            _print_multi_agent_disabled()
            print()
            return True
        task = user_input[20:].strip()
        if agent.custom_agent_router:
            print("\n[Collaborative Agents] Executing task with parallel agents + review...")
            agent.custom_agent_router.execute_collaborative(task)
        else:
            print("\n[Error] Collaborative multi-agent system not available.")
        print()
        return True

    if user_input.lower().startswith("/execute ") or user_input.lower().startswith(
        "/run-code "
    ) or user_input.lower().startswith("/test-code "):
        if not agent.multi_agent_enabled:
            _print_multi_agent_disabled()
            print()
            return True
        task = user_input
        for trigger in ["/execute ", "/run-code ", "/test-code "]:
            if user_input.lower().startswith(trigger):
                task = user_input[len(trigger) :].strip()
                break
        if agent.custom_agent_router:
            print("\n[Executor Agent] Running code with test/fix loop...")
            agent.custom_agent_router.execute(task)
        else:
            print("\n[Error] Executor agent not available.")
        print()
        return True

    user_input = shortcuts(user_input)
    await agent.chat_stream(user_input)
    print()
    return True


async def _repl_worker(agent: AgentWithTools, inbox: asyncio.Queue, state: dict) -> None:
    while True:
        user_input = await inbox.get()
        if user_input is None:
            break
        state["busy"] = True
        try:
            if not await _repl_dispatch(agent, user_input):
                await inbox.put(None)
                break
        except KeyboardInterrupt:
            print("\n\nVoxPrime: Session interrupted. Goodbye.")
            try:
                await agent.mcp_client.disconnect()
            except Exception:
                pass
            await inbox.put(None)
            break
        except EOFError:
            print("\n\nVoxPrime: End of input. Goodbye.")
            await inbox.put(None)
            break
        finally:
            state["busy"] = False


async def _repl_reader(broker, inbox: asyncio.Queue, state: dict) -> None:
    """
    Idle prompt (You:) only when the worker is not busy.
    While the agent runs, read stdin silently; extra lines queue (Cursor-style).
    """
    first_prompt = True
    while True:
        try:
            while state.get("busy"):
                await asyncio.sleep(0.05)

            prefix = "" if first_prompt else "\n"
            first_prompt = False
            user_input = (await broker.read_user(f"{prefix}You: ")).strip()
        except EOFError:
            await inbox.put(None)
            break
        if not user_input:
            continue
        await inbox.put(user_input)

        while inbox.qsize() > 0 and not state.get("busy"):
            await asyncio.sleep(0.02)

        while state.get("busy"):
            try:
                line = await broker.read_user_timed(None, 0.2)
            except EOFError:
                await inbox.put(None)
                return
            if line is None:
                continue
            queued = line.strip()
            if not queued:
                continue
            await inbox.put(queued)
            _print_queued(inbox.qsize())


async def interactive_loop(
    no_confirm: bool = False, dry_run: bool = False, multi_agent: bool | None = None
):
    """Run interactive chat loop with streaming."""
    if multi_agent is not None:
        os.environ["VOXPRIME_MULTI_AGENT"] = "1" if multi_agent else "0"
    agent = AgentWithTools()
    agent.skip_confirm = no_confirm
    if dry_run:
        agent.dry_run.enable()

    await agent.mcp_client.connect()

    print("\n" + "=" * 50)
    print("  VoxPrime Agent with MCP Tools (Streaming)")
    print("  Type '/help' for commands | quit/exit to stop")
    print(
        "  Tip: while VoxPrime works, type another line and Enter — it queues silently"
    )
    focus = agent._resolve_editor_focus_file()
    if focus:
        print(f"  Editor focus: {focus}")
    elif agent.session_active_file:
        print(f"  Session file: {agent.session_active_file}")
    else:
        print(
            "  Tip: /file <path> or enable VoxPrime extension (syncs open tab)"
        )
    print("=" * 50 + "\n")

    # Greeting with streaming
    # print("VoxPrime: ", end="", flush=True)
    await agent.chat_stream("Give a brief one-sentence greeting.")
    print()

    await agent.mcp_client.connect_external()

    from voxprime.core.stdin_broker import install_broker

    loop = asyncio.get_running_loop()
    broker = install_broker(loop)
    inbox: asyncio.Queue = asyncio.Queue()
    state: dict = {"busy": False}

    worker = asyncio.create_task(_repl_worker(agent, inbox, state))
    await _repl_reader(broker, inbox, state)
    await worker


def main():
    import argparse

    parser = argparse.ArgumentParser(description="VoxPrime agent with MCP tools")
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="Skip confirmation for destructive tool actions",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Start with dry-run enabled (tools are previewed only)",
    )
    parser.add_argument(
        "--multi-agent",
        action="store_true",
        help="Enable CrewAI / custom multi-agent routing (off by default for MVP)",
    )
    args = parser.parse_args()
    asyncio.run(
        interactive_loop(
            no_confirm=args.no_confirm,
            dry_run=args.dry_run,
            multi_agent=True if args.multi_agent else None,
        )
    )


if __name__ == "__main__":
    main()
