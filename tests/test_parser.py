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

    def __init__(self, page, name, count=1, inner_text=""):
        self._page = page
        self._name = name
        self._count = count
        self._inner_text = inner_text
        self.first = self

    async def count(self) -> int:
        return self._count

    async def inner_text(self) -> str:
        return self._inner_text

    def nth(self, index: int) -> "FakeParserLocator":
        return self

    async def fill(self, texto, timeout=None):
        self._page.actions.append(f"fill:{self._name}")

    async def click(self, timeout=None):
        if self._count == 0:
            raise Exception("no element found")
        self._page.actions.append(f"click:{self._name}")

    async def dblclick(self, timeout=None):
        if self._count == 0:
            raise Exception("no element found")
        self._page.actions.append(f"dblclick:{self._name}")

    async def hover(self, timeout=None):
        self._page.actions.append(f"hover:{self._name}")

    async def is_visible(self) -> bool:
        self._page.actions.append(f"visible:{self._name}")
        return self._count > 0

    async def wait_for(self, state=None, timeout=None):
        self._page.actions.append(f"wait_for:{self._name}")

    async def scroll_into_view_if_needed(self, timeout=None):
        self._page.actions.append(f"scroll:{self._name}")

    async def select_option(self, label=None, timeout=None):
        self._page.actions.append(f"select:{self._name}")

    async def set_input_files(self, paths, timeout=None):
        self._page.actions.append(f"upload:{self._name}")

    async def drag_to(self, target, timeout=None):
        self._page.actions.append(f"drag:{self._name}->{target._name}")


class FakeParserPage:
    """Fake de una Page con getters y locator que resuelven por selector."""

    def __init__(self, matches, inner_text=""):
        self.matches = matches
        self.inner_text = inner_text
        self.actions = []

    def _loc(self, name):
        return FakeParserLocator(self, name, self.matches.get(name, 0), self.inner_text)

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

    async def evaluate(self, expr: str) -> str:
        self.actions.append(f"evaluate:{expr}")
        return ""


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
        "campo": "username field",  # "the" ahora se consume
    }
    assert parser.parse_step("click on the shopping cart icon") == {
        "action": "clic",
        "texto": "the shopping cart icon",
    }


