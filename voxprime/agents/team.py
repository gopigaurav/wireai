"""
CrewAI agent team — multiple specialized agents working together.
"""

from crewai import Agent, Task, Crew, Process
from langchain_ollama import ChatOllama
from groundwire.config import config


def get_llm():
    """Get the Qwen 3.5 LLM instance."""
    return ChatOllama(
        model=config.LLM_MODEL,
        base_url=config.LLM_BASE_URL,
        temperature=float(config.TEMPERATURE),
    )


def create_researcher_agent(verbose=False):
    """Create a research specialist agent."""
    return Agent(
        role="Senior Research Analyst",
        goal="Find, verify, and synthesize information from multiple sources",
        backstory=(
            "You are an expert researcher with years of experience analyzing "
            "complex topics and distilling them into clear, actionable insights. "
            "You excel at finding patterns and connecting dots across domains."
        ),
        verbose=verbose,
        allow_delegation=False,
        llm=get_llm(),
    )


def create_coder_agent(verbose=False):
    """Create a coding specialist agent."""
    return Agent(
        role="Senior Software Engineer",
        goal="Write clean, efficient, and well-documented code",
        backstory=(
            "You are a seasoned software engineer with expertise in multiple "
            "programming languages and architectures. You write code that is "
            "not just functional, but maintainable and elegant."
        ),
        verbose=verbose,
        allow_delegation=False,
        llm=get_llm(),
    )


def create_writer_agent(verbose=False):
    """Create a content specialist agent."""
    return Agent(
        role="Content Strategist",
        goal="Create clear, engaging, and purposeful written content",
        backstory=(
            "You are a skilled communicator who can adapt your writing style "
            "to any audience. You excel at explaining complex topics simply."
        ),
        verbose=verbose,
        allow_delegation=False,
        llm=get_llm(),
    )


def create_agent_team(mcp=None):
    """
    Create a team of specialized agents that can collaborate on tasks.

    Returns a dict with:
    - 'crew': The CrewAI Crew instance
    - 'agents': List of agents
    - 'run': Function to execute a task with the team
    """

    # Create agents
    researcher = create_researcher_agent()
    coder = create_coder_agent()
    writer = create_writer_agent()

    def run_task(description: str, expected_output: str = "") -> str:
        """
        Run a task with the agent team.

        Args:
            description: What needs to be done
            expected_output: Description of the expected deliverable

        Returns:
            The team's output
        """
        task = Task(
            description=description,
            expected_output=expected_output or "A complete, well-formatted response",
            agent=researcher,  # Default assignee; can be changed based on task type
        )

        crew = Crew(
            agents=[researcher, coder, writer],
            tasks=[task],
            process=Process.sequential,
            verbose=True,
        )

        result = crew.kickoff()
        return str(result)

    # Register as MCP tool if mcp is provided
    if mcp:

        @mcp.tool()
        def team_collaborate(task_description: str, expected_output: str = "") -> str:
            """
            Delegate a complex task to the agent team.
            The team will collaborate to produce a comprehensive response.

            Args:
                task_description: Detailed description of what needs to be done
                expected_output: Optional description of the expected format/output

            Returns:
                The team's completed work
            """
            return run_task(task_description, expected_output)

    return {
        "crew": None,  # Created on-demand per task
        "agents": [researcher, coder, writer],
        "run": run_task,
    }
