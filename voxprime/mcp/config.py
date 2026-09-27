"""Load user MCP server definitions (Cursor / Claude compatible shape)."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict

_ENV_REPO = os.environ.get("VOXPRIME_GIT_REPO", os.environ.get("VOXPRIME_WORKSPACE", ""))


def _default_git_server() -> Dict[str, Any]:
    repo = _ENV_REPO or os.getcwd()
    uvx = os.environ.get("VOXPRIME_UVX", "uvx")
    has_uvx = shutil.which(uvx) is not None
    skip = os.environ.get("VOXPRIME_MCP_SKIP_GIT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    return {
        "git": {
            "enabled": has_uvx and not skip,
            "command": uvx,
            "args": ["mcp-server-git", "--repository", repo],
            "env": {},
        }
    }


def config_search_paths() -> list[Path]:
    paths: list[Path] = []
    if os.environ.get("VOXPRIME_MCP_CONFIG"):
        paths.append(Path(os.environ["VOXPRIME_MCP_CONFIG"]))
    paths.append(Path.cwd() / ".voxprime" / "mcp.json")
    paths.append(Path.home() / ".config" / "voxprime" / "mcp.json")
    return paths


def load_mcp_servers() -> Dict[str, Any]:
    """Return mcpServers dict from first existing config file, else default git."""
    for path in config_search_paths():
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            servers = data.get("mcpServers", data)
            if isinstance(servers, dict):
                return servers
    return _default_git_server()


def expand_env(value: str) -> str:
    return os.path.expandvars(value.replace("${VOXPRIME_WORKSPACE}", os.getcwd()))


def normalize_server_spec(name: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve env vars in command/args for a single server entry."""
    if spec.get("enabled") is False:
        return spec
    out = dict(spec)
    if "command" in out:
        out["command"] = expand_env(str(out["command"]))
    if "args" in out:
        out["args"] = [expand_env(str(a)) for a in out["args"]]
    if "env" in out and out["env"]:
        out["env"] = {k: expand_env(str(v)) for k, v in out["env"].items()}
    return out