def test_parse_step_escribir_comillas_y_articulos():
    # Comillas simples: se eliminan del texto.
    assert parser.parse_step("escribir 'inteligencia artificial' en el campo de busqueda") == {
        "action": "escribir",
        "texto": "inteligencia artificial",
        "campo": "campo de busqueda",
    }
    # Comillas dobles.
    assert parser.parse_step('escribir "hola mundo" en la caja') == {
        "action": "escribir",
        "texto": "hola mundo",
        "campo": "caja",
    }
    # Inglés con artículo y comillas.
    assert parser.parse_step("write 'hello world' in the search field") == {
        "action": "escribir",
        "texto": "hello world",
        "campo": "search field",
    }
    # Texto citado que contiene el separador "en" (no corta dentro de las comillas).
    assert parser.parse_step("escribir 'hola en casa' en el campo") == {
        "action": "escribir",
        "texto": "hola en casa",
        "campo": "campo",
    }
    # Artículo español consumido antes del campo.
    assert parser.parse_step("escribir user en el campo username") == {
        "action": "escribir",
        "texto": "user",
        "campo": "campo username",
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


def test_parse_step_hover():
    assert parser.parse_step("hover sobre Products") == {
        "action": "hover",
        "texto": "products",
    }
    assert parser.parse_step("hover Products") == {
        "action": "hover",
        "texto": "products",
    }
    assert parser.parse_step("pasar mouse sobre Products")["action"] == "hover"


def test_parse_step_hover_clic():
    assert parser.parse_step("hover sobre Products y luego clic en LangSmith") == {
        "action": "hover_clic",
        "hover_texto": "products",
        "clic_texto": "langsmith",
    }


def test_hover_objetivo():
    page = FakeParserPage({"text:products": 1})
    assert asyncio.run(qa_mod._hover_objetivo(page, "products"))
    assert "hover:text:products" in page.actions


def test_execute_step_hover():
    page = FakeParserPage({"text:products": 1})
    resultados = asyncio.run(qa_mod._execute_step(page, "hover sobre Products"))
    assert resultados["status"] == "ok"
    assert "hover:text:products" in page.actions


def test_click_via_text_fallback_primer_match():
    page = FakeParserPage({"text:english": 2})  # "English" no es único
    assert asyncio.run(qa_mod._click_via_text(page, "english"))
    assert "click:text:english" in page.actions


def test_click_objetivo_rol_directo():
    page = FakeParserPage({"role:link:english": 1})  # sin match por texto
    assert asyncio.run(qa_mod._click_objetivo(page, "english"))
    assert "click:role:link:english" in page.actions


def test_click_objetivo_con_retry():
    page = FakeParserPage({})
    assert asyncio.run(qa_mod._click_objetivo(page, "objetivo inexistente")) is False
    assert "evaluate:window.scrollBy(0, 500)" in page.actions
    assert "wait:500" in page.actions


def test_execute_step_limpiar():
    page = FakeParserPage({"placeholder:username": 1})
    resultados = asyncio.run(qa_mod._execute_step(page, "limpiar campo username"))
    assert resultados["status"] == "ok"
    assert "fill:placeholder:username" in page.actions


def test_execute_step_capturar_contenido():
    page = FakeParserPage({"h1": 1}, inner_text="Título principal")
    resultados = asyncio.run(qa_mod._execute_step(page, "capturar el título principal"))
    assert resultados["status"] == "ok"
    assert resultados["resultado"] == "Título principal"


def test_execute_step_ir_inicio():
    page = FakeParserPage({})
    resultados = asyncio.run(qa_mod._execute_step(page, "ir al inicio"))
    assert resultados["status"] == "ok"
    assert "evaluate:window.scrollTo(0, 0)" in page.actions


def test_execute_step_clic_cuantificador():
    page = FakeParserPage({"a, [role=link]": 2})
    resultados = asyncio.run(qa_mod._execute_step(page, "clic en el primer enlace"))
    assert resultados["status"] == "ok"
    assert "click:a, [role=link]" in page.actions


def test_parse_step_scroll_escrolea():
    assert parser.parse_step("escrolea hacia abajo") == {
        "action": "scroll",
        "texto": "abajo",
    }


def test_parse_step_scroll_arriba():
    assert parser.parse_step("scroll hacia arriba") == {
        "action": "scroll",
        "texto": "arriba",
    }


def test_parse_step_scroll_desplazate():
    assert parser.parse_step("desplázate hacia abajo") == {
        "action": "scroll",
        "texto": "abajo",
    }


def test_parse_step_clic_products():
    assert parser.parse_step("clic en Products") == {
        "action": "clic",
        "texto": "products",
    }


def test_parse_step_hacer_clic_boton():
    assert parser.parse_step("hacer clic en el botón Submit") == {
        "action": "clic",
        "texto": "el botón submit",
    }


def test_parse_step_escribir_type_ingles():
    assert parser.parse_step("type standard_user in the username field") == {
        "action": "escribir",
        "texto": "standard_user",
        "campo": "username field",
    }


def test_parse_step_escribir_fill():
    assert parser.parse_step("fill secret in password") == {
        "action": "escribir",
        "texto": "secret",
        "campo": "password",
    }


def test_parse_step_leer_contenido():
    assert parser.parse_step("leer contenido") == {"action": "leer"}


def test_parse_step_leer_contenido_pagina():
    assert parser.parse_step("leer el contenido de la página") == {"action": "leer"}


def test_parse_step_extraer_texto():
    assert parser.parse_step("extraer texto de la sección noticias") == {"action": "leer"}


def test_parse_step_clic_boton_de():
    assert parser.parse_step("clic en el botón de búsqueda") == {
        "action": "clic_boton",
        "texto": "búsqueda",
    }


def test_parse_step_clic_boton_del():
    assert parser.parse_step("clic en el botón del menú") == {
        "action": "clic_boton",
        "texto": "menú",
    }


def test_parse_step_clic_boton_labeled():
    assert parser.parse_step("click on the button labeled Search") == {
        "action": "clic_boton",
        "texto": "search",
    }


def test_parse_step_clic_boton_sin_separador_regresion():
    # Sin separador (de/del/para/que dice/labeled) cae en el clic genérico histórico.
    assert parser.parse_step("hacer clic en el botón Submit") == {
        "action": "clic",
        "texto": "el botón submit",
    }


def test_parse_step_clic_boton_no_colision_cuantificador():
    assert parser.parse_step("clic en el primer botón") == {
        "action": "clic_cuantificador",
        "ordinal": 1,
        "tipo": "botón",
    }


def test_execute_step_clic_boton_role():
    page = FakeParserPage({"role:button:búsqueda": 1})
    resultados = asyncio.run(qa_mod._execute_step(page, "clic en el botón de búsqueda"))
    assert resultados["status"] == "ok"
    assert "click:role:button:búsqueda" in page.actions


def test_execute_step_clic_boton_input_submit():
    page = FakeParserPage({'input[type="submit"][value*="búsqueda" i]': 1})
    resultados = asyncio.run(qa_mod._execute_step(page, "clic en el botón de búsqueda"))
    assert resultados["status"] == "ok"
    assert 'click:input[type="submit"][value*="búsqueda" i]' in page.actions


def test_click_objetivo_input_submit_generico():
    page = FakeParserPage({'input[type="submit"][value*="buscar" i]': 1})
    assert asyncio.run(qa_mod._click_objetivo(page, "buscar"))
    assert 'click:input[type="submit"][value*="buscar" i]' in page.actions


def test_click_boton_fallback_generico():
    page = FakeParserPage({'[class*="búsqueda"]': 1})
    assert asyncio.run(qa_mod._click_boton(page, "búsqueda"))
    assert 'click:[class*="búsqueda"]' in page.actions