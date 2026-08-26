"""Construcción y compilación del grafo LangGraph del VFA."""

from langgraph.graph import END, START, StateGraph

from app.agents.browser_agent import browser_node, route_after_browser
from app.agents.semantic_agent import semantic_node
from app.agents.vision_agent import vision_node
from app.graph.state import VFAState


def build_graph() -> StateGraph:
    """Construye el StateGraph del VFA con los nodos browser, vision y semantic."""
    graph = StateGraph(VFAState)
    graph.add_node("browser", browser_node)
    graph.add_node("vision", vision_node)
    graph.add_node("semantic", semantic_node)
    graph.add_edge(START, "browser")
    graph.add_conditional_edges(
        "browser",
        route_after_browser,
        {"vision": "vision", "semantic": "semantic"},
    )
    graph.add_edge("vision", "semantic")
    graph.add_edge("semantic", END)
    return graph


def get_compiled_graph():
    """Compila y retorna el grafo LangGraph listo para su ejecución."""
    return build_graph().compile()