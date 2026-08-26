"""Nodos de grafo del VFA por dominio."""

from app.agents.browser_agent import browser_node, route_after_browser
from app.agents.semantic_agent import semantic_node
from app.agents.vision_agent import vision_node

__all__ = [
    "browser_node",
    "semantic_node",
    "vision_node",
    "route_after_browser",
]