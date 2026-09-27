"""stdio MCP server subprocess (git, fetch, user-configured servers)."""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


def _format_call_result(result: Any) -> dict:
    parts: List[str] = []
    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if text:
            parts.append(text)
    text = "\n".join(parts).strip()
    is_error = bool(getattr(result, "isError", False))
    if is_error:
        return {"error": text or "MCP tool returned an error"}
    return {"result": text or "(empty result)"}


class ExternalMCPServer:
    """One configured MCP server (e.g. mcp-server-git)."""

    def __init__(self, name: str, command: str, args: List[str], env: Optional[Dict[str, str]] = None):
        self.name = name
        self.command = command
        self.args = args
        self.env = env
        self.tool_names: List[str] = []
        self._stack: Optional[AsyncExitStack] = None
        self._session: Optional[ClientSession] = None

    async def connect(self) -> None:
        params = StdioServerParameters(command=self.command, args=self.args, env=self.env)
        stack = AsyncExitStack()
        try:
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            listed = await session.list_tools()
            self.tool_names = [t.name for t in listed.tools]
            self._stack = stack
            self._session = session
            logger.info("MCP server %s tools: %s", self.name, self.tool_names)
        except BaseException:
            await stack.aclose()
            self._stack = None
            self._session = None
            self.tool_names = []
            raise

    async def disconnect(self) -> None:
        if self._stack:
            await self._stack.aclose()
            self._stack = None
            self._session = None

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> dict:
        if not self._session:
            return {"error": f"MCP server '{self.name}' is not connected"}
        try:
            result = await self._session.call_tool(tool_name, arguments=arguments or {})
            return _format_call_result(result)
        except Exception as e:
            return {"error": f"MCP {self.name}.{tool_name} failed: {e}"}
