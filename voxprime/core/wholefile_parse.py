"""Parse whole-file blocks from model output (filename line + fenced body)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

_FILENAME_LINE = re.compile(
    r"^[`'\"]?([\w./\\:-]+\.(?:md|markdown|txt|rst|py|json|ya?ml|toml|jsx?|tsx?|css|html|vue|svelte))[`'\"]?\s*$",
    re.IGNORECASE,
)


def parse_wholefile_writes(text: str) -> List[Tuple[str, str]]:
    """
    Detect writes like:

        youtube_system_design.md
        ```markdown
        # Title
        ...
        ```
    """
    if not text or not text.strip():
        return []

    lines = text.splitlines()
    results: List[Tuple[str, str]] = []
    i = 0
    while i < len(lines):
        m = _FILENAME_LINE.match(lines[i].strip())
        if not m:
            i += 1
            continue

        rel_path = m.group(1).strip().strip('"').strip("'")
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines) or not lines[j].strip().startswith("```"):
            i += 1
            continue

        j += 1  # skip opening fence
        body_lines: List[str] = []
        while j < len(lines):
            if lines[j].strip().startswith("```"):
                break
            body_lines.append(lines[j])
            j += 1

        body = "\n".join(body_lines)
        if body.strip():
            results.append((rel_path, body if body.endswith("\n") else body + "\n"))
        i = j + 1 if j < len(lines) else len(lines)

    return results


def resolve_write_path(rel_path: str, cwd: str) -> str:
    p = Path(rel_path)
    if p.is_absolute():
        return str(p)
    return str((Path(cwd) / p).resolve())
