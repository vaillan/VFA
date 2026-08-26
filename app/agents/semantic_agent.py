"""Nodo de interpretación semántica del grafo VFA."""

from typing import Any, Dict

from app.graph.state import VFAState
from app.semantic import _resolve_semantic_step


async def semantic_node(state: VFAState) -> Dict[str, Any]:
    """Resuelve cada paso en lenguaje natural mediante accesibilidad."""
    page = state.get("page")
    steps = state.get("steps") or []
    results = []
    for step in steps:
        results.append(await _resolve_semantic_step(page, step))
    return {"semantic_result": results}