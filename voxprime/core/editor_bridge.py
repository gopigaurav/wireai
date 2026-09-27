"""Sync focused editor file from VS Code / Cursor into the CLI agent (Cursor-style)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

_DEFAULT_TTL = int(os.getenv("VOXPRIME_EDITOR_BRIDGE_TTL", "300"))


def editor_context_path(workspace_root: str | None = None) -> Path:
    root = workspace_root or os.getcwd()
    return Path(root).resolve() / ".voxprime" / "editor_context.json"


def write_editor_context(
    *,
    active_file: str,
    workspace_folder: str = "",
    selection: str = "",
    workspace_root: str | None = None,
) -> None:
    path = editor_context_path(workspace_root or workspace_folder or os.getcwd())
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "activeFile": os.path.abspath(active_file) if active_file else "",
        "workspaceFolder": workspace_folder or "",
        "selection": selection or "",
        "updatedAt": time.time(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_editor_context(
    workspace_root: str | None = None,
    *,
    max_age_seconds: int | None = None,
) -> Optional[dict[str, Any]]:
    """Return bridge data if file exists and is fresh enough."""
    ttl = max_age_seconds if max_age_seconds is not None else _DEFAULT_TTL
    path = editor_context_path(workspace_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    updated = float(data.get("updatedAt") or 0)
    if ttl > 0 and updated and (time.time() - updated) > ttl:
        return None
    active = (data.get("activeFile") or data.get("active_file") or "").strip()
    if active and not os.path.isfile(active):
        return None
    return data


def load_focused_editor_file(workspace_root: str | None = None) -> Optional[str]:
    data = load_editor_context(workspace_root)
    if not data:
        return None
    active = (data.get("activeFile") or data.get("active_file") or "").strip()
    if active and os.path.isfile(active):
        return os.path.abspath(active)
    return None
