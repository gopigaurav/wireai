from voxprime.core.tool_parse import extract_tool_calls

s = (
    '{"tools": [{"name": "create_file", "args": {"file_path": "a.md", '
    '"content": "# Hi\\n\\nline2", "encoding": "utf-8"}}]}'
)
c = extract_tool_calls(s)
assert c[0][0] == "create_file"
assert "encoding" not in c[0][1]
assert "line2" in c[0][1]["content"]
print("ok", c)
