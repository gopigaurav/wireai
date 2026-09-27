"""
Ingest images, documents, and web pages for the agent (Cursor / Claude-style attachments).

Text formats are extracted into the prompt; images are passed to Ollama vision models when available.
"""

from __future__ import annotations

import base64
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import httpx

# Extensions (aligned with common agent tooling; PDF treated as document text unless vision model)
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}
DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".csv",
    ".json",
    ".xml",
    ".html",
    ".htm",
}
WEB_FETCH_MAX_CHARS = int(os.getenv("VOXPRIME_WEB_MAX_CHARS", "32000"))
DOCUMENT_MAX_CHARS = int(os.getenv("VOXPRIME_DOCUMENT_MAX_CHARS", "48000"))

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)


def _url_ok_for_auto_fetch(url: str) -> bool:
    """Skip localhost, MCP/SSE endpoints, and other non-page URLs."""
    try:
        parsed = urlparse(url.rstrip(".,;"))
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        return False
    path = (parsed.path or "").lower()
    if path.endswith("/sse") or path.endswith("/mcp"):
        return False
    return True
ATTACH_AT_RE = re.compile(
    r"@([^\s]+\.(?:pdf|docx?|png|jpe?g|webp|gif|bmp|html?|htm|txt|md|markdown|csv|json))",
    re.IGNORECASE,
)


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: List[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip = False
        if tag in ("p", "div", "br", "li", "h1", "h2", "h3", "tr"):
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self._chunks.append(data)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self._chunks)).strip()


def classify_path(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in DOCUMENT_EXTENSIONS:
        return "document"
    return "unknown"


def model_supports_vision(model_name: str) -> bool:
    m = (model_name or "").lower()
    if os.getenv("VOXPRIME_FORCE_VISION", "").strip() in ("1", "true", "yes"):
        return True
    return any(
        token in m
        for token in (
            "vision",
            "vl",
            "llava",
            "bakllava",
            "moondream",
            "minicpm-v",
            "gemma3",
            "llama3.2-vision",
            "qwen2.5vl",
            "qwen3-vl",
        )
    )


def load_image_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return (
            "[PDF] Install optional dependency: pip install pypdf\n"
            f"File: {path}"
        )
    reader = PdfReader(str(path))
    parts = []
    for i, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        if text.strip():
            parts.append(f"\n--- Page {i} ---\n{text}")
    return "\n".join(parts) if parts else "[PDF contained no extractable text]"


def _extract_docx(path: Path) -> str:
    try:
        from docx import Document
    except ImportError:
        return (
            "[DOCX] Install optional dependency: pip install python-docx\n"
            f"File: {path}"
        )
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def extract_document_text(path: str, max_chars: int = DOCUMENT_MAX_CHARS) -> str:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return f"[Error] File not found: {path}"

    ext = p.suffix.lower()
    try:
        if ext == ".pdf":
            body = _extract_pdf(p)
        elif ext in (".docx", ".doc"):
            if ext == ".doc":
                return "[.doc] Convert to .docx or use a vision model; binary .doc not supported."
            body = _extract_docx(p)
        elif ext in (".html", ".htm"):
            body = html_to_text(p.read_text(encoding="utf-8", errors="replace"))
        else:
            body = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"[Error reading {p.name}]: {e}"

    header = f"=== Document: {p} ({ext}) ===\n"
    if len(body) > max_chars:
        body = body[:max_chars] + f"\n\n... [truncated at {max_chars} chars]"
    return header + body + "\n=== End document ==="


def html_to_text(html: str) -> str:
    try:
        import html2text

        h = html2text.HTML2Text()
        h.ignore_links = False
        h.body_width = 0
        return h.handle(html).strip()
    except ImportError:
        parser = _HTMLTextExtractor()
        parser.feed(html)
        return parser.text()


def fetch_webpage_markdown(url: str, max_chars: int = WEB_FETCH_MAX_CHARS) -> str:
    headers = {
        "User-Agent": "VoxPrime/0.1 (+https://github.com; local agent)",
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
    }
    try:
        with httpx.Client(follow_redirects=True, timeout=20.0, headers=headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            ctype = (resp.headers.get("content-type") or "").lower()
            raw = resp.text
    except Exception as e:
        return f"[Error fetching {url}]: {e}"

    if "html" in ctype or raw.lstrip().startswith("<!DOCTYPE") or raw.lstrip().startswith("<html"):
        text = html_to_text(raw)
    else:
        text = raw

    title = urlparse(url).netloc or url
    header = f"=== Web page: {url} ===\n"
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n... [truncated at {max_chars} chars]"
    return header + text + f"\n=== End {title} ==="


def resolve_attachment_path(name: str, cwd: Optional[str] = None) -> Optional[str]:
    candidate = name.strip().strip('"').strip("'")
    if os.path.isabs(candidate) and os.path.isfile(candidate):
        return os.path.abspath(candidate)
    bases = [cwd or os.getcwd(), os.path.dirname(os.path.abspath(__file__))]
    for base in bases:
        path = os.path.join(base, candidate)
        if os.path.isfile(path):
            return os.path.abspath(path)
    return None


def ingest_paths(
    paths: List[str],
    model_name: str,
    cwd: Optional[str] = None,
) -> Tuple[str, List[str]]:
    """
    Returns (text_block_to_append, base64_images_for_ollama).
    """
    text_parts: List[str] = []
    images: List[str] = []
    vision = model_supports_vision(model_name)

    for raw in paths:
        resolved = resolve_attachment_path(raw, cwd=cwd)
        if not resolved:
            text_parts.append(f"[Attachment not found: {raw}]")
            continue

        kind = classify_path(resolved)
        if kind == "image":
            if vision:
                try:
                    images.append(load_image_base64(resolved))
                    text_parts.append(
                        f"[Image attached for vision model: {resolved} — analyze visually.]"
                    )
                except Exception as e:
                    text_parts.append(f"[Image read error {resolved}]: {e}")
            else:
                text_parts.append(
                    f"[Image `{resolved}` — current model may not support vision. "
                    f"Use a vision model (e.g. llava, qwen2.5vl) or set VOXPRIME_VISION_MODEL.]"
                )
        elif kind == "document":
            text_parts.append(extract_document_text(resolved))
        else:
            text_parts.append(extract_document_text(resolved))

    return "\n\n".join(text_parts), images


def enrich_prompt_with_media(
    user_text: str,
    model_name: str,
    extra_paths: Optional[List[str]] = None,
    fetch_urls: bool = True,
    cwd: Optional[str] = None,
) -> Tuple[str, List[str]]:
    """
    Parse @paths and URLs from the user message; append extracted content.
    """
    paths = list(extra_paths or [])
    for m in ATTACH_AT_RE.finditer(user_text):
        paths.append(m.group(1))

    # Quoted file paths in message
    for m in re.finditer(
        r"[`'\"]([^`'\"]+\.(?:pdf|docx?|png|jpe?g|webp|gif|html?|txt|md))[`'\"]",
        user_text,
        re.I,
    ):
        paths.append(m.group(1))

    text = user_text
    images: List[str] = []

    if fetch_urls:
        for url in URL_RE.findall(user_text):
            if not _url_ok_for_auto_fetch(url):
                continue
            print(f"\n[Fetching page] {url}\n")
            text += "\n\n" + fetch_webpage_markdown(url)

    if paths:
        seen = set()
        unique = []
        for p in paths:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        block, imgs = ingest_paths(unique, model_name, cwd=cwd)
        images.extend(imgs)
        if block.strip():
            text += "\n\n[Attached content]\n" + block

    return text, images
