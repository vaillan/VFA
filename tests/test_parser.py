"""Pruebas unitarias del parser de pasos y de los helpers de resolución.

Cubren las funciones puras de app.tools.parser, la resolución de campos y clics
contra el DOM (defectos corregidos), la agnosticidad de idioma y la regresión
del flujo vía _execute_step, usando fakes estilo tests/test_qa_reconnect.py.
"""

import asyncio

import app.tools.parser as parser
import app.tools.qa as qa_mod


class FakeParserLocator:
    """Fake de un locator que registra la acción ejecutada y su unicidad."""

    def __init__(self, page, name, count=1):
        self._page = page
        self._name = name
        self._count = count
        self.first = self

    async def count(self) -> int:
        return self._count

    async def fill(self, texto, timeout=None):
        self._page.actions.append(f"fill:{self._name}")

    async def click(self, timeout=None):
        self._page.actions.append(f"click:{self._name}")


class FakeParserPage:
    """Fake de una Page con getters y locator que resuelven por selector."""

    def __init__(self, matches):
        self.matches = matches
        self.actions = []

    def _loc(self, name):
        return FakeParserLocator(self, name, self.matches.get(name, 0))

    def get_by_text(self, texto, exact=False):
        return self._loc(f"text:{texto}")

    def get_by_label(self, campo, exact=None):
        return self._loc(f"label:{campo}")

    def get_by_placeholder(self, campo, exact=None):
        return self._loc(f"placeholder:{campo}")

    def get_by_role(self, role, name=None, exact=None):
        return self._loc(f"role:{role}:{name}")

    def locator(self, selector):
        return self._loc(selector)

    async def wait_for_timeout(self, ms):
        self.actions.append(f"wait:{ms}")


def test_tokenize():
    assert parser.tokenize("El Campo Username!") == ["el", "campo", "username"]


def test_generate_candidates_orden():
    candidatos = parser.generate_candidates("el campo username")
    assert candidatos[0] == "el campo username"
    assert "username" in candidatos


def test_raw_tokens_quita_stopwords():
    tokens = parser.raw_tokens("el carrito de compras")
    assert "carrito" in tokens
    assert "compras" in tokens


def test_parse_step_espanol():
    assert parser.parse_step("clic en el carrito") == {
        "action": "clic",
        "texto": "el carrito",
    }
    assert parser.parse_step("escribir user en username") == {
        "action": "escribir",
        "texto": "user",
        "campo": "username",
    }
    assert parser.parse_step("esperar 3") == {"action": "esperar", "segundos": 3}


def test_parse_step_ingles():
    assert parser.parse_step("write standard_user in the username field") == {
        "action": "escribir",
        "texto": "standard_user",
        "campo": "the username field",
    }
    assert parser.parse_step("click on the shopping cart icon") == {
        "action": "clic",
        "texto": "the shopping cart icon",
    }


def test_fill_campo_resuelve_subtoken():
    page = FakeParserPage({"placeholder:username": 1})
    assert asyncio.run(qa_mod._fill_campo(page, "el campo username", "standard_user"))
    assert "fill:placeholder:username" in page.actions


def test_click_objetivo_resuelve_icono_svg():
    page = FakeParserPage({'[class*="carrito"]': 1})
    assert asyncio.run(qa_mod._click_objetivo(page, "el carrito de compras"))
    assert 'click:[class*="carrito"]' in page.actions


def test_fill_campo_ingles():
    page = FakeParserPage({"placeholder:username": 1})
    assert asyncio.run(qa_mod._fill_campo(page, "the username field", "standard_user"))
    assert "fill:placeholder:username" in page.actions


def test_click_objetivo_ingles():
    page = FakeParserPage({'[class*="cart"]': 1})
    assert asyncio.run(qa_mod._click_objetivo(page, "the shopping cart icon"))
    assert 'click:[class*="cart"]' in page.actions


def test_execute_step_regresion():
    page = FakeParserPage(
        {"text:login": 1, "text:add to cart": 1, "label:username": 1}
    )
    pasos = ["clic en Login", "escribir user en Username", "clic en Add to cart", "esperar 2"]
    resultados = asyncio.run(qa_mod._execute_step(page, pasos[0]))
    assert resultados["status"] == "ok"
    for paso in pasos[1:]:
        resultados = asyncio.run(qa_mod._execute_step(page, paso))
        assert resultados["status"] == "ok"
    assert "click:text:login" in page.actions
    assert "fill:label:username" in page.actions
    assert "click:text:add to cart" in page.actions
    assert "wait:2000" in page.actions