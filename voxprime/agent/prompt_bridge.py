"""Route permission prompts to the Textual input bar when TUI is active."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from voxprime.tui.chat_app import VoxPrimeChatApp

_app: Optional["VoxPrimeChatApp"] = None


def register_tui_app(app: "VoxPrimeChatApp") -> None:
    global _app
    _app = app


def is_tui_active() -> bool:
    return _app is not None


async def tui_read_choice(prompt: str) -> str:
    if _app is None:
        raise RuntimeError("TUI not active")
    return await _app.ask_permission(prompt)
