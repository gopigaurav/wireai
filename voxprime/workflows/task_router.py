"""
Intelligent Task Router for multi-agent system.
Routes tasks to specialists based on intent classification.
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import re


class AgentType(Enum):
    """Available specialist agents."""
    RESEARCHER = "RESEARCHER"
    CODER = "CODER"
    WRITER = "WRITER"
    GENERAL = "GENERAL"


@dataclass
class RoutingDecision:
    """Result of task routing."""
    agent: AgentType
    confidence: float
    reasoning: str
    keywords: List[str]


class TaskRouter:
    """
    Intelligent task router using keyword matching and pattern recognition.

    For production, this would use an LLM for intent classification.
    This implementation provides fast, deterministic routing.
    """

    # Keyword patterns for each agent type
    RESEARCHER_KEYWORDS = [
        "research", "analyze", "find", "discover", "investigate",
        "what is", "explain", "tell me about", "learn", "study",
        "facts", "evidence", "data", "statistics", "sources",
        "compare", "versus", "difference between", "similar",
        "history", "background", "origin", "evolution",
        "current events", "news", "trending", "latest",
        "scientific", "academic", "paper", "study", "journal",
        "who", "when", "where", "why", "how does", "what does",
    ]

    CODER_KEYWORDS = [
        "code", "program", "function", "method", "class", "module",
        "debug", "error", "bug", "fix", "issue", "exception",
        "implement", "write code", "script", "automation",
        "api", "endpoint", "request", "response", "http",
        "database", "sql", "query", "table", "schema",
        "algorithm", "data structure", "complexity", "optimize",
        "refactor", "clean code", "best practice", "design pattern",
        "test", "unit test", "integration test", "pytest",
        "git", "version control", "commit", "branch", "merge",
        "docker", "container", "kubernetes", "deploy", "ci/cd",
        "python", "javascript", "typescript", "java", "go", "rust",
        "react", "vue", "angular", "node", "backend", "frontend",
        "file", "read", "write", "parse", "json", "xml", "yaml",
        "regex", "pattern", "match", "extract",
    ]

    WRITER_KEYWORDS = [
        "write", "draft", "compose", "create content", "article",
        "email", "message", "communication", "letter", "memo",
        "documentation", "doc", "readme", "guide", "tutorial",
        "summarize", "summary", "brief", "overview", "abstract",
        "edit", "revise", "improve", "polish", "proofread",
        "tone", "style", "voice", "audience", "reader",
        "blog", "post", "social media", "caption", "description",
        "presentation", "slide", "speech", "talk", "pitch",
        "creative", "story", "narrative", "plot", "character",
        "explain simply", "eli5", "like i'm five", "beginner",
    ]

    def __init__(self):
        self.route_history: List[RoutingDecision] = []

    def route(self, task_description: str) -> RoutingDecision:
        """
        Route a task to the appropriate specialist.

        Args:
            task_description: The user's request

        Returns:
            RoutingDecision with agent, confidence, and reasoning
        """
        text_lower = task_description.lower()

        # Score each agent type
        scores = {
            AgentType.RESEARCHER: self._score_for_agent(text_lower, self.RESEARCHER_KEYWORDS),
            AgentType.CODER: self._score_for_agent(text_lower, self.CODER_KEYWORDS),
            AgentType.WRITER: self._score_for_agent(text_lower, self.WRITER_KEYWORDS),
        }
        print(scores)

        # Find the best match
        best_agent = max(scores, key=lambda a: scores[a]["score"])
        best_score = scores[best_agent]

        # Determine confidence
        confidence = self._calculate_confidence(best_score["score"], scores)

        # Create decision
        decision = RoutingDecision(
            agent=best_agent,
            confidence=confidence,
            reasoning=best_score["reasoning"],
            keywords=best_score["matched_keywords"],
        )

        self.route_history.append(decision)
        return decision

    def _score_for_agent(self, text: str, keywords: List[str]) -> Dict[str, Any]:
        """Score how well a task matches an agent type."""
        matched = []
        score = 0.0

        for keyword in keywords:
            if keyword in text:
                matched.append(keyword)
                # Weight longer phrases higher (more specific)
                word_count = len(keyword.split())
                score += word_count * 0.5

        # Bonus for multiple matches
        if len(matched) > 1:
            score += len(matched) * 0.3

        # Bonus for matches near the beginning (usually more important)
        for kw in matched:
            pos = text.find(kw)
            if pos < 50:
                score += 0.5

        reasoning = self._generate_reasoning(matched, score)

        return {
            "score": score,
            "matched_keywords": matched,
            "reasoning": reasoning,
        }

    def _generate_reasoning(self, matched_keywords: List[str], score: float) -> str:
        """Generate human-readable reasoning for the routing decision."""
        if not matched_keywords:
            return "No strong keywords matched; default routing."

        if len(matched_keywords) <= 2:
            return f"Matched keywords: {', '.join(matched_keywords)}"

        return f"Strong match with {len(matched_keywords)} keywords including: {', '.join(matched_keywords[:5])}"

    def _calculate_confidence(self, best_score: float, all_scores: Dict[AgentType, Dict]) -> float:
        """Calculate confidence score (0.0 to 1.0)."""
        if best_score == 0:
            return 0.3  # Low confidence default

        # Get second-best score
        sorted_scores = sorted(all_scores.values(), key=lambda x: x["score"], reverse=True)
        second_best = sorted_scores[1]["score"] if len(sorted_scores) > 1 else 0

        # Confidence based on margin over second place
        margin = best_score - second_best
        if margin > 2:
            return 0.9
        elif margin > 1:
            return 0.7
        elif margin > 0.5:
            return 0.6
        else:
            return 0.5  # Close call

    def get_routing_stats(self) -> Dict[str, Any]:
        """Get statistics about routing decisions."""
        if not self.route_history:
            return {"total_routes": 0}

        agent_counts = {}
        for decision in self.route_history:
            agent_name = decision.agent.value
            agent_counts[agent_name] = agent_counts.get(agent_name, 0) + 1

        avg_confidence = sum(d.confidence for d in self.route_history) / len(self.route_history)

        return {
            "total_routes": len(self.route_history),
            "agent_distribution": agent_counts,
            "average_confidence": round(avg_confidence, 2),
        }


# ---------------------------------------------------------------------------
# LLM-Based Router (Alternative)
# ---------------------------------------------------------------------------

class LLMTaskRouter:
    """
    LLM-based task router for more accurate intent classification.
    Uses Qwen 3.5 via Ollama.
    """

    def __init__(self, model: str = None, base_url: str = None):
        from groundwire.config import config

        self.model = model or config.LLM_MODEL
        self.base_url = base_url or config.LLM_BASE_URL
        self.client = None
        self._init_client()

    def _init_client(self):
        """Initialize Ollama client."""
        try:
            import ollama
            self.client = ollama.Client(host=self.base_url)
        except Exception as e:
            print(f"Warning: LLM router unavailable - {e}")
            self.client = None

    def route(self, task_description: str) -> RoutingDecision:
        """Route using LLM-based intent classification."""
        if self.client is None:
            # Fallback to keyword router
            fallback = TaskRouter()
            return fallback.route(task_description)

        prompt = f"""Analyze this task and route it to the best specialist:

