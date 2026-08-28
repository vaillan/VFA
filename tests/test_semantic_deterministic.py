"""Pruebas de las ramas deterministas de app/semantic.py.

Cubre el clic cuantificador ("clic en el primer resultado") y la rama de
escribir normalizada (eliminación de artículos iniciales del campo).
"""

import asyncio

from app.semantic import _resolve_semantic_step_deterministic
from app.tools.parser import CLIC_CUANTIFICADOR_SELECTORES


class FakeLocator:
    def __init__(self, page, count=0):
        self.page = page
        self.count_value = count
        self.first = self

    async def count(self) -> int:
        return self.count_value

    def nth(self, index: int) -> "FakeLocator":
        self.page.nth_indexes.append(index)
        return self

    async def click(self) -> None:
        self.page.clicks.append("click")

    async def fill(self, text: str) -> None:
        self.page.fills.append(text)


class FakePage:
    def __init__(self, counts=None, raise_label=False, raise_placeholder=False):
        self.counts = counts or {}
        self.raise_label = raise_label
        self.raise_placeholder = raise_placeholder
        self.clicks = []
        self.fills = []
        self.nth_indexes = []
        self.locator_selectors = []
        self.labels = []
        self.placeholders = []

    def locator(self, selector: str) -> FakeLocator:
        self.locator_selectors.append(selector)
        return FakeLocator(self, self.counts.get(selector, 0))

    def get_by_label(self, label: str) -> FakeLocator:
        self.labels.append(label)
        if self.raise_label:
            raise Exception("label no encontrado")
        return FakeLocator(self)

    def get_by_placeholder(self, placeholder: str) -> FakeLocator:
        self.placeholders.append(placeholder)
        if self.raise_placeholder:
            raise Exception("placeholder no encontrado")
        return FakeLocator(self)

    def get_by_role(self, role: str, name=None, exact=None) -> FakeLocator:
        return FakeLocator(self)

    def get_by_text(self, texto: str, exact=None) -> FakeLocator:
        return FakeLocator(self)


def test_clic_primer_resultado():
    """(1) 'clic en el primer resultado' clica el primer elemento del selector."""
    page = FakePage(counts={CLIC_CUANTIFICADOR_SELECTORES["resultado"]: 3})
    resultado = asyncio.run(
        _resolve_semantic_step_deterministic(page, "clic en el primer resultado")
    )
    assert resultado == "semantic"
    assert page.nth_indexes == [0]
    assert page.clicks == ["click"]


def test_clic_segundo_enlace():
    """(2) 'clic en el segundo enlace' clica el segundo elemento."""
    page = FakePage(counts={CLIC_CUANTIFICADOR_SELECTORES["enlace"]: 2})
    resultado = asyncio.run(
        _resolve_semantic_step_deterministic(page, "clic en el segundo enlace")
    )
    assert resultado == "semantic"
    assert page.nth_indexes == [1]


def test_clic_tercer_boton():
    """(3) 'clic en el tercer botón' clica el tercer elemento."""
    page = FakePage(counts={CLIC_CUANTIFICADOR_SELECTORES["botón"]: 3})
    resultado = asyncio.run(
        _resolve_semantic_step_deterministic(page, "clic en el tercer botón")
    )
    assert resultado == "semantic"
    assert page.nth_indexes == [2]


def test_click_on_first_result():
    """(4) 'click on the first result' resuelve el ordinal en inglés."""
    page = FakePage(counts={CLIC_CUANTIFICADOR_SELECTORES["result"]: 1})
    resultado = asyncio.run(
        _resolve_semantic_step_deterministic(page, "click on the first result")
    )
    assert resultado == "semantic"
    assert page.nth_indexes == [0]


def test_clic_sin_elementos_unsupported():
    """(5) Sin elementos suficientes retorna 'unsupported' sin clicar."""
    page = FakePage(counts={CLIC_CUANTIFICADOR_SELECTORES["resultado"]: 0})
    resultado = asyncio.run(
        _resolve_semantic_step_deterministic(page, "clic en el primer resultado")
    )
    assert resultado == "unsupported"
    assert page.clicks == []


def test_clic_ordinal_no_soportado_cae_a_generica():
    """(6) 'clic en el cuarto elemento' no matchea y cae a la rama genérica."""
    page = FakePage()
    resultado = asyncio.run(
        _resolve_semantic_step_deterministic(page, "clic en el cuarto elemento")
    )
    assert resultado == "semantic"
    assert page.locator_selectors == []


def test_escribir_campo_con_articulo():
    """(7) 'escribir hola en el campo nombre' normaliza el artículo del campo."""
    page = FakePage()
    resultado = asyncio.run(
        _resolve_semantic_step_deterministic(page, "escribir hola en el campo nombre")
    )
    assert resultado == "semantic"
    assert page.labels == ["campo nombre"]
    assert page.fills == ["hola"]


def test_escribir_campo_sin_articulo():
    """(8) 'escribir hola en nombre' conserva el campo sin artículo."""
    page = FakePage()
    resultado = asyncio.run(
        _resolve_semantic_step_deterministic(page, "escribir hola en nombre")
    )
    assert resultado == "semantic"
    assert page.labels == ["nombre"]


def test_escribir_campo_con_articulo_la():
    """(9) 'escribir hola en la caja email' elimina el artículo 'la'."""
    page = FakePage()
    resultado = asyncio.run(
        _resolve_semantic_step_deterministic(page, "escribir hola en la caja email")
    )
    assert resultado == "semantic"
    assert page.labels == ["caja email"]


def test_escribir_sin_campo_unsupported():
    """(10) 'escribir hola en' sin campo retorna 'unsupported'."""
    page = FakePage()
    resultado = asyncio.run(
        _resolve_semantic_step_deterministic(page, "escribir hola en")
    )
    assert resultado == "unsupported"


def test_escribir_sin_texto_unsupported():
    """(11) 'escribir en campo' sin texto retorna 'unsupported'."""
    page = FakePage()
    resultado = asyncio.run(
        _resolve_semantic_step_deterministic(page, "escribir en campo")
    )
    assert resultado == "unsupported"


def test_escribir_fallback_placeholder():
    """(12) Si get_by_label falla, cae a get_by_placeholder."""
    page = FakePage(raise_label=True)
    resultado = asyncio.run(
        _resolve_semantic_step_deterministic(page, "escribir hola en el campo nombre")
    )
    assert resultado == "semantic"
    assert page.placeholders == ["campo nombre"]


def test_escribir_ambos_fallan_unsupported():
    """(13) Si label y placeholder fallan, retorna 'unsupported'."""
    page = FakePage(raise_label=True, raise_placeholder=True)
    resultado = asyncio.run(
        _resolve_semantic_step_deterministic(page, "escribir hola en el campo nombre")
    )
    assert resultado == "unsupported"
