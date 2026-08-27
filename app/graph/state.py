"""Contrato de estado compartido del grafo LangGraph del VFA."""

from typing import Any, Dict, List, Optional, TypedDict


class VFAState(TypedDict, total=False):
    """Estado tipado que fluye entre los nodos del grafo VFA.

    `total=False` permite que cada nodo devuelva únicamente las claves que
    actualiza, dejando el resto del estado intacto.
    """

    url: str
    steps: List[str]
    expected_screenshot_path: Optional[str]
    page: Optional[Any]
    audit_result: Optional[Dict[str, Any]]
    runtime_errors_result: Optional[Dict[str, Any]]
    visual_result: Optional[Dict[str, Any]]
    semantic_result: Optional[Dict[str, Any]]
    deep_result: Optional[Dict[str, Any]]