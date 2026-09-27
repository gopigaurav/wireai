from voxprime.core.wholefile_parse import parse_wholefile_writes

text = """youtube_system_design.md

```markdown
# Hi
line
```
"""
assert len(parse_wholefile_writes(text)) == 1
assert "Hi" in parse_wholefile_writes(text)[0][1]
print("ok")
