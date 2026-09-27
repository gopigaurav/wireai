"""
Tool registry — imports and registers all tool modules with the MCP server.
Add new tool modules here as you build them.
"""

from voxprime.tools import system, files, web, code_review, media


def register_all_tools(mcp):
    """Register all tool groups onto the MCP server instance."""
    system.register(mcp)
    files.register(mcp)
    web.register(mcp)
    media.register(mcp)
    code_review.register(mcp)
