"""Pruebas unitarias del scroll previo al click en las tools QA.

Verifican que _click_via_text, _click_via_attr y _click_via_input_valor
ejecutan _scroll_into_view antes de cada click, que un fallo de scroll no
bloquea el click y que un fallo de click retorna False. El import del módulo
también valida la corrección de sintaxis de la última línea de app/tools/qa.py.
"""

import asyncio
from typing import List, Optional

import app.tools.qa as qa_mod


class FakeScrollLocator:
    """Fake de locator que registra scroll y click en page.actions."""

    def __init__(
        self,
        page: "FakeScrollPage",
        name: str,
        count: int = 1,
        first: Optional["FakeScrollLocator"] = None,
        fail_scroll: bool = False,
        fail_click: bool = False,
    ) -> None:
        self._page = page
        self._name = name
        self._count = count
        self.first = first
        self._fail_scroll = fail_scroll
        self._fail_click = fail_click

    async def count(self) -> int:
        return self._count

    async def scroll_into_view_if_needed(self, timeout: Optional[int] = None) -> None:
        if self._fail_scroll:
            raise RuntimeError("scroll falló")
        self._page.actions.append(f"scroll:{self._name}")

    async def click(self, timeout: Optional[int] = None) -> None:
        if self._fail_click:
            raise RuntimeError("click falló")
        self._page.actions.append(f"click:{self._name}")


class FakeScrollPage:
    """Fake de Page con get_by_text y locator que devuelven locators de scroll."""

    def __init__(self) -> None:
        self.actions: List[str] = []
        self._locators: dict = {}

    def set_locator(self, key: str, loc: FakeScrollLocator) -> None:
        self._locators[key] = loc

    def get_by_text(self, texto: str, exact: bool = False) -> FakeScrollLocator:
        return self._locators[f"text:{texto}"]

    def locator(self, selector: str) -> FakeScrollLocator:
        return self._locators[f"css:{selector}"]


def test_click_via_text_unico_hace_scroll():
    page = FakeScrollPage()
    loc = FakeScrollLocator(page, "text:Login", count=1)
    page.set_locator("text:Login", loc)

    result = asyncio.run(qa_mod._click_via_text(page, "Login"))

    assert result is True
    assert page.actions == ["scroll:text:Login", "click:text:Login"]


def test_click_via_text_no_unico_usa_first():
    page = FakeScrollPage()
    first = FakeScrollLocator(page, "first:Login", count=1)
    loc = FakeScrollLocator(page, "text:Login", count=2, first=first)
    page.set_locator("text:Login", loc)

    result = asyncio.run(qa_mod._click_via_text(page, "Login"))

    assert result is True
    assert page.actions == ["scroll:first:Login", "click:first:Login"]


def test_click_via_attr_hace_scroll():
    page = FakeScrollPage()
    selector = '[aria-label="Login" i]'
    loc = FakeScrollLocator(page, f"css:{selector}", count=1)
    page.set_locator(f"css:{selector}", loc)

    result = asyncio.run(qa_mod._click_via_attr(page, "aria-label", "Login", False))

    assert result is True
    assert page.actions == [f"scroll:css:{selector}", f"click:css:{selector}"]


def test_click_via_input_valor_primer_selector():
    page = FakeScrollPage()
    selector = 'input[type="submit"][value*="Login" i]'
    loc = FakeScrollLocator(page, f"css:{selector}", count=1)
    page.set_locator(f"css:{selector}", loc)

    result = asyncio.run(qa_mod._click_via_input_valor(page, "Login"))

    assert result is True
    assert page.actions == [f"scroll:css:{selector}", f"click:css:{selector}"]


def test_click_via_input_valor_segundo_selector():
    page = FakeScrollPage()
    selector_1 = 'input[type="submit"][value*="Login" i]'
    selector_2 = 'input[type="button"][value*="Login" i]'
    page.set_locator(f"css:{selector_1}", FakeScrollLocator(page, f"css:{selector_1}", count=0))
    loc_2 = FakeScrollLocator(page, f"css:{selector_2}", count=1)
    page.set_locator(f"css:{selector_2}", loc_2)

    result = asyncio.run(qa_mod._click_via_input_valor(page, "Login"))

    assert result is True
    assert page.actions == [f"scroll:css:{selector_2}", f"click:css:{selector_2}"]


def test_scroll_falla_no_bloquea_click():
    page = FakeScrollPage()
    loc = FakeScrollLocator(page, "text:Login", count=1, fail_scroll=True)
    page.set_locator("text:Login", loc)

    result = asyncio.run(qa_mod._click_via_text(page, "Login"))

    assert result is True
    assert page.actions == ["click:text:Login"]


def test_click_falla_retorna_false():
    page = FakeScrollPage()
    loc = FakeScrollLocator(page, "text:Login", count=1, fail_click=True)
    page.set_locator("text:Login", loc)

    result = asyncio.run(qa_mod._click_via_text(page, "Login"))

    assert result is False
    assert page.actions == ["scroll:text:Login"]