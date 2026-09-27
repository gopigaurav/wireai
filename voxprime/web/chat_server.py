"""
Browser chat UI for VoxPrime (stdlib HTTP). Same AgentWithTools as the CLI.

  python -m voxprime.web.chat_server
  python -m voxprime.web.chat_server --port 8765
"""

from __future__ import annotations

import argparse
import asyncio
import json
import queue
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

STATIC_DIR = Path(__file__).resolve().parent / "static"

_agent = None
_agent_lock = threading.Lock()


def _import_agent_class():
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from agent_with_tools import AgentWithTools

    return AgentWithTools


async def _run_chat_streaming(
    message: str,
    emit: Callable[[dict], None],
    ide_context: dict | None = None,
) -> None:
    global _agent
    with _agent_lock:
        if _agent is None:
            cls = _import_agent_class()
            _agent = cls()
            await _agent.mcp_client.connect()
            await _agent.mcp_client.connect_external()
        agent = _agent
        agent.web_event_sink = emit
        try:
            await agent.chat_stream(message, ide_context=ide_context)
        finally:
            agent.web_event_sink = None
        emit({"type": "turn_done", "activity": agent.turn_activity.lines})


def _stream_chat_ndjson(
    message: str,
    write_line: Callable[[bytes], None],
    ide_context: dict | None = None,
) -> None:
    q: queue.Queue[Any] = queue.Queue()

    def emit(event: dict) -> None:
        q.put(event)

    def worker() -> None:
        try:
            asyncio.run(_run_chat_streaming(message, emit, ide_context))
        except Exception as exc:
            q.put({"type": "error", "message": str(exc)})
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    while True:
        item = q.get()
        if item is None:
            break
        line = json.dumps(item, ensure_ascii=False) + "\n"
        write_line(line.encode("utf-8"))


class ChatHandler(BaseHTTPRequestHandler):
    server_version = "VoxPrimeChat/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[chat-web] {self.address_string()} - {format % args}")

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            data = (STATIC_DIR / "index.html").read_bytes()
            self._send_bytes(200, data, "text/html; charset=utf-8")
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/api/chat":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8"))
            message = str(data.get("message", "")).strip()
            ide_context = data.get("ide_context") or data.get("context")
            if ide_context is not None and not isinstance(ide_context, dict):
                ide_context = None
            if not message:
                self._send_json(400, {"error": "message required"})
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            def write_chunk(chunk: bytes) -> None:
                self.wfile.write(chunk)
                self.wfile.flush()

            _stream_chat_ndjson(message, write_chunk, ide_context)
        except Exception as exc:
            if not self.wfile.closed:
                try:
                    self._send_json(500, {"error": str(exc)})
                except Exception:
                    pass


def main() -> None:
    parser = argparse.ArgumentParser(description="VoxPrime browser chat")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), ChatHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"VoxPrime chat UI at {url}")
    print("Uses the same agent as agent_with_tools.py (output also appears in this terminal).")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        httpd.shutdown()


if __name__ == "__main__":
    main()
