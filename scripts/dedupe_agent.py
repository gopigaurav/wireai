from pathlib import Path

p = Path(__file__).resolve().parents[1] / "agent_with_tools.py"
text = p.read_text(encoding="utf-8")
vision = (
    "            if VISION_MODEL:\n"
    '                print(f"[OK] Vision model (images/screenshots): {VISION_MODEL}")\n'
    "            elif not model_supports_vision(LLM_MODEL):\n"
    "                print(\n"
    '                    "[Tip] For screenshots, set VOXPRIME_VISION_MODEL=qwen2.5vl:latest "\n'
    '                    "(ollama pull qwen2.5vl) or use a vision-capable LLM_MODEL"\n'
    "                )\n"
)
while text.count(vision) > 1:
    text = text.replace(vision, "", 1)
p.write_text(text, encoding="utf-8")
print("vision blocks:", text.count(vision))
