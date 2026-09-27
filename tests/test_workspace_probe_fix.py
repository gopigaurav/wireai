import os

from voxprime.core.workspace_probe import (
    discover_investigation_files,
    folders_mentioned_in_message,
    resolve_fix_scope_directory,
)


def test_fix_client_folder_scope():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    msg = "fix client folder"
    folders = folders_mentioned_in_message(msg, root)
    assert folders, "expected client folder from message"
    assert any(f.endswith("client") or os.path.basename(f) == "client" for f in folders)
    scope = resolve_fix_scope_directory(msg, root)
    assert scope and os.path.basename(scope) == "client"


def test_fix_scope_excludes_unrelated_active_file():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    agent = os.path.join(root, "agent_with_tools.py")
    paths, reason = discover_investigation_files(
        workspace_root=root,
        user_message="fix client folder",
        active_file=agent,
    )
    assert paths
    assert not any(p.endswith("agent_with_tools.py") for p in paths)
    assert any("client" in p.replace("\\", "/") for p in paths)
