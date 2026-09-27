"""Unified MCP hub: built-in tools + user-configured external servers (git, …)."""

from __future__ import annotations

import asyncio
import httpx
from typing import Any, Dict, List, Optional, Tuple

from voxprime.mcp.builtin_tools import BuiltinToolExecutor
from voxprime.mcp.config import load_mcp_servers, normalize_server_spec
from voxprime.mcp.external_server import ExternalMCPServer

# Official git MCP tool names that modify repo state
GIT_WRITE_TOOLS = frozenset(
    {
        "git_add",
        "git_commit",
        "git_create_branch",
        "git_checkout",
    }
)


class MCPHub:
    """
    Agent-facing MCP client.
    - Built-in tools (files, web, media, …) run in-process.
    - External tools come from `.voxprime/mcp.json` (default: git via uvx mcp-server-git).
    """

    def __init__(self, server_url: str):
        self.server_url = server_url
        self._connected = False
        self.builtin = BuiltinToolExecutor()
        self.external: Dict[str, ExternalMCPServer] = {}
        self._tool_routes: Dict[str, Tuple[str, str]] = {}

    async def connect(self) -> bool:
        """Fast connect: SSE health only (built-in tools work without external MCP)."""
        await self._check_sse_health()
        self._connected = True
        return True

    async def connect_external(self) -> None:
        """Start user-configured stdio MCP servers (git, …). Safe to call after first chat turn."""
        await self._connect_external_servers()

    async def disconnect(self) -> None:
        for server in list(self.external.values()):
            try:
                await server.disconnect()
            except (RuntimeError, asyncio.CancelledError, Exception):
                pass
        self.external.clear()
        self._tool_routes.clear()

    async def _check_sse_health(self) -> None:
        try:
            async with httpx.AsyncClient() as client:
                url = self.server_url.replace("/sse", "/health")
                response = await client.get(url, timeout=2)
                if response.status_code == 200:
                    print(f"[OK] VoxPrime MCP server reachable at {self.server_url}")
                    return
        except Exception:
            pass
        print(f"[WARN] VoxPrime MCP server may not be running at {self.server_url}")
        print("  Start it with: python server.py")

    async def _connect_external_servers(self) -> None:
        servers = load_mcp_servers()
        for name, spec in servers.items():
            spec = normalize_server_spec(name, spec)
            if spec.get("enabled") is False:
                continue
            command = spec.get("command")
            args = spec.get("args") or []
            if not command:
                print(f"[WARN] MCP server '{name}' missing command — skipped")
                continue
            env = spec.get("env") or None
            server = ExternalMCPServer(name, command, list(args), env=env)
            try:
                print(f"[MCP] Connecting to '{name}' ({command} {' '.join(args)})...")
                await server.connect()
                self.external[name] = server
                for tool in server.tool_names:
                    self._register_tool_route(tool, name, tool)
                print(f"[OK] MCP '{name}' — {len(server.tool_names)} tools")
            except Exception as e:
                try:
                    await server.disconnect()
                except Exception:
                    pass
                print(f"[WARN] MCP server '{name}' failed to start: {e}")
                if name == "git":
                    print(
                        "       Git MCP optional — built-in file tools still work. "
                        "Install: uvx mcp-server-git  or set git.enabled=false in .voxprime/mcp.json"
                    )
                else:
                    print(f"       Check command/args for MCP server '{name}'.")

    def _register_tool_route(self, exposed_name: str, server_name: str, real_name: str) -> None:
        if exposed_name in self._tool_routes and self._tool_routes[exposed_name][0] != server_name:
            exposed_name = f"{server_name}__{real_name}"
        self._tool_routes[exposed_name] = (server_name, real_name)

    def list_tool_names(self) -> List[str]:
        names = set(self.builtin.list_tool_names())
        names.update(self._tool_routes.keys())
        return sorted(names)

    def is_git_write_tool(self, tool_name: str) -> bool:
        _, real = self._tool_routes.get(tool_name, (None, tool_name))
        return real in GIT_WRITE_TOOLS or tool_name in GIT_WRITE_TOOLS

    async def call_tool(self, tool_name: str, **kwargs) -> dict:
        if tool_name in self._tool_routes:
            server_name, real_name = self._tool_routes[tool_name]
            server = self.external.get(server_name)
            if not server:
                return {"error": f"MCP server '{server_name}' not connected"}
            args = dict(kwargs)
            if "repo_path" not in args and server_name == "git":
                import os

                args.setdefault("repo_path", os.getcwd())
            return await server.call_tool(real_name, args)
        return await self.builtin.call_tool(tool_name, **kwargs)

    # Back-compat alias
    async def call_tool_builtin_only(self, tool_name: str, **kwargs) -> dict:
        return await self.builtin.call_tool(tool_name, **kwargs)
