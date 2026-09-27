"""
Integrated LangGraph + CrewAI workflow.
Combines LangGraph's state management with CrewAI's specialized agents.

This creates a hierarchical agent system where:
- LangGraph orchestrates the overall workflow
- CrewAI handles specialized task execution with role-based agents
"""

from typing import Annotated, TypedDict, List, Any, Optional
from enum import Enum

from langchain_ollama import ChatOllama
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from crewai import Agent, Task, Crew, Process

from groundwire.config import config


# ---------------------------------------------------------------------------
# Agent State
# ---------------------------------------------------------------------------

class WorkflowState(TypedDict):
    """State for the integrated workflow."""
    messages: Annotated[List[BaseMessage], lambda x, y: x + y]
    current_agent: str
    task_description: str
    task_output: str
    context: dict
    needs_review: bool


# ---------------------------------------------------------------------------
# System Prompts
# ---------------------------------------------------------------------------

ORCHESTRATOR_PROMPT = """You are the Orchestrator for Groundwire's multi-agent system.

Your role:
1. Analyze incoming requests
2. Determine which specialized agent should handle each task
3. Route tasks appropriately
4. Synthesize final responses

Available specialists:
- RESEARCHER: For information gathering, analysis, fact-checking, synthesizing knowledge
- CODER: For writing code, debugging, code review, technical implementations
- WRITER: For content creation, documentation, explanations, communications

Respond with just the agent name (RESEARCHER, CODER, or WRITER) and a brief routing instruction."""

AGENT_SYSTEM_PROMPTS = {
    "RESEARCHER": """You are a Senior Research Analyst on the Groundwire team.

Your expertise:
- Finding and verifying information from multiple sources
- Analyzing complex topics and identifying patterns
- Synthesizing research into clear, actionable insights

When you receive a task:
1. Break it down into research steps
2. Gather relevant information
3. Verify facts when possible
4. Present findings in a structured, easy-to-understand format

Be thorough but concise. Cite sources when applicable.""",

    "CODER": """You are a Senior Staff Software Engineer on the Groundwire team.

Your expertise:
- Writing clean, efficient, well-documented code
- Debugging and troubleshooting technical issues
- Code review and best practices
- System design and architecture

When you receive a task:
1. Understand the requirements clearly
2. Plan your approach before coding
3. Write production-quality code with comments
4. Test mentally and explain edge cases

Use best practices. Explain your reasoning when helpful.""",

    "WRITER": """You are a Content Strategist on the Groundwire team.

Your expertise:
- Creating clear, engaging written content
- Adapting tone to audience and purpose
- Explaining complex topics simply
- Documentation and communication

When you receive a task:
1. Identify the audience and purpose
2. Structure content logically
3. Use clear, concise language
4. Ensure the output is polished and professional

Make complex ideas accessible without losing accuracy.""",
}


# ---------------------------------------------------------------------------
# CrewAI Agents
# ---------------------------------------------------------------------------

def get_llm():
    """Get the Qwen 3.5 LLM instance."""
    return {        
        "llm_type": "openai",
        "model": config.LLM_MODEL,  # e.g. "qwen3.5:latest"
        "api_base": config.LLM_BASE_URL,
        "api_key": "dummy",
        "temperature": float(config.TEMPERATURE),
        }


def create_researcher_agent():
    """Create the researcher specialist."""
    return Agent(
        role="Senior Research Analyst",
        goal="Find, verify, and synthesize information from multiple sources",
        backstory=(
            "You are an expert researcher with years of experience analyzing "
            "complex topics and distilling them into clear, actionable insights."
        ),
        verbose=True,
        allow_delegation=False,
        llm=get_llm(),
    )


def create_coder_agent():
    """Create the coder specialist."""
    return Agent(
        role="Senior Software Engineer",
        goal="Write clean, efficient, and well-documented code",
        backstory=(
            "You are a seasoned software engineer with expertise in multiple "
            "programming languages and architectures."
        ),
        verbose=True,
        allow_delegation=False,
        llm=get_llm(),
    )


def create_writer_agent():
    """Create the writer specialist."""
    return Agent(
        role="Content Strategist",
        goal="Create clear, engaging, and purposeful written content",
        backstory=(
            "You are a skilled communicator who can adapt your writing style "
            "to any audience and purpose."
        ),
        verbose=True,
        allow_delegation=False,
        llm=get_llm(),
    )


# ---------------------------------------------------------------------------
# Workflow Nodes
# ---------------------------------------------------------------------------

