"""Generation / continuation policy (reflection loop, not open-ended concat)."""

from __future__ import annotations

import os

# Max follow-up LLM calls after the first reply for one user message (Aider-style cap).
DEFAULT_MAX_REFLECTIONS = int(os.getenv("VOXPRIME_MAX_REFLECTIONS", "2"))

REFLECTION_TRUNCATED_TOOL = """Your previous reply was a tool JSON payload that was cut off or invalid.
Nothing was saved on disk.

Option A — valid JSON only (one tool):
{"tools": [{"name": "edit_file", "args": {"file_path": "path/to/file", "content": "..."}}]}

Use \\n for newlines inside "content". Keep content under 3500 characters.

Option B — whole-file format (often easier for .jsx / package.json):
client/src/App.jsx
```jsx
// full file
```

Use the same path you intended before."""

REFLECTION_TRUNCATED_PROSE = """Your previous reply was cut off mid-output.

Continue exactly where you stopped. Do not repeat earlier sections.
Do not claim files were created unless you use create_file or the filename+markdown fence format."""

REFLECTION_WHOLEFILE_HINT = """If JSON is fragile, use whole-file format (saved automatically):

client/package.json
```json
{ ... full file ... }
```

Or for source files: path/to/file.jsx then a fenced code block with the full file."""

TOKEN_LIMIT_USER_HINT = """Output hit the model token limit.

Next reply: either a shorter create_file (under 4000 chars in content) OR use:

filename.md
```markdown
...
```"""
