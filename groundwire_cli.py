"""Deprecated: use agent_with_tools.py (pre-cleanup VoxPrime entry)."""
import runpy
import sys

print("[INFO] groundwire_cli.py is deprecated. Starting agent_with_tools.py …", file=sys.stderr)
runpy.run_path("agent_with_tools.py", run_name="__main__")
