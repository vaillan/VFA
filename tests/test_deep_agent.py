"""Pruebas unitarias del Deep Agent y su integración en el grafo VFA."""

from unittest.mock import AsyncMock, patch

import pytest

from app.graph import build_graph
from app.agents.deep_agent import (
    _build_model_string,
    _build_prompt,
    _wrap_qa_tools,
    deep_node,
)


def test_build_model_string():
    """El identificador del modelo sigue el formato provider:model."""
    with patch("app.agents.deep_agent.config.get_llm_provider", return_value="openai"), patch(
        "app.agents.deep_agent.config.get_llm_model", return_value="gpt-4o"
    ):
        assert _build_model_string() == "openai:gpt-4o"


def test_wrap_qa_tools_returns_three():
    """Se envuelven exactamente las tres tools QA."""
    assert len(_wrap_qa_tools()) == 3


def test_build_prompt_with_url():
    """El prompt incluye la URL y los pasos del estado."""
    prompt = _build_prompt({"url": "https://ejemplo.com", "steps": ["click"]})
    assert "https://ejemplo.com" in prompt
    assert "click" in prompt


def test_build_prompt_empty_state():
    """Con estado vacío no lanza y usa valores por defecto."""
    prompt = _build_prompt({})
    assert "URL no proporcionada" in prompt


@pytest.mark.asyncio
async def test_deep_node_success():
    """deep_node devuelve el resultado del agente bajo la clave deep_result."""
    fake_agent = AsyncMock()
    fake_agent.ainvoke.return_value = {"output": "ok"}
    with patch("app.agents.deep_agent._get_deep_agent", return_value=fake_agent):
        result = await deep_node({"url": "https://ejemplo.com"})
    assert result == {"deep_result": {"output": "ok"}}


@pytest.mark.asyncio
async def test_deep_node_error():
    """deep_node captura excepciones del agente sin propagarlas."""
    fake_agent = AsyncMock()
    fake_agent.ainvoke.side_effect = RuntimeError("boom")
    with patch("app.agents.deep_agent._get_deep_agent", return_value=fake_agent):
        result = await deep_node({"url": "https://ejemplo.com"})
    assert "error" in result["deep_result"]


def test_graph_has_deep_node():
    """El grafo registra el nodo deep y el arco browser -> deep."""
    graph = build_graph()
    assert "deep" in graph.nodes
    assert ("browser", "deep") in graph.edges