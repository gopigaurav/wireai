"""
LangGraph-based agent workflow with Qwen 3.5.
Implements a ReAct-style agent with state management and tool routing.
"""

from typing import Annotated, TypedDict, List
from langchain_ollama import ChatOllama
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END

from groundwire.config import config


# ---------------------------------------------------------------------------
# Agent State
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    """State for the agent workflow."""
    messages: Annotated[List[BaseMessage], lambda x, y: x + y]
    context: dict


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are Groundwire, an advanced AI assistant a local coding assistant.

Your role:
- Help users with tasks ranging from simple queries to complex multi-step workflows
- Use available tools when they can provide accurate information
- Be concise, accurate, and proactive
- Think step-by-step for complex problems

When using tools:
1. Only call a tool when you need specific information
2. After receiving tool results, incorporate them into your response
3. If a tool fails, try an alternative approach or ask the user for clarification

Maintain a helpful, professional tone. Be direct but friendly."""


# ---------------------------------------------------------------------------
# Create LLM with tool binding
# ---------------------------------------------------------------------------

def create_llm(tools=None):
    """Create Qwen 3.5 LLM instance via Ollama."""
    llm = ChatOllama(
        model=config.LLM_MODEL,
        base_url=config.LLM_BASE_URL,
        temperature=float(config.TEMPERATURE),
        num_predict=config.MAX_TOKENS,
    )

    if tools:
        return llm.bind_tools(tools)
    return llm


# ---------------------------------------------------------------------------
# Workflow Nodes
# ---------------------------------------------------------------------------

def should_continue(state: AgentState) -> str:
    """Determine if we should continue to tools or end."""
    messages = state["messages"]
    last_message = messages[-1] if messages else None

    # If the last message has tool calls, continue to tools
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"

    # Otherwise, we're done
    return END


def call_model(state: AgentState, llm) -> dict:
    """Call the LLM with current conversation state."""
    messages = state["messages"]

    # Add system prompt if not present
    if not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)

    response = llm.invoke(messages)
    return {"messages": [response]}


# ---------------------------------------------------------------------------
# Workflow Builder
# ---------------------------------------------------------------------------

def create_agent_workflow(mcp):
    """
    Create and register the agent workflow with MCP.

    This creates a ReAct-style agent that:
    1. Receives user input
    2. Decides whether to use tools or respond directly
    3. Executes tools if needed
    4. Continues until a final response is generated
    """

    # Define tools available to the agent (empty for now - tools come from MCP)
    agent_tools: list = []

    # Create the LLM with tool binding
    llm = create_llm(agent_tools)

    # Build the graph (simplified - direct LLM response without tool routing)
    workflow = StateGraph(AgentState)

    # Add node
    workflow.add_node("agent", lambda state: call_model(state, llm))

    # Set entry point
    workflow.set_entry_point("agent")

    # Add edge
    workflow.add_edge("agent", END)

    # Compile the workflow
    app = workflow.compile()

    @mcp.tool()
    async def agent_query(query: str, context: str = "") -> str:
        """
        Process a query through the agent workflow.
        Use this for complex queries that may require multiple steps or tool calls.

        Args:
            query: The user's question or request
            context: Optional additional context

        Returns:
            The agent's response
        """
        try:
            # Initialize state
            initial_state = {
                "messages": [HumanMessage(content=query)],
                "context": {"additional_context": context} if context else {}
            }

            # Run the workflow
            result = await app.ainvoke(initial_state)

            # Extract the final response
            messages = result.get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and not msg.tool_calls:
                    return msg.content

            return "I was unable to generate a response. Please try again."

        except Exception as e:
            return f"Error processing query: {e}"

    return app
