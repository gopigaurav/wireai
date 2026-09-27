"""Discover project files to attach to the user message (Cursor-style, not hardcoded paths)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable, Optional

_SKIP_DIR_NAMES = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".next",
        "coverage",
        ".voxprime",
        "site-packages",
    }
)

_JS_APP_HINTS = frozenset(
    {"react", "react-dom", "react-scripts", "vite", "next", "vue", "@angular/core"}
)

_PATH_IN_TEXT_RE = re.compile(
    r"(?:@)?([^\s'\"`]+\.(?:js|jsx|ts|tsx|json|py|html|css|vue|svelte))"
    r"|(?:^|\s)([a-zA-Z][\w./-]*/[\w./-]+\.(?:js|jsx|ts|tsx|json))"
)

_FOLDER_IN_TEXT_RE = re.compile(
    r"\b(?:in|under|inside|for|within)\s+(?:the\s+)?([a-zA-Z][\w./-]*)\b",
    re.IGNORECASE,
)

_FIX_SCOPE_RE = re.compile(
    r"\b(?:fix|debug|repair|troubleshoot|solve|investigate)\s+(?:the\s+)?([a-zA-Z][\w./-]+)(?:\s+folder)?\b",
    re.IGNORECASE,
)

_NAMED_FOLDER_RE = re.compile(
    r"\b([a-zA-Z][\w./-]+)\s+folder\b",
    re.IGNORECASE,
)

_ANALYZE_SCOPE_RE = re.compile(
    r"\b(?:analy[sz]e|review|explain|summarize|understand|inspect|walk\s*through|overview\s+of)\s+(?:the\s+)?([a-zA-Z][\w./-]+)\b",
    re.IGNORECASE,
)

_SCOPE_STOPWORDS = frozenset(
    {
        "file",
        "files",
        "code",
        "codebase",
        "project",
        "repo",
        "workspace",
        "issue",
        "bug",
        "this",
        "that",
        "it",
        "them",
        "everything",
        "all",
        "whole",
    }
)

_FIX_STOPWORDS = _SCOPE_STOPWORDS | frozenset(
    {
        "folder",
        "directories",
        "directory",
        "issue",
        "bug",
        "error",
        "problem",
        "it",
        "this",
        "that",
    }
)

_MANIFEST_NAMES = (
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
)


def _norm(path: str) -> str:
    return os.path.normpath(os.path.abspath(path))


def _is_under(root: str, path: str) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def _resolve_named_directory(token: str, workspace_root: str) -> Optional[str]:
    raw = (token or "").strip().strip('"').strip("'").rstrip("/\\")
    if not raw or raw in (".", "..") or raw.lower() in _FIX_STOPWORDS:
        return None
    root = Path(workspace_root).resolve()
    for c in (raw, str(root / raw)):
        p = _norm(c)
        if os.path.isdir(p):
            return p
    return None


def resolve_fix_scope_directory(
    user_message: str, workspace_root: str
) -> Optional[str]:
    """
    Directory the user asked to fix (e.g. 'fix client folder' → client/).
    """
    for folder in folders_mentioned_in_message(user_message, workspace_root):
        return folder
    for pattern in (_FIX_SCOPE_RE, _NAMED_FOLDER_RE):
        for m in pattern.finditer(user_message):
            p = _resolve_named_directory(m.group(1), workspace_root)
            if p:
                return p
    return None


def discover_fix_attachments(
    scope_dir: str, workspace_root: str
) -> tuple[list[str], str]:
    """Seed files for fix/debug in a named folder (listing + manifest + entry)."""
    max_files = max(1, int(os.getenv("VOXPRIME_FIX_MAX_FILES", "3")))
    ordered: list[str] = []
    for manifest in _manifest_paths_under(scope_dir):
        ordered.append(manifest)
    entries = _entry_files_for_app(scope_dir)
    if entries:
        ordered.append(entries[0])

    seen: set[str] = set()
    final: list[str] = []
    for p in ordered:
        if p in seen or not os.path.isfile(p):
            continue
        seen.add(p)
        final.append(p)
        if len(final) >= max_files:
            break

    try:
        rel = os.path.relpath(scope_dir, workspace_root)
    except ValueError:
        rel = scope_dir
    return final, f"fix/debug scope `{rel}`"


def resolve_analysis_scope_directory(
    user_message: str, workspace_root: str
) -> Optional[str]:
    """
    Directory the user asked to analyze (e.g. 'analyze the client' → client/).
    Not used for vague 'analyze the codebase' (stopwords).
    """
    root = Path(workspace_root).resolve()
    for folder in folders_mentioned_in_message(user_message, str(root)):
        return folder
    for m in _ANALYZE_SCOPE_RE.finditer(user_message):
        token = (m.group(1) or "").strip().strip('"').strip("'")
        if not token or token.lower() in _SCOPE_STOPWORDS:
            continue
        for c in (token, str(root / token)):
            p = _norm(c)
            if os.path.isdir(p):
                return p
            if os.path.isfile(p):
                return _norm(str(Path(p).parent))
    return None


def discover_analysis_attachments(
    scope_dir: str, workspace_root: str
) -> tuple[list[str], str]:
    """
    Minimal in-chat files for scoped analysis (Cursor-style): listing + manifest + one entry.
    Additional files: model uses read_file under scope_dir.
    """
    max_files = max(1, int(os.getenv("VOXPRIME_ANALYSIS_MAX_FILES", "2")))
    ordered: list[str] = []
    scope = Path(scope_dir)
    for name in ("README.md", "README", "readme.md"):
        p = scope / name
        if p.is_file():
            ordered.append(_norm(str(p)))
    for manifest in _manifest_paths_under(scope_dir):
        ordered.append(manifest)
    entries = _entry_files_for_app(scope_dir)
    if entries:
        ordered.append(entries[0])

    seen: set[str] = set()
    final: list[str] = []
    for p in ordered:
        if p in seen or not os.path.isfile(p):
            continue
        seen.add(p)
        final.append(p)
        if len(final) >= max_files:
            break

    try:
        rel = os.path.relpath(scope_dir, workspace_root)
    except ValueError:
        rel = scope_dir
    return final, f"scoped analysis of `{rel}`"


def list_dir_summary(directory: str, limit: int = 60) -> str:
    return _list_dir_summary(directory, limit=limit)


def folders_mentioned_in_message(text: str, workspace_root: str) -> list[str]:
    """Resolve directory paths from phrases like 'in client', 'fix client folder'."""
    root = Path(workspace_root).resolve()
    found: list[str] = []

    def _add_token(raw: str) -> None:
        raw = (raw or "").strip().strip('"').strip("'").rstrip("/\\")
        if not raw or raw in (".", "..") or raw.lower() in _FIX_STOPWORDS:
            return
        for c in (raw, str(root / raw)):
            p = _norm(c)
            if os.path.isdir(p) and p not in found:
                found.append(p)
                break

    for m in _FOLDER_IN_TEXT_RE.finditer(text):
        _add_token(m.group(1) or "")
    for pattern in (_FIX_SCOPE_RE, _NAMED_FOLDER_RE):
        for m in pattern.finditer(text):
            _add_token(m.group(1) or "")
    return found


def paths_mentioned_in_message(text: str, workspace_root: str) -> list[str]:
    """Resolve file paths the user named in plain text."""
    root = Path(workspace_root).resolve()
    found: list[str] = []
    for m in _PATH_IN_TEXT_RE.finditer(text):
        raw = (m.group(1) or m.group(2) or "").strip().strip('"').strip("'")
        if not raw or raw.startswith("http"):
            continue
        candidates = [raw]
        if not os.path.isabs(raw):
            candidates.append(str(root / raw))
        for c in candidates:
            p = _norm(c)
            if os.path.isfile(p) and p not in found:
                found.append(p)
    return found


def _walk_package_json_dirs(workspace_root: str, max_depth: int = 5) -> list[str]:
    roots: list[str] = []
    root_path = Path(workspace_root).resolve()
    for dirpath, dirnames, filenames in os.walk(root_path, topdown=True):
        depth = len(Path(dirpath).relative_to(root_path).parts)
        if depth > max_depth:
            dirnames.clear()
            continue
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES and not d.startswith(".")]
        if "package.json" in filenames:
            roots.append(_norm(dirpath))
    return roots


def _user_mentions_dir_name(user_lower: str, dir_name: str) -> int:
    """Boost when the user named this folder (e.g. 'in client' → client/)."""
    name = dir_name.lower()
    if len(name) < 2:
        return 0
    if re.search(rf"\b{re.escape(name)}\b", user_lower):
        return 25
    return 0


def _package_json_score(pkg_path: str, user_lower: str) -> int:
    score = 0
    app_root = Path(pkg_path).parent
    score += _user_mentions_dir_name(user_lower, app_root.name)
    try:
        data = json.loads(Path(pkg_path).read_text(encoding="utf-8"))
    except Exception:
        return score
    deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    if deps:
        score += 3
    if deps.keys() & _JS_APP_HINTS:
        score += 10
    scripts = data.get("scripts") or {}
    if scripts:
        score += 5
    return score


def _manifest_paths_under(directory: str) -> list[str]:
    base = Path(directory)
    out: list[str] = []
    for name in _MANIFEST_NAMES:
        p = base / name
        if p.is_file():
            out.append(_norm(str(p)))
    return out


def _list_dir_summary(directory: str, limit: int = 60) -> str:
    try:
        names = sorted(os.listdir(directory))
    except OSError as e:
        return f"(could not list: {e})"
    head = names[:limit]
    lines = "\n".join(f"  {n}" for n in head)
    if len(names) > limit:
        lines += f"\n  … ({len(names)} entries total)"
    return lines


def _entry_files_for_app(app_root: str) -> list[str]:
    """Guess entry/source files from package.json and common layouts."""
    app = Path(app_root)
    pkg_file = app / "package.json"
    paths: list[str] = []
    rel_guesses = (
        "src/index.tsx",
        "src/index.jsx",
        "src/index.js",
        "src/main.tsx",
        "src/main.jsx",
        "src/main.js",
        "src/App.tsx",
        "src/App.jsx",
        "src/App.js",
        "index.html",
    )
    if pkg_file.is_file():
        try:
            data = json.loads(pkg_file.read_text(encoding="utf-8"))
            main = data.get("main") or data.get("module")
            if isinstance(main, str) and main.strip():
                rel_guesses = (main.strip(),) + rel_guesses
        except Exception:
            pass
    for rel in rel_guesses:
        p = app / rel
        if p.is_file():
            paths.append(_norm(str(p)))
    return paths


def _app_root_for_file(file_path: str, package_roots: Iterable[str]) -> Optional[str]:
    file_path = _norm(file_path)
    best: Optional[str] = None
    best_len = -1
    for root in package_roots:
        if _is_under(root, file_path) and len(root) > best_len:
            best = root
            best_len = len(root)
    return best


def discover_investigation_files(
    *,
    workspace_root: str,
    user_message: str,
    active_file: Optional[str] = None,
    max_apps: int = 2,
    max_files: int = 8,
) -> tuple[list[str], str]:
    """
    Return (absolute file paths, short reason string) for attaching to the prompt.
    Dynamic: walks the workspace, scores package.json projects, adds entries + mentions.
    """
    root = _norm(workspace_root or os.getcwd())
    user_lower = user_message.lower()
    ordered: list[str] = []
    reasons: list[str] = []

    fix_scope = resolve_fix_scope_directory(user_message, root)

    mentioned = paths_mentioned_in_message(user_message, root)
    if mentioned:
        ordered.extend(mentioned)
        reasons.append(f"{len(mentioned)} path(s) from your message")

    for folder in folders_mentioned_in_message(user_message, root):
        for manifest in _manifest_paths_under(folder):
            ordered.append(manifest)
        entries = _entry_files_for_app(folder)
        if entries:
            ordered.append(entries[0])
        reasons.append(f"folder `{os.path.relpath(folder, root)}` from your message")

    if fix_scope:
        for manifest in _manifest_paths_under(fix_scope):
            if manifest not in ordered:
                ordered.insert(0, manifest)
        entries = _entry_files_for_app(fix_scope)
        if entries and entries[0] not in ordered:
            ordered.insert(1 if ordered else 0, entries[0])
        reasons.append(f"fix scope `{os.path.relpath(fix_scope, root)}`")

    pkg_roots = _walk_package_json_dirs(root)
    ranked = sorted(
        pkg_roots,
        key=lambda d: _package_json_score(str(Path(d) / "package.json"), user_lower),
        reverse=True,
    )
    ranked = [
        r
        for r in ranked
        if _package_json_score(str(Path(r) / "package.json"), user_lower) > 0
    ]
    if not ranked and pkg_roots:
        # Prefer apps whose directory name appears in the user message
        by_name = [
            r
            for r in pkg_roots
            if _user_mentions_dir_name(user_lower, Path(r).name) > 0
        ]
        ranked = by_name[:max_apps] if by_name else pkg_roots[:max_apps]

    if active_file and os.path.isfile(active_file):
        active_norm = _norm(active_file)
        skip_active = fix_scope and not _is_under(fix_scope, active_norm)
        if not skip_active:
            app = _app_root_for_file(active_file, pkg_roots)
            if app and app not in ranked:
                ranked.insert(0, app)
            elif active_norm not in ordered:
                ordered.append(active_norm)
                reasons.append("active editor file")

    for app_root in ranked[:max_apps]:
        if fix_scope and not _is_under(fix_scope, app_root):
            continue
        pkg = str(Path(app_root) / "package.json")
        if os.path.isfile(pkg):
            ordered.append(pkg)
        entries = _entry_files_for_app(app_root)
        if entries:
            ordered.append(entries[0])
    if ranked:
        reasons.append(f"{min(len(ranked), max_apps)} JS/TS app root(s) under workspace")

    # De-dupe, preserve order, cap count
    seen: set[str] = set()
    final: list[str] = []
    for p in ordered:
        if p in seen or not os.path.isfile(p):
            continue
        if fix_scope and not _is_under(fix_scope, p):
            continue
        seen.add(p)
        final.append(p)
        if len(final) >= max_files:
            break

    reason = "; ".join(reasons) if reasons else "workspace scan"
    return final, reason
