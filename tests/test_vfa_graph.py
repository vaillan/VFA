"""Pruebas unitarias del grafo LangGraph del VFA (estructura y ruteo)."""

import pytest

from app.graph import build_graph, get_compiled_graph
from app.graph.nodes import route_after_browser


def test_graph_compila():
    """El grafo compilado no es None."""
    graph = get_compiled_graph()
    assert graph is not None


def test_nodos_browser_vision_semantic():
    """El grafo registra los nodos browser, vision y semantic."""
    graph = build_graph()
    assert {"browser", "vision", "semantic"} <= set(graph.nodes)


def test_route_after_browser_con_steps():
    """Con steps presentes, el ruteo dirige a semantic."""
    assert route_after_browser({"steps": ["click"]}) == "semantic"


def test_route_after_browser_sin_steps():
    """Sin steps, el ruteo dirige a vision."""
    assert route_after_browser({}) == "vision"


def test_aristas_condicionales():
    """Existe una arista condicional desde el nodo browser hacia vision y semantic."""
    graph = build_graph()
    assert "browser" in graph.branches
    mapping = graph.branches["browser"]
    # En esta versión de LangGraph, mapping es un dict {nombre_funcion: BranchSpec}
    # donde cada BranchSpec.ends contiene los destinos de la arista condicional.
    destinos = set()
    for spec in mapping.values():
        destinos.update(spec.ends.keys())
    assert "vision" in destinos
    assert "semantic" in destinos