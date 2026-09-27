"""
System tools — time, environment info, shell commands, etc.
"""

import datetime
import platform
import subprocess


def register(mcp):

    @mcp.tool()
    def get_current_time() -> str:
        """Return the current date and time in ISO 8601 format."""
        return datetime.datetime.now().isoformat()

    @mcp.tool()
    def get_system_info() -> dict:
        """Return basic information about the host system."""
        return {
            "os": platform.system(),
            "os_version": platform.version(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
        }

    @mcp.tool()
    def calculate(expression: str) -> str:
        """
        Evaluate a mathematical expression safely.
        Supports basic arithmetic: +, -, *, /, **, parentheses.
        """
        import ast
        import operator

        OPERATORS = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Pow: operator.pow,
            ast.USub: operator.neg,
            ast.UAdd: operator.pos,
        }

        def eval_node(node):
            if isinstance(node, ast.Num):
                return node.n
            elif isinstance(node, ast.BinOp):
                left = eval_node(node.left)
                right = eval_node(node.right)
                op = OPERATORS[type(node.op)]
                return op(left, right)
            elif isinstance(node, ast.UnaryOp):
                operand = eval_node(node.operand)
                op = OPERATORS[type(node.op)]
                return op(operand)
            elif isinstance(node, ast.Expression):
                return eval_node(node.body)
            else:
                raise ValueError(f"Unsupported expression: {node}")

        try:
            tree = ast.parse(expression, mode='eval')
            result = eval_node(tree)
            return str(result)
        except Exception as e:
            return f"Error evaluating expression: {e}"

    @mcp.tool()
    def run_command(command: str, timeout: int = 60) -> str:
        """
        Execute a shell command and return the output.
        Use this to run npm, npx, git, or any system commands.

        Args:
            command: The shell command to execute
            timeout: Maximum time to wait for completion (seconds)

        Returns:
            Command output or error message
        """
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = result.stdout + result.stderr
            return output.strip() if output else "Command executed successfully (no output)"
        except subprocess.TimeoutExpired:
            return f"Command timed out after {timeout} seconds"
        except Exception as e:
            return f"Error executing command: {str(e)}"

    @mcp.tool()
    def create_file(file_path: str, content: str = "") -> str:
        """
        Create a new file with optional content.

        Args:
            file_path: Path where the file should be created
            content: Optional content to write to the file

        Returns:
            Success or error message
        """
        try:
            from pathlib import Path
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
            return f"Successfully created: {file_path}"
        except Exception as e:
            return f"Error creating file: {str(e)}"

    @mcp.tool()
    def create_directory(dir_path: str) -> str:
        """
        Create a new directory (including parent directories if needed).

        Args:
            dir_path: Path where the directory should be created

        Returns:
            Success or error message
        """
        try:
            from pathlib import Path
            path = Path(dir_path)
            path.mkdir(parents=True, exist_ok=True)
            return f"Successfully created directory: {dir_path}"
        except Exception as e:
            return f"Error creating directory: {str(e)}"
