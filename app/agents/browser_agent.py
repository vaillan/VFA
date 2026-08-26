"""Nodo de auditoría de navegador del grafo VFA."""

from typing import Any, Dict

from app.graph.state import VFAState
from app.tools import qa_audit_url, qa_get_runtime_errors


async def browser_node(state: VFAState) -> Dict[str, Any]:
    """Audita la URL objetivo y captura los errores de runtime del navegador."""
    if "url" not in state:
        raise KeyError("VFAState requiere la clave 'url' para el nodo browser")
    url = state["url"]
    audit = await qa_audit_url(url, state.get("expected_screenshot_path"))
    errors = await qa_get_runtime_errors(url)
    return {"audit_result": audit, "runtime_errors_result": errors}


def route_after_browser(state: VFAState) -> str:
    """Rutea tras el nodo browser: a semantic si hay pasos, si no a vision."""
    return "semantic" if state.get("steps") else "vision"