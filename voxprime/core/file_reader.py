"""
Line-range file reading for large sources (Cursor-style chunks).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

DEFAULT_LINES_PER_CHUNK = int(os.getenv("GROUNDWIRE_LINES_PER_CHUNK", "1000"))


def count_lines(path: str) -> int:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return sum(1 for _ in f)


def read_line_range(path: str, start_line: int, end_line: int) -> str:
    """Read inclusive 1-based line range."""
    if start_line < 1:
        start_line = 1
    lines: List[str] = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, start=1):
            if i < start_line:
                continue
            if i > end_line:
                break
            lines.append(f"{i:6d}| {line.rstrip()}")
    return "\n".join(lines)


def chunk_ranges(total_lines: int, lines_per_chunk: int) -> List[tuple[int, int]]:
    ranges: List[tuple[int, int]] = []
    start = 1
    while start <= total_lines:
        end = min(start + lines_per_chunk - 1, total_lines)
        ranges.append((start, end))
        start = end + 1
    return ranges


def read_file_chunked_text(
    path: str,
    lines_per_chunk: int = DEFAULT_LINES_PER_CHUNK,
    max_chunks: Optional[int] = None,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
) -> str:
    """
    Return formatted file content. Large files are split into labeled chunks.
    Optional start_line/end_line reads a single range (1-based, inclusive).
    """
    abs_path = os.path.abspath(path)
    if not os.path.isfile(abs_path):
        return f"[Error] File not found: {path}"

    total = count_lines(abs_path)

    if start_line is not None or end_line is not None:
        s = start_line or 1
        e = end_line or total
        body = read_line_range(abs_path, s, e)
        return (
            f"=== FILE: {abs_path} (lines {s}-{e} of {total}) ===\n"
            f"{body}\n=== END lines {s}-{e} ==="
        )

    ranges = chunk_ranges(total, lines_per_chunk)
    if max_chunks is not None:
        ranges = ranges[:max_chunks]

    parts = [
        f"=== FILE: {abs_path} ({total} lines, {len(chunk_ranges(total, lines_per_chunk))} chunk(s) of up to {lines_per_chunk} lines) ==="
    ]
    for i, (s, e) in enumerate(ranges, 1):
        parts.append(f"\n--- CHUNK {i}/{len(ranges)}: lines {s}-{e} ---\n")
        parts.append(read_line_range(abs_path, s, e))
        parts.append(f"\n--- END CHUNK {i} ---")

    remaining = len(chunk_ranges(total, lines_per_chunk)) - len(ranges)
    if remaining > 0:
        parts.append(
            f"\n[{remaining} more chunk(s) not loaded — use read_file with "
            f"start_line/end_line or ask to continue from line {ranges[-1][1] + 1}.]"
        )
    return "\n".join(parts)


def active_file_store_path() -> Path:
    return Path.cwd() / ".groundwire" / "active_file"


def load_persisted_active_file() -> Optional[str]:
    p = active_file_store_path()
    if not p.is_file():
        return None
    text = p.read_text(encoding="utf-8").strip()
    if text and os.path.isfile(text):
        return os.path.abspath(text)
    return None


def persist_active_file(path: str) -> None:
    p = active_file_store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(os.path.abspath(path), encoding="utf-8")
