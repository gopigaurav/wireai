"""Resolve tool path arguments (aliases, workspace-relative paths)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping


def _first_path_value(kwargs: Mapping[str, Any]) -> str:
    for key in ("dir_path", "directory", "path", "folder", "file_path", "filepath"):
        val = kwargs.get(key)
        if val is not None and str(val).strip():
            return str(val).strip().strip('"').strip("'")
    return "."


def resolve_directory_path(kwargs: Mapping[str, Any], cwd: str | None = None) -> str:
    raw = _first_path_value(kwargs)
    base = cwd or os.getcwd()
    if os.path.isabs(raw):
        return os.path.normpath(raw)
    candidate = os.path.join(base, raw)
    return os.path.normpath(os.path.abspath(candidate))


def resolve_file_path(kwargs: Mapping[str, Any], cwd: str | None = None) -> str:
    raw = _first_path_value(kwargs)
    if raw == ".":
        return raw
    base = cwd or os.getcwd()
    if os.path.isabs(raw):
        return os.path.normpath(raw)
    return os.path.normpath(os.path.abspath(os.path.join(base, raw)))
