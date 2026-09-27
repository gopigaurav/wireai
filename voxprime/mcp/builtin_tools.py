"""In-process tool execution (bridge for local tools)."""

import asyncio
import httpx
import os

from voxprime.config import config
from voxprime.core.file_reader import read_file_chunked_text
from voxprime.core.workspace_paths import resolve_directory_path, resolve_file_path
from voxprime.core.media_ingest import (
    extract_document_text,
    fetch_webpage_markdown,
    ingest_paths,
    model_supports_vision,
)

LLM_MODEL = config.LLM_MODEL


class BuiltinToolExecutor:
    """In-process VoxPrime tools (files, web, media, shell)."""

    def list_tool_names(self) -> list[str]:
        return [
            "get_current_time",
            "get_system_info",
            "calculate",
            "get_weather",
            "search_web",
            "fetch_url",
            "fetch_webpage",
            "read_file",
            "write_file",
            "create_file",
            "edit_file",
            "delete_file",
            "create_directory",
            "list_directory",
            "search_files",
            "run_command",
            "review_code",
            "read_document",
            "describe_image",
            "ingest_attachments",
        ]

    async def call_tool(self, tool_name: str, **kwargs) -> dict:
        """Call a tool on the MCP server via direct implementation."""
        try:
            # Implement tools directly for reliability
            if tool_name == "get_current_time":
                import datetime
                return {"result": datetime.datetime.now().isoformat()}
            elif tool_name == "get_system_info":
                import platform
                return {"result": {
                    "os": platform.system(),
                    "os_version": platform.version(),
                    "machine": platform.machine(),
                    "python_version": platform.python_version(),
                }}
            elif tool_name == "calculate":
                expr = kwargs.get("expression", "")
                try:
                    import ast
                    result = eval(ast.unparse(ast.parse(expr, mode='eval')))
                    return {"result": str(result)}
                except Exception as e:
                    return {"error": str(e)}
            elif tool_name == "get_weather":
                city = kwargs.get("city", "")
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"https://wttr.in/{city}?format=%C+%t")
                    return {"result": f"Weather in {city}: {response.text.strip()}"}
            elif tool_name == "search_web":
                query = kwargs.get("query", "")
                return await self._search_web(query)
            elif tool_name in ("fetch_url", "fetch_webpage"):
                url = kwargs.get("url", "")
                max_chars = int(kwargs.get("max_chars", 32000))
                try:
                    return {"result": fetch_webpage_markdown(url, max_chars=max_chars)}
                except Exception as e:
                    return {"error": str(e)}
            elif tool_name == "read_document":
                file_path = kwargs.get("file_path", "")
                max_chars = int(kwargs.get("max_chars", 48000))
                try:
                    return {"result": extract_document_text(file_path, max_chars=max_chars)}
                except Exception as e:
                    return {"error": str(e)}
            elif tool_name == "describe_image":
                from voxprime.core.media_ingest import load_image_base64

                file_path = kwargs.get("file_path", "")
                if not model_supports_vision(LLM_MODEL):
                    return {
                        "result": f"Vision not enabled for {LLM_MODEL}. Use a vision model or VOXPRIME_FORCE_VISION=1."
                    }
                try:
                    b64 = load_image_base64(file_path)
                    return {"result": f"Image ready ({len(b64)} b64 chars) at {file_path}"}
                except Exception as e:
                    return {"error": str(e)}
            elif tool_name == "ingest_attachments":
                from voxprime.core.media_ingest import ingest_paths

                raw = kwargs.get("file_paths", "")
                paths = [p.strip() for p in raw.split(",") if p.strip()]
                text, _ = ingest_paths(paths, LLM_MODEL)
                return {"result": text}
            elif tool_name == "read_file":
                file_path = kwargs.get("file_path", "")
                start_line = kwargs.get("start_line")
                end_line = kwargs.get("end_line")
                try:
                    if start_line is not None or end_line is not None:
                        text = read_file_chunked_text(
                            file_path,
                            start_line=int(start_line) if start_line else None,
                            end_line=int(end_line) if end_line else None,
                        )
                    else:
                        text = read_file_chunked_text(file_path)
                    return {"result": text}
                except Exception as e:
                    return {"error": str(e)}
            elif tool_name == "list_directory":
                dir_path = resolve_directory_path(kwargs)
                try:
                    if not os.path.isdir(dir_path):
                        return {"error": f"Not a directory: {dir_path}"}
                    entries = sorted(os.listdir(dir_path))
                    head = "\n".join(entries[:50])
                    suffix = f"\n… ({len(entries)} entries total)" if len(entries) > 50 else ""
                    return {"result": f"{dir_path}:\n{head}{suffix}"}
                except Exception as e:
                    return {"error": str(e)}
            elif tool_name == "search_files":
                dir_path = kwargs.get("dir_path", ".")
                query = kwargs.get("query", "*")
                try:
                    import fnmatch
                    matches = []
                    for root, dirs, files in os.walk(dir_path):
                        for name in files:
                            if fnmatch.fnmatch(name, query) or fnmatch.fnmatch(os.path.join(root, name), query):
                                rel_path = os.path.relpath(os.path.join(root, name), dir_path)
                                matches.append(rel_path)
                                if len(matches) >= 200:
                                    break
                        if len(matches) >= 200:
                            break
                    return {"result": "\n".join(matches) if matches else f"No files matched: {query}"}
                except Exception as e:
                    return {"error": str(e)}
            elif tool_name == "review_code":
                file_path = kwargs.get("file_path", "")
                try:
                    from code_review_graph import analyze_file
                    analysis = analyze_file(file_path)
                    return {"result": str(analysis)}
                except ImportError:
                    return {"error": "code-review-graph not installed"}
                except Exception as e:
                    return {"error": str(e)}
            elif tool_name == "create_file":
                file_path = kwargs.get("file_path", "")
                content = kwargs.get("content", "")
                try:
                    from pathlib import Path
                    import json
                    
                    path = Path(file_path)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Format JSON files for human readability
                    if file_path.endswith('.excalidraw') or file_path.endswith('.json'):
                        try:
                            # Parse and reformat JSON with proper indentation
                            parsed_json = json.loads(content)
                            formatted_content = json.dumps(parsed_json, indent=2, ensure_ascii=False)
                            path.write_text(formatted_content, encoding='utf-8')
                        except json.JSONDecodeError:
                            # If JSON parsing fails, write as-is
                            path.write_text(content, encoding='utf-8')
                    else:
                        path.write_text(content, encoding='utf-8')
                    
                    return {"result": f"Successfully created: {file_path}"}
                except Exception as e:
                    return {"error": str(e)}
            elif tool_name == "create_directory":
                dir_path = resolve_directory_path(kwargs)
                try:
                    from pathlib import Path
                    path = Path(dir_path)
                    path.mkdir(parents=True, exist_ok=True)
                    return {"result": f"Successfully created directory: {dir_path}"}
                except Exception as e:
                    return {"error": str(e)}
            elif tool_name == "edit_file":
                file_path = kwargs.get("file_path", "")
                content = kwargs.get("content", "")
                try:
                    from pathlib import Path
                    import json
                    
                    path = Path(file_path)
                    if not path.exists():
                        return {"error": f"File does not exist: {file_path}"}
                    
                    # Format JSON files for human readability
                    if file_path.endswith('.excalidraw') or file_path.endswith('.json'):
                        try:
                            # Parse and reformat JSON with proper indentation
                            parsed_json = json.loads(content)
                            formatted_content = json.dumps(parsed_json, indent=2, ensure_ascii=False)
                            path.write_text(formatted_content, encoding='utf-8')
                        except json.JSONDecodeError:
                            # If JSON parsing fails, write as-is
                            path.write_text(content, encoding='utf-8')
                    else:
                        path.write_text(content, encoding='utf-8')
                    
                    return {"result": f"Successfully updated: {file_path}"}
                except Exception as e:
                    return {"error": str(e)}
            elif tool_name == "delete_file":
                file_path = kwargs.get("file_path", "")
                try:
                    from pathlib import Path
                    path = Path(file_path)
                    if path.exists():
                        path.unlink()
                        return {"result": f"Successfully deleted: {file_path}"}
                    return {"result": f"File not found: {file_path}"}
                except Exception as e:
                    return {"error": str(e)}
            elif tool_name == "run_command":
                from voxprime.core.shell_runner import run_shell_command

                command = kwargs.get("command", "")
                timeout = kwargs.get("timeout")
                if timeout is not None:
                    timeout = int(timeout)
                try:
                    out = await asyncio.to_thread(
                        run_shell_command, command, timeout=timeout
                    )
                    if "error" in out:
                        return {"error": out["error"]}
                    payload: dict = {"result": out.get("result", "")}
                    if "exit_code" in out:
                        payload["exit_code"] = out["exit_code"]
                    return payload
                except Exception as e:
                    return {"error": str(e)}
            else:
                return {"error": f"Unknown tool: {tool_name}"}
        except Exception as e:
            return {"error": str(e)}

    async def _search_web(self, query: str) -> dict:
        """Search web via DuckDuckGo with timeout."""
        search_url = f"https://html.duckduckgo.com/html/?q={httpx.URL(query)}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                response = await client.get(search_url, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True)
                content = response.text
                import re
                snippets = re.findall(r'<p class="result__snippet"[^>]*>([^<]+)</p>', content, re.DOTALL)
                if snippets:
                    cleaned = [re.sub(r'<[^>]+>', '', s).strip()[:200] for s in snippets[:3]]
                    return {"result": "\n".join(f"- {c}" for c in cleaned)}
                return {"result": f"Search completed for: {query}"}
            except httpx.ReadTimeout:
                return {"result": f"Search timeout for: {query}. Try a simpler query."}
            except Exception as e:
                return {"error": str(e)}


# ---------------------------------------------------------------------------
