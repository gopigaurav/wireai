"""Single stdin reader for REPL + permission prompts (enables message queue while agent runs)."""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from contextlib import contextmanager
from typing import Optional

_broker: Optional["StdinBroker"] = None


class StdinBroker:
    """
    One background thread reads stdin; lines route to either an active permission
    prompt or the user message inbox (asyncio.Queue).
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._user_q: asyncio.Queue[str] = asyncio.Queue()
        self._choice_q: Optional[asyncio.Queue[str]] = None
        self._running = True
        self._read_enabled = True

    def pause_reading(self) -> None:
        """Let subprocesses (npx/npm) read from the real console stdin."""
        self._read_enabled = False

    def resume_reading(self) -> None:
        self._read_enabled = True

    def start(self) -> None:
        threading.Thread(target=self._reader, name="voxprime-stdin", daemon=True).start()

    def _reader(self) -> None:
        while self._running:
            if not self._read_enabled:
                time.sleep(0.05)
                continue
            try:
                line = sys.stdin.readline()
            except Exception:
                break
            if line == "":
                self._loop.call_soon_threadsafe(self._user_q.put_nowait, "")
                break
            line = line.rstrip("\r\n")
            self._loop.call_soon_threadsafe(self._deliver, line)

    def _deliver(self, line: str) -> None:
        if self._choice_q is not None:
            try:
                self._choice_q.put_nowait(line)
            except asyncio.QueueFull:
                pass
            return
        self._user_q.put_nowait(line)

    async def read_user(self, prompt: str | None = "You: ") -> str:
        """Read a user line. prompt=None waits silently (for queue while agent runs)."""
        if prompt is not None:
            print(prompt, end="", flush=True)
        return await self._user_q.get()

    async def read_user_timed(
        self, prompt: str | None, timeout: float
    ) -> str | None:
        """Like read_user, but returns None on timeout (so REPL can exit busy-wait)."""
        if prompt is not None:
            print(prompt, end="", flush=True)
        try:
            return await asyncio.wait_for(self._user_q.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def read_choice(self, prompt: str) -> str:
        print(prompt, end="", flush=True)
        self._choice_q = asyncio.Queue(maxsize=1)
        try:
            return await self._choice_q.get()
        finally:
            self._choice_q = None

    def stop(self) -> None:
        self._running = False


def install_broker(loop: asyncio.AbstractEventLoop) -> StdinBroker:
    global _broker
    _broker = StdinBroker(loop)
    _broker.start()
    return _broker


def get_broker() -> Optional[StdinBroker]:
    return _broker


@contextmanager
def pause_broker_for_subprocess():
    """While a shell tool runs, do not steal stdin from npx/npm prompts."""
    broker = get_broker()
    if broker:
        broker.pause_reading()
    try:
        yield
    finally:
        if broker:
            broker.resume_reading()
