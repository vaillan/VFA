"""Nodo de análisis visual del grafo VFA."""

from typing import Any, Dict

from app.graph.state import VFAState
from app.vision import _analyze_visual_with_llm


async def vision_node(state: VFAState) -> Dict[str, Any]:
    """Analiza visualmente el screenshot producido por la auditoría."""
    audit = state.get("audit_result") or {}
    screenshot = audit.get("screenshot_path")
    if not screenshot:
        return {"visual_result": {"status": "skipped", "reason": "no screenshot"}}
    expected = state.get("expected_screenshot_path") or ""
    return {"visual_result": await _analyze_visual_with_llm(screenshot, expected)}