"""
Multi-agent collaboration examples and patterns.

This module demonstrates common multi-agent workflows where tasks
are handed off between specialists for comprehensive results.
"""

from typing import List, Dict, Any
from crewai import Agent, Task, Crew, Process

from groundwire.config import config
from groundwire.workflows.crewai_langgraph_workflow import (
    create_researcher_agent,
    create_coder_agent,
    create_writer_agent,
)


# ---------------------------------------------------------------------------
# Pre-built Collaboration Patterns
# ---------------------------------------------------------------------------

class CollaborationPatterns:
    """
    Pre-configured multi-agent collaboration patterns.

    Each pattern defines:
    - Which agents participate
    - The sequence of tasks
    - How outputs flow between agents
    """

    # Pattern 1: Research → Write (for reports, articles, documentation)
    @staticmethod
    def research_and_write(topic: str, format: str = "article") -> Crew:
        """
        Create a crew that researches a topic then writes about it.

        Flow: Researcher gathers info → Writer creates polished content
        """
        researcher = create_researcher_agent()
        writer = create_writer_agent()

        research_task = Task(
            description=f"""Research the topic: {topic}

Gather key information including:
- Main concepts and definitions
- Current state/latest developments
- Important facts, statistics, or examples
- Different perspectives if applicable

Provide structured notes that a writer can use.""",
            expected_output="Structured research notes with key findings",
            agent=researcher,
        )

        writing_task = Task(
            description=f"""Using the research notes, write a {format} about: {topic}

Requirements:
- Clear, engaging introduction
- Well-organized body sections
- Concrete examples where helpful
- Strong conclusion

Target audience: General educated readers.""",
            expected_output=f"A polished {format} ready for publication",
            agent=writer,
        )

        return Crew(
            agents=[researcher, writer],
            tasks=[research_task, writing_task],
            process=Process.sequential,
            verbose=True,
        )

    # Pattern 2: Plan → Code → Review (for software development)
    @staticmethod
    def plan_code_review(feature_request: str, language: str = "Python") -> Crew:
        """
        Create a crew that plans, implements, and reviews a feature.

        Flow: Coder plans approach → Coder implements → Coder reviews
        """
        coder = create_coder_agent()

        planning_task = Task(
            description=f"""Plan the implementation of: {feature_request}

Create a detailed plan including:
- Architecture/design approach
- Key components needed
- Potential challenges and solutions
- Testing strategy

Language: {language}""",
            expected_output="Detailed implementation plan",
            agent=coder,
        )

        coding_task = Task(
            description=f"""Implement the feature based on the plan.

Provide:
- Clean, well-commented code
- Example usage
- Brief explanation of key design decisions

Language: {language}""",
            expected_output="Working code implementation",
            agent=coder,
        )

        review_task = Task(
            description="""Review the implementation for:
- Code quality and best practices
- Potential bugs or edge cases
- Performance considerations
- Security concerns
- Suggestions for improvement""",
            expected_output="Code review with findings and recommendations",
            agent=coder,
        )

        return Crew(
            agents=[coder],
            tasks=[planning_task, coding_task, review_task],
            process=Process.sequential,
            verbose=True,
        )

    # Pattern 3: Research → Code → Document (for technical tutorials)
    @staticmethod
    def research_code_document(topic: str, language: str = "Python") -> Crew:
        """
        Create a crew that creates a complete technical tutorial.

        Flow: Researcher gathers info → Coder creates examples → Writer documents
        """
        researcher = create_researcher_agent()
        coder = create_coder_agent()
        writer = create_writer_agent()

        research_task = Task(
            description=f"""Research the topic: {topic}

Focus on:
- Key concepts a beginner needs to understand
- Common use cases and patterns
- Best practices and pitfalls to avoid
- Current state of the technology""",
            expected_output="Research notes for tutorial creation",
            agent=researcher,
        )

        coding_task = Task(
            description=f"""Create example code demonstrating: {topic}

Provide:
- Multiple examples from simple to advanced
- Clear comments explaining each part
- Example output where applicable

Language: {language}""",
            expected_output="Working example code for tutorial",
            agent=coder,
        )

        documentation_task = Task(
            description=f"""Write a beginner-friendly tutorial for: {topic}

Structure:
1. Introduction (what and why)
2. Prerequisites
3. Step-by-step examples with code
4. Common patterns and best practices
5. Next steps for learning

Use the research notes and code examples provided.""",
            expected_output="Complete, publication-ready tutorial",
            agent=writer,
        )

        return Crew(
            agents=[researcher, coder, writer],
            tasks=[research_task, coding_task, documentation_task],
            process=Process.sequential,
            verbose=True,
        )

    # Pattern 4: Analyze → Recommend (for code review/audits)
    @staticmethod
    def analyze_and_recommend(code: str, focus: str = "general") -> Crew:
        """
        Create a crew that analyzes code and provides recommendations.

        Flow: Coder analyzes → Coder recommends improvements
        """
        coder = create_coder_agent()

        analysis_task = Task(
            description=f"""Analyze this code:

```
{code[:2000]}  # Truncate for token efficiency
```

Focus area: {focus}

Identify:
- Code quality issues
- Potential bugs
- Performance concerns
- Security vulnerabilities
- Maintainability issues""",
            expected_output="Detailed code analysis",
            agent=coder,
        )

        recommendation_task = Task(
            description="""Based on the analysis, provide prioritized recommendations:

1. Critical issues (must fix)
2. Important improvements (should fix)
3. Nice-to-have enhancements (consider)

For each recommendation:
- Explain the issue
- Show the fix with code example
- Explain the benefit""",
            expected_output="Prioritized recommendations with code examples",
            agent=coder,
        )

        return Crew(
            agents=[coder],
            tasks=[analysis_task, recommendation_task],
            process=Process.sequential,
            verbose=True,
        )