Task: "{task_description}"

Available specialists:
- RESEARCHER: Information gathering, analysis, fact-checking, knowledge synthesis, explaining concepts
- CODER: Writing code, debugging, code review, technical implementations, automation
- WRITER: Content creation, documentation, communications, summarization, editing

Respond in this exact JSON format:
{{
    "agent": "AGENT_NAME",
    "confidence": 0.0-1.0,
    "reasoning": "Brief explanation"
}}"""

        try:
            response = self.client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                format={"type": "json"},
            )

            import json
            result = json.loads(response["message"]["content"])

            agent = AgentType[result.get("agent", "GENERAL")]

            return RoutingDecision(
                agent=agent,
                confidence=float(result.get("confidence", 0.5)),
                reasoning=result.get("reasoning", ""),
                keywords=[],
            )

        except Exception as e:
            # Fallback to keyword router
            fallback = TaskRouter()
            return fallback.route(task_description)


# ---------------------------------------------------------------------------
# MCP Integration
# ---------------------------------------------------------------------------

def register_task_router(mcp):
    """Register task router as MCP tools."""

    router = TaskRouter()

    @mcp.tool()
    def route_task(task_description: str) -> str:
        """
        Analyze a task and determine which specialist should handle it.
        Returns the routing decision with reasoning.
        """
        decision = router.route(task_description)

        return (
            f"Routed to: {decision.agent.value}\n"
            f"Confidence: {decision.confidence:.0%}\n"
            f"Reasoning: {decision.reasoning}\n"
            f"Keywords: {', '.join(decision.keywords) if decision.keywords else 'N/A'}"
        )

    @mcp.tool()
    def get_routing_stats() -> dict:
        """Get statistics about task routing decisions."""
        return router.get_routing_stats()

    return router
