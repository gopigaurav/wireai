"""
Workflow registry — registers all LangGraph workflows with the MCP server.
"""

from groundwire.workflows.agent_workflow import create_agent_workflow
from groundwire.workflows.crewai_langgraph_workflow import register_collaborative_workflow
from groundwire.workflows.task_router import register_task_router
from groundwire.workflows.examples import register_collaboration_examples


def register_workflows(mcp):
    """Register all workflows with the MCP server."""
    create_agent_workflow(mcp)
    register_collaborative_workflow(mcp)
    register_task_router(mcp)
    register_collaboration_examples(mcp)