# ---------------------------------------------------------------------------
# Example Usage Functions
# ---------------------------------------------------------------------------

async def run_research_and_write_example(topic: str = "Quantum Computing"):
    """Run the research-and-write pattern example."""
    crew = CollaborationPatterns.research_and_write(topic, format="explainer article")
    result = crew.kickoff()
    return str(result)


async def run_plan_code_review_example(feature: str = "A REST API endpoint for user authentication"):
    """Run the plan-code-review pattern example."""
    crew = CollaborationPatterns.plan_code_review(feature)
    result = crew.kickoff()
    return str(result)


async def run_tutorial_example(topic: str = "Async/Await in Python"):
    """Run the research-code-document tutorial pattern."""
    crew = CollaborationPatterns.research_code_document(topic)
    result = crew.kickoff()
    return str(result)


# ---------------------------------------------------------------------------
# MCP Integration
# ---------------------------------------------------------------------------

def register_collaboration_examples(mcp):
    """Register collaboration pattern tools with MCP."""

    @mcp.tool()
    def create_research_write_crew(topic: str, format: str = "article") -> str:
        """
        Create a crew that researches a topic and writes about it.
        Returns the crew execution result.

        Args:
            topic: What to research and write about
            format: Type of content (article, blog post, report, etc.)
        """
        crew = CollaborationPatterns.research_and_write(topic, format)
        result = crew.kickoff()
        return str(result)

    @mcp.tool()
    def create_tutorial_crew(topic: str, language: str = "Python") -> str:
        """
        Create a crew that builds a complete technical tutorial.
        Research → Code examples → Write documentation.

        Args:
            topic: What the tutorial is about
            language: Programming language for examples
        """
        crew = CollaborationPatterns.research_code_document(topic, language)
        result = crew.kickoff()
        return str(result)

    @mcp.tool()
    def create_code_review_crew(code: str, focus: str = "general") -> str:
        """
        Create a crew that analyzes code and provides recommendations.

        Args:
            code: The code to analyze
            focus: Specific area to focus on (security, performance, etc.)
        """
        # Truncate long code
        if len(code) > 3000:
            code = code[:3000] + "\n... [truncated]"

        crew = CollaborationPatterns.analyze_and_recommend(code, focus)
        result = crew.kickoff()
        return str(result)

    return CollaborationPatterns
