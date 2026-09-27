# Thinking display — ported from Kubernetes/agentic/thinking_display.py (example.py companion)

import re
from typing import List, Dict


class ThinkingDisplay:
    """Parse and show LLM thinking blocks from tagged responses."""

    def __init__(self):
        self.display_enabled = True
        self.thinking_prefix = "[LLM Thinking]"
        self.thinking_suffix = "[/LLM Thinking]"

    def parse_thinking_from_response(self, response: str) -> List[Dict]:
        thinking_blocks = []
        patterns = [
            r"<<thinking>>\s*(.*?)\s*\[/<<thinking>>]",
            r"\[\[thinking\]\]\s*(.*?)\s*\[\[\/thinking\]\]",
            r"<thinking>\s*(.*?)\s*</thinking>",
            r"\[THOUGHTS\]\s*(.*?)\s*\[/THOUGHTS\]",
        ]
        for pattern in patterns:
            for match in re.findall(pattern, response, re.DOTALL | re.IGNORECASE):
                clean_content = self._clean_thinking_content(match)
                thinking_blocks.append(
                    {
                        "content": clean_content.strip(),
                        "type": self._determine_thinking_type(clean_content),
                        "summary": self._extract_summary(clean_content),
                        "word_count": len(clean_content.split()),
                    }
                )
        return thinking_blocks

    def _clean_thinking_content(self, content: str) -> str:
        content = re.sub(r"\[TOOL\][\s\S]*?[/TOOL]", "", content, flags=re.IGNORECASE)
        content = re.sub(r"```(?:\w+)?\s*\n(?:.*?)\n```", "", content, flags=re.DOTALL)
        content = re.sub(r"[*_`#]", "", content)
        return " ".join(content.split())

    def _determine_thinking_type(self, content: str) -> str:
        content_lower = content.lower()
        if "summary" in content_lower or "done" in content_lower or "complete" in content_lower:
            return "summary"
        if "tool" in content_lower or "action" in content_lower:
            return "plan"
        return "thought"

    def _extract_summary(self, content: str) -> str:
        for pattern in [
            r"\[summary\](.*?)\[\/summary\]",
            r"SUMMARY:\s*(.+?)(?=\n\n|\n|$)",
            r"=== SUMMARY ===\s*(.+?)\s*===",
        ]:
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                return self._clean_thinking_content(match.group(1)).strip()
        return ""

    def display_thinking(self, thinking_blocks: List[Dict], full_response: str = "") -> None:
        if not self.display_enabled or not thinking_blocks:
            return
        print("\n" + "=" * 60)
        print(f"{self.thinking_prefix} ({len(thinking_blocks)} steps)")
        print("=" * 60)
        for i, block in enumerate(thinking_blocks, 1):
            print(f"\n--- Step {i} ({block['type']}): {block['word_count']} words ---")
            print(block["content"])
        print("=" * 60 + "\n")


thinking_display = ThinkingDisplay()