def route_to_agent(state: WorkflowState) -> dict:
    """
    Analyze the request and route to the appropriate specialist agent.
    Uses the orchestrator LLM to make routing decisions.
    """
    messages = state["messages"]
    last_message = messages[-1] if messages else None

    if not isinstance(last_message, HumanMessage):
        return {"current_agent": "WRITER", "needs_review": False}

    user_input = last_message.content

    # Use LLM to route
    orchestrator_llm = ChatOllama(
        model=config.LLM_MODEL,
        base_url=config.LLM_BASE_URL,
        temperature=0.1,  # Low temp for consistent routing
    )

    routing_prompt = f"""Analyze this request and route to the best specialist:

Request: "{user_input}"

Available specialists:
- RESEARCHER: Information gathering, analysis, fact-checking, knowledge synthesis
- CODER: Writing code, debugging, code review, technical implementations
- WRITER: Content creation, documentation, explanations, communications

Respond with ONLY the agent name (RESEARCHER, CODER, or WRITER)."""

    try:
        response = orchestrator_llm.invoke([HumanMessage(content=routing_prompt)])
        agent_name = response.content.strip().upper()

        # Default to WRITER if routing fails
        if agent_name not in ["RESEARCHER", "CODER", "WRITER"]:
            agent_name = "WRITER"

        return {
            "current_agent": agent_name,
            "task_description": user_input,
            "needs_review": False,
        }

    except Exception as e:
        # Fallback to WRITER on error
        return {"current_agent": "WRITER", "task_description": user_input, "needs_review": False}


def execute_specialist_task(state: WorkflowState) -> dict:
    """
    Execute the task using the appropriate CrewAI agent.
    """
    current_agent = state.get("current_agent", "WRITER")
    task_description = state.get("task_description", "")

    # Create the appropriate agent
    agents = {
        "RESEARCHER": create_researcher_agent(),
        "CODER": create_coder_agent(),
        "WRITER": create_writer_agent(),
    }

    specialist = agents.get(current_agent, agents["WRITER"])

    # Create and execute task
    task = Task(
        description=task_description,
        expected_output="A complete, well-formatted response that fully addresses the request",
        agent=specialist,
    )

    crew = Crew(
        agents=[specialist],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
    )

    try:
        result = crew.kickoff()
        return {
            "task_output": str(result),
            "needs_review": False,
        }
    except Exception as e:
        return {
            "task_output": f"[Error executing task: {str(e)}]",
            "needs_review": True,
        }


def generate_response(state: WorkflowState) -> dict:
    """
    Generate the final response message.
    """
    task_output = state.get("task_output", "")
    current_agent = state.get("current_agent", "WRITER")

    # Create response message
    response_content = task_output if task_output else "I was unable to complete the task."

    return {
        "messages": [AIMessage(content=response_content)],
    }


def should_review(state: WorkflowState) -> str:
    """Determine if the output needs review."""
    if state.get("needs_review", False):
        return "review"
    return "end"


# ---------------------------------------------------------------------------
# Workflow Builder
# ---------------------------------------------------------------------------

def create_integrated_workflow():
    """
    Create the integrated LangGraph + CrewAI workflow.

    Flow:
    1. User input → Route to specialist
    2. Specialist agent executes task (via CrewAI)
    3. Generate response
    4. Output
    """

    # Build the graph
    workflow = StateGraph(WorkflowState)

    # Add nodes
    workflow.add_node("router", route_to_agent)
    workflow.add_node("specialist", execute_specialist_task)
    workflow.add_node("response", generate_response)

    # Set entry point
    workflow.set_entry_point("router")

    # Add edges
    workflow.add_edge("router", "specialist")
    workflow.add_edge("specialist", "response")
    workflow.add_edge("response", END)

    # Compile
    app = workflow.compile()
    return app


# ---------------------------------------------------------------------------
# MCP Integration
# ---------------------------------------------------------------------------

def register_collaborative_workflow(mcp):
    """
    Register the collaborative multi-agent workflow as an MCP tool.
    """

    # Create the workflow
    workflow_app = create_integrated_workflow()

    @mcp.tool()
    async def team_collaborate(task_description: str) -> str:
        """
        Delegate a complex task to the Groundwire agent team.

        The system will:
        1. Analyze your request
        2. Route to the best specialist (Researcher, Coder, or Writer)
        3. Execute the task with domain expertise
        4. Return a comprehensive response

        Use this for tasks that benefit from specialized expertise.

        Args:
            task_description: Detailed description of what needs to be done

        Returns:
            The specialist's completed work
        """
        try:
            initial_state = {
                "messages": [HumanMessage(content=task_description)],
                "current_agent": "",
                "task_description": task_description,
                "task_output": "",
                "context": {},
                "needs_review": False,
            }

            result = await workflow_app.ainvoke(initial_state)

            # Extract the response
            messages = result.get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    return f"[{result.get('current_agent', 'UNKNOWN')}] {msg.content}"

            return result.get("task_output", "Task completed.")

        except Exception as e:
            return f"[Error in team collaboration: {str(e)}]"

    return workflow_app
