"""
Media tools — documents, images, and web pages (Claude / Cursor-style).
"""

from voxprime.core.media_ingest import (
    extract_document_text,
    fetch_webpage_markdown,
    ingest_paths,
    load_image_base64,
    model_supports_vision,
)


def register(mcp):

    @mcp.tool()
    def read_document(file_path: str, max_chars: int = 48000) -> str:
        """
        Read PDF, DOCX, TXT, MD, HTML, CSV, JSON and return extracted text.
        Large files are truncated to max_chars.
        """
        return extract_document_text(file_path, max_chars=max_chars)

    @mcp.tool()
    def fetch_webpage(url: str, max_chars: int = 32000) -> str:
        """
        Fetch a URL and return readable text (HTML converted to markdown/plain).
        """
        return fetch_webpage_markdown(url, max_chars=max_chars)

    @mcp.tool()
    def describe_image(file_path: str, model: str = "") -> str:
        """
        Load an image for vision analysis. Returns base64 metadata or a hint to use a vision model.
        Prefer asking the agent with /attach when using a vision-capable Ollama model.
        """
        from voxprime.config import config

        model_name = model or config.LLM_MODEL
        if not model_supports_vision(model_name):
            return (
                f"Model `{model_name}` does not appear vision-capable. "
                f"Pull a vision model (e.g. llava, qwen2.5vl) or set VOXPRIME_FORCE_VISION=1."
            )
        try:
            b64 = load_image_base64(file_path)
            return (
                f"Image loaded ({len(b64)} base64 chars) from {file_path}. "
                "Use chat with images enabled to analyze."
            )
        except Exception as e:
            return f"Error loading image: {e}"

    @mcp.tool()
    def ingest_attachments(file_paths: str, model: str = "") -> str:
        """
        Ingest one or more comma-separated file paths (pdf, docx, images, text).
        Returns extracted text summary for documents.
        """
        from voxprime.config import config

        model_name = model or config.LLM_MODEL
        paths = [p.strip() for p in file_paths.split(",") if p.strip()]
        text, _ = ingest_paths(paths, model_name)
        return text or "[No content extracted]"
