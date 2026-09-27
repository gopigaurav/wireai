"""
Code review tools — analyze code using code-review-graph for token-efficient review.
"""

from pathlib import Path


def register(mcp):

    @mcp.tool()
    def review_code(file_path: str) -> str:
        """
        Review a code file for issues, improvements, and best practices.
        Uses code-review-graph for efficient token usage.
        Returns a structured review with findings.
        """
        try:
            from code_review_graph import analyze_file

            path = Path(file_path).expanduser().resolve()
            if not path.exists():
                return f"Error: File not found: {file_path}"

            analysis = analyze_file(str(path))

            # Format the analysis results
            output = []
            output.append("### Code Review Results\n")

            if analysis.get("issues"):
                output.append("**Issues Found:**")
                for issue in analysis["issues"]:
                    output.append(f"- Line {issue.get('line', '?')}: {issue.get('message', 'Unknown issue')}")
                output.append("")

            if analysis.get("suggestions"):
                output.append("**Suggestions:**")
                for suggestion in analysis["suggestions"]:
                    output.append(f"- {suggestion}")
                output.append("")

            if analysis.get("metrics"):
                output.append("**Code Metrics:**")
                metrics = analysis["metrics"]
                output.append(f"- Lines: {metrics.get('lines', 'N/A')}")
                output.append(f"- Complexity: {metrics.get('complexity', 'N/A')}")
                output.append("")

            if not output[1:]:
                output.append("No significant issues found. Code looks clean!")

            return "\n".join(output)

        except ImportError:
            return "code-review-graph not installed. Install with: pip install code-review-graph"
        except Exception as e:
            return f"Error reviewing code: {e}"

    @mcp.tool()
    def review_code_diff(diff: str) -> str:
        """
        Review a code diff for issues and improvements.
        Returns a structured review of the changes.
        """
        try:
            from code_review_graph import analyze_diff

            analysis = analyze_diff(diff)

            output = ["### Code Diff Review\n"]

            if analysis.get("issues"):
                output.append("**Issues in Changes:**")
                for issue in analysis["issues"]:
                    output.append(f"- {issue}")
                output.append("")

            if analysis.get("positive"):
                output.append("**Good Changes:**")
                for item in analysis["positive"]:
                    output.append(f"+ {item}")
                output.append("")

            if not output[1:]:
                output.append("Changes look good!")

            return "\n".join(output)

        except ImportError:
            return "code-review-graph not installed."
        except Exception as e:
            return f"Error reviewing diff: {e}"

    @mcp.tool()
    def get_code_stats(file_path: str) -> dict:
        """
        Get code statistics for a file.
        Returns line count, function count, class count, and complexity.
        """
        try:
            from code_review_graph import get_file_stats

            path = Path(file_path).expanduser().resolve()
            if not path.exists():
                return {"error": f"File not found: {file_path}"}

            stats = get_file_stats(str(path))
            return stats

        except ImportError:
            return {"error": "code-review-graph not installed"}
        except Exception as e:
            return {"error": str(e)}
