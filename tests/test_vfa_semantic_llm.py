"""Pruebas del fallback LLM del resolvedor semantico (app/semantic.py).

Cubre: (a) pasos soportados por reglas no invocan el LLM, (b) pasos
"unsupported" por reglas si invocan el LLM, (c) sin API key el fallback
retorna "unsupported" sin excepcion, (d) respuestas LLM malformadas retornan
"unsupported" y los bloques markdown ```json``` se parsean.
"""

import asyncio

import pytest

import app.semantic as semantic_mod
from app.llm import get_vision_llm
from app.semantic import _resolve_semantic_step, _resolve_semantic_step_with_llm


@pytest.fixture(autouse=True)
def _limpiar_cache_llm():
    """Limpia la cache de get_vision_llm antes y despues de cada test."""
    get_vision_llm.cache_clear()
    yield
    get_vision_llm.cache_clear()


class FakeLocator:
    def __init__(self, page):
        self.page = page
        self.first = self

    async def click(self):
        self.page.clicks.append("click")

    async def fill(self, text):
        self.page.fills.append(text)


class FakePage:
    def __init__(self, snapshot=None):
        self.snapshot_data = snapshot or {"role": "document", "children": []}
        self.clicks = []
        self.fills = []

    @property
    def accessibility(self):
        return self

    async def snapshot(self):
        return self.snapshot_data

    def get_by_role(self, role, name=None, exact=None):
        return FakeLocator(self)

    def get_by_text(self, texto, exact=None):
        return FakeLocator(self)

    def get_by_label(self, label):
        return FakeLocator(self)

    def get_by_placeholder(self, placeholder):
        return FakeLocator(self)


class FakeResp:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, content):
        self.content = content
        self.invocations = 0

    async def ainvoke(self, messages):
        self.invocations += 1
        return FakeResp(self.content)


def test_paso_soportado_no_invoca_llm(monkeypatch):
    """(a) Un paso 'clic en Guardar' se resuelve por reglas sin tocar el LLM."""

    class LLMQueNoDebeInvocarse:
        async def ainvoke(self, messages):
            raise AssertionError("El LLM no debe invocarse para pasos soportados")

    monkeypatch.setattr(semantic_mod, "get_vision_llm", lambda *a, **k: LLMQueNoDebeInvocarse())
    page = FakePage(snapshot={"role": "document", "children": [{"role": "button", "name": "Guardar"}]})

    resultado = asyncio.run(_resolve_semantic_step(page, "clic en Guardar"))

    assert resultado == "semantic"
    assert page.clicks == ["click"]


def test_paso_unsupported_invoca_llm(monkeypatch):
    """(b) Un paso no soportado por reglas delega en el LLM y ejecuta la accion."""
    monkeypatch.setenv("VFA_VISION_API_KEY", "test-key")
    llm_fake = FakeLLM(
        '{"action": "click", "selector_role": "button", '
        '"selector_name": "Confirmar", "fill_text": null}'
    )
    monkeypatch.setattr(semantic_mod, "get_vision_llm", lambda *a, **k: llm_fake)
    page = FakePage(snapshot={"role": "document", "children": [{"role": "button", "name": "Confirmar"}]})

    resultado = asyncio.run(_resolve_semantic_step(page, "confirmar la compra"))

    assert resultado == "semantic"
    assert llm_fake.invocations == 1
    assert page.clicks == ["click"]


def test_sin_api_key_retorna_unsupported(monkeypatch):
    """(c) Sin API key el fallback retorna 'unsupported' sin lanzar excepcion."""
    for var in (
        "VFA_VISION_API_KEY",
        "VFA_LLM_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "VFA_VISION_PROVIDER",
        "VFA_LLM_PROVIDER",
    ):
        monkeypatch.delenv(var, raising=False)

    resultado = asyncio.run(_resolve_semantic_step_with_llm(FakePage(), "confirmar la compra"))

    assert resultado == "unsupported"


def test_respuesta_llm_malformada_retorna_unsupported(monkeypatch):
    """(d) Una respuesta LLM no-JSON retorna 'unsupported' sin excepcion."""
    monkeypatch.setenv("VFA_VISION_API_KEY", "test-key")
    llm_fake = FakeLLM("esto no es un json valido")
    monkeypatch.setattr(semantic_mod, "get_vision_llm", lambda *a, **k: llm_fake)

    resultado = asyncio.run(_resolve_semantic_step_with_llm(FakePage(), "confirmar la compra"))

    assert resultado == "unsupported"
    assert llm_fake.invocations == 1


def test_respuesta_markdown_json_se_parsea(monkeypatch):
    """(d) Bloques markdown ```json``` se parsean y ejecutan la accion."""
    monkeypatch.setenv("VFA_VISION_API_KEY", "test-key")
    llm_fake = FakeLLM(
        '```json\n{"action": "click", "selector_role": "button", '
        '"selector_name": "Continuar", "fill_text": null}\n```'
    )
    monkeypatch.setattr(semantic_mod, "get_vision_llm", lambda *a, **k: llm_fake)
    page = FakePage()

    resultado = asyncio.run(_resolve_semantic_step_with_llm(page, "continuar el proceso"))

    assert resultado == "semantic"
    assert page.clicks == ["click"]