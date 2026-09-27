"""
File system tools — read, write, search, and manage files.
"""

import os
from pathlib import Path


def register(mcp):

    @mcp.tool()
    def read_file(file_path: str) -> str:
        """
        Read the contents of a file.
        Returns the full text content of the file.
        """
        try:
            path = Path(file_path).expanduser().resolve()
            if not path.exists():
                return f"Error: File not found: {file_path}"
            if not path.is_file():
                return f"Error: Not a file: {file_path}"
            return path.read_text(encoding='utf-8')
        except Exception as e:
            return f"Error reading file: {e}"

    @mcp.tool()
    def write_file(file_path: str, content: str) -> str:
        """
        Write content to a file, overwriting if it exists.
        Returns a success message or error.
        """
        try:
            path = Path(file_path).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
            return f"Successfully wrote to {file_path}"
        except Exception as e:
            return f"Error writing file: {e}"

    @mcp.tool()
    def list_directory(dir_path: str) -> list[str]:
        """
        List files and directories in a given path.
        Returns a list of entry names.
        """
        try:
            path = Path(dir_path).expanduser().resolve()
            if not path.exists():
                return [f"Error: Directory not found: {dir_path}"]
            if not path.is_dir():
                return [f"Error: Not a directory: {dir_path}"]
            entries = sorted([e.name for e in path.iterdir()])
            return entries
        except Exception as e:
            return [f"Error listing directory: {e}"]

    @mcp.tool()
    def search_files(pattern: str, root_path: str = ".") -> list[str]:
        """
        Search for files matching a glob pattern.
        Returns a list of matching file paths.
        """
        try:
            root = Path(root_path).expanduser().resolve()
            matches = list(root.glob(pattern))
            return [str(m) for m in matches]
        except Exception as e:
            return [f"Error searching files: {e}"]

    @mcp.tool()
    def file_exists(file_path: str) -> bool:
        """Check if a file exists."""
        path = Path(file_path).expanduser().resolve()
        return path.exists() and path.is_file()

    @mcp.tool()
    def directory_exists(dir_path: str) -> bool:
        """Check if a directory exists."""
        path = Path(dir_path).expanduser().resolve()
        return path.exists() and path.is_dir()
