"""Pruebas unitarias de app/llm.py y de la migracion de app/vision.py.

Ningun test llama a APIs reales: se mockean init_chat_model y ChatOllama, y se
limpia la cache de get_vision_llm entre tests para evitar contaminacion.
"""

import asyncio
import pytest

from app import llm
from app.llm import _create_llm, get_vision_llm, provider_map
from app.vision import _analyze_visual_with_llm


@pytest.fixture(autouse=True)
def _limpiar_cache_llm():
    """Limpia la cache de get_vision_llm antes y despues de cada test."""
    get_vision_llm.cache_clear()
    yield
    get_vision_llm.cache_clear()


def test_provider_map_mapeo():
    """El provider_map mapea correctamente los proveedores clave."""
    assert provider_map["google"] == "google_genai"
    assert provider_map["open-router"] == "openrouter"
    assert provider_map["local"] == "ollama"
    assert provider_map["aws-bedrock"] == "bedrock_converse"


def test_create_llm_provider_invalido():
    """_create_llm lanza ValueError descriptivo ante un proveedor inexistente."""
    with pytest.raises(ValueError) as excinfo:
        _create_llm("proveedor-inexistente", "gpt-4o", "key")
    assert "Unsupported provider" in str(excinfo.value)
    assert "proveedor-inexistente" in str(excinfo.value)


def test_create_llm_import_error(monkeypatch):
    """_create_llm envuelve un ImportError de init_chat_model en ValueError."""

    def _lanzar_import_error(*args, **kwargs):
        raise ImportError("No module named 'langchain_openai'")

    monkeypatch.setattr(llm, "init_chat_model", _lanzar_import_error)
    with pytest.raises(ValueError) as excinfo:
        _create_llm("openai", "gpt-4o", "key")
    assert "Failed to initialize model" in str(excinfo.value)
    assert "openai" in str(excinfo.value)


def test_analyze_visual_skipped_sin_keys(monkeypatch):
    """_analyze_visual_with_llm retorna 'skipped' sin API keys configuradas."""
    for var in (
        "VFA_VISION_API_KEY",
        "VFA_LLM_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "VFA_VISION_PROVIDER",
        "VFA_LLM_PROVIDER",
    ):
        monkeypatch.delenv(var, raising=False)

    resultado = asyncio.run(_analyze_visual_with_llm("ruta/dummy.png", "ruta/esperada.png"))
    assert resultado["status"] == "skipped"
    assert "API key" in resultado["reason"]


def test_get_vision_llm_local_usa_chatollama(monkeypatch):
    """get_vision_llm instancia ChatOllama cuando el proveedor es 'local'."""
    monkeypatch.setenv("VFA_VISION_PROVIDER", "local")
    monkeypatch.setenv("VFA_VISION_MODEL", "llama3")
    monkeypatch.setenv("VFA_VISION_API_KEY", "x")

    instanciado = {}

    class FakeChatOllama:
        def __init__(self, **kwargs):
            instanciado["kwargs"] = kwargs

    monkeypatch.setattr(llm, "ChatOllama", FakeChatOllama)

    modelo = get_vision_llm()
    assert isinstance(modelo, FakeChatOllama)
    assert instanciado["kwargs"]["model"] == "llama3"