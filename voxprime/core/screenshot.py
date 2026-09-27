"""Clipboard screenshot capture for CLI (optional Pillow)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def capture_clipboard_to_png(dest: Path) -> tuple[bool, str]:
    """
    Save Windows/macOS clipboard image to dest.
    Returns (ok, message).
    """
    try:
        from PIL import ImageGrab  # type: ignore
    except ImportError:
        return (
            False,
            "Install Pillow for /screenshot: pip install pillow\n"
            "Or save a PNG (Win+Shift+S) and use: /attach shot.png -- describe this",
        )

    try:
        img = ImageGrab.grabclipboard()
    except Exception as e:
        return False, f"Could not read clipboard: {e}"

    if img is None:
        return False, "Clipboard has no image. Copy a screenshot first (e.g. Win+Shift+S)."

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="PNG")
    return True, str(dest.resolve())
