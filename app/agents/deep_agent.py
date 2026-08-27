"""Nodo de agente profundo (deepagents) del grafo VFA."""

import uuid
from functools import lru_cache
from typing import Any, Dict, List, Optional

from deepagents import create_deep_agent
from langchain_core.tools import BaseTool, tool

from app import config
from app.graph.state import VFAState
from app.session_pool import session_context
from app.tools import qa_audit_url, qa_execute_user_flow, qa_get_runtime_errors


_DEEP_SESSION_ID: str = f"deep-{uuid.uuid4().hex}"


def _build_model_string() -> str:
    """Compone el identificador `provider:model` que espera create_deep_agent."""
    return f"{config.get_llm_provider()}:{config.get_llm_model()}"


def _wrap_qa_tools() -> List[BaseTool]:
    """Envuelve las tools QA existentes como tools de LangChain."""

    @tool
    async def _qa_audit_tool(
        url: str, expected_screenshot_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """Audita una URL y captura su screenshot y errores de runtime."""
        return await qa_audit_url(url, expected_screenshot_path)

    @tool
    async def _qa_flow_tool(url: str, steps: List[str]) -> Dict[str, Any]:
        """Ejecuta un flujo de usuario paso a paso sobre una URL."""
        return await qa_execute_user_flow(url, steps)

    @tool
    async def _qa_runtime_tool(url: str) -> Dict[str, Any]:
        """Recupera los errores de runtime registrados en una URL."""
        return await qa_get_runtime_errors(url)

    return [_qa_audit_tool, _qa_flow_tool, _qa_runtime_tool]


@lru_cache(maxsize=1)
def _get_deep_agent():
    """Construye y cachea el agente profundo con las tools QA."""
    return create_deep_agent(
        model=_build_model_string(),
        tools=_wrap_qa_tools(),
        system_prompt=(
            "Eres un auditor funcional y visual de aplicaciones web. "
            "Usa las tools QA para auditar URLs, ejecutar flujos y detectar "
            "errores de runtime."
        ),
    )


def _build_prompt(state: VFAState) -> str:
    """Compone el prompt del agente a partir del estado del grafo."""
    url = state.get("url") or "URL no proporcionada"
    steps = state.get("steps") or []
    audit = state.get("audit_result") or {}
    return (
        f"Audita la aplicación web en {url}.\n"
        f"Pasos a ejecutar: {steps or 'ninguno'}.\n"
        f"Resultado de auditoría previo: {audit or 'sin datos'}."
    )


async def deep_node(state: VFAState) -> Dict[str, Any]:
    """Ejecuta el agente profundo y devuelve su resultado en `deep_result`."""
    try:
        with session_context(_DEEP_SESSION_ID):
            result = await _get_deep_agent().ainvoke(
                {"messages": [{"role": "user", "content": _build_prompt(state)}]}
            )
        return {"deep_result": result}
    except Exception as exc:  # noqa: BLE001 - no romper el grafo ante fallos del agente
        return {"deep_result": {"error": str(exc)}}