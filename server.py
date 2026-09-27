"""
Groundwire MCP Server — Entry Point
Run with: python server.py
"""

from mcp.server.fastmcp import FastMCP
from voxprime.tools import register_all_tools
from voxprime.workflows import register_workflows

# Create the MCP server instance
mcp = FastMCP(
    name="VoxPrime",
    instructions=(
        "You are VoxPrime, a local AI assistant with tools for coding and automation. "
        "You have access to tools for file operations, web search, code analysis, and more. "
        "Be concise, accurate, and proactive."
    ),
)

# Register tools and workflows
register_all_tools(mcp)
register_workflows(mcp)


def main():
    mcp.run(transport='sse')


if __name__ == "__main__":
    main()
