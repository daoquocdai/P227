from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from src.agents.nodes.reasoning import reasoning_node
from src.agents.state import AgentState


def should_continue(state: AgentState) -> str:
    """Route based on whether an error occurred during analysis."""
    if state.get("error"):
        return END
    return END


def build_graph() -> CompiledStateGraph:
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("reasoning", reasoning_node)

    # Add edges
    graph.set_entry_point("reasoning")
    graph.add_conditional_edges("reasoning", should_continue)

    return graph.compile()


agent = build_graph()
