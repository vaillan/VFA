"""Pruebas unitarias de la reconexión resiliente de qa_execute_user_flow.

Cubren la reconexión exitosa ante la muerte de la sesión remota, el límite de
reconexiones alcanzado, la restauración de cookies y la no degradación del
flujo normal, usando fakes y monkeypatch (patrón de test_server_mcp_advanced).
"""

import asyncio

import app.tools.qa as qa_mod


class FakeContext:
    """Fake de un BrowserContext que registra las cookies añadidas."""

    def __init__(self, cookies=None):
        self._cookies = cookies or []
        self.added = []

    async def cookies(self):
        return self._cookies

    async def add_cookies(self, cookies):
        self.added.extend(cookies)


class FakeReconnectLocator:
    """Fake de un locator que registra la acción ejecutada."""

    def __init__(self, page, name):
        self._page = page
        self._name = name

    async def fill(self, texto, timeout=None):
        self._page.actions.append(f"fill:{self._name}")

    async def click(self, timeout=None):
        self._page.actions.append(f"click:{self._name}")


class FakeReconnectTextLocator:
    """Fake de un locator de texto que expone .first para el click del flujo."""

    def __init__(self, page, name):
        self.first = FakeReconnectLocator(page, name)


class FakeReconnectPage:
    """Fake de una Page con estado de vida, contexto y locators mínimos."""

    def __init__(self, closed=False, cookies=None):
        self._closed = closed
        self.url = "https://ejemplo.com"
        self.context = FakeContext(cookies)
        self.actions = []

    def is_closed(self):
        return self._closed

    def get_by_text(self, texto, exact=False):
        return FakeReconnectTextLocator(self, f"text:{texto}")

    def get_by_label(self, campo):
        return FakeReconnectLocator(self, f"label:{campo}")

    def get_by_placeholder(self, campo):
        return FakeReconnectLocator(self, f"placeholder:{campo}")


class FakeDieAfterPage(FakeReconnectPage):
    """Página viva en el primer chequeo y muerta a partir del segundo."""

    def __init__(self, cookies=None):
        super().__init__(closed=False, cookies=cookies)
        self._checks = 0

    def is_closed(self):
        self._checks += 1
        return self._checks > 1


class FakeSimplePage:
    """Página sin is_closed ni context (regresión de fakes existentes)."""

    def __init__(self):
        self.url = "https://ejemplo.com"
        self.actions = []

    def get_by_text(self, texto, exact=False):
        return FakeReconnectTextLocator(self, f"text:{texto}")

    def get_by_label(self, campo):
        return FakeReconnectLocator(self, f"label:{campo}")

    def get_by_placeholder(self, campo):
        return FakeReconnectLocator(self, f"placeholder:{campo}")


def _patch_flow(monkeypatch, open_page, goto, reconnect=None):
    monkeypatch.setattr(qa_mod, "_open_page", open_page)
    monkeypatch.setattr(qa_mod, "_goto", goto)
    if reconnect is not None:
        monkeypatch.setattr(qa_mod, "_reconnect_flow", reconnect)
    monkeypatch.setattr(qa_mod, "_attach_console_capture", lambda page: [])
    monkeypatch.setattr(qa_mod, "_capture_network_errors", lambda page: ([], []))


def test_reconnect_exitoso(monkeypatch):
    dead_page = FakeReconnectPage(closed=True)
    live_page = FakeReconnectPage(closed=False)

    async def fake_open_page():
        return None, dead_page

    async def fake_goto(page, url):
        return None

    async def fake_reconnect(browser, page, cookies, last_url):
        return None, live_page

    _patch_flow(monkeypatch, fake_open_page, fake_goto, fake_reconnect)

    result = asyncio.run(
        qa_mod.qa_execute_user_flow(
            "https://ejemplo.com",
            ["clic en Login", "escribir user en Username"],
        )
    )

    assert result["status"] == "completed"
    assert result["steps_executed"] == 2
    assert result["log"][0]["strategy"] == "regex:reconnect"
    assert result["log"][1]["strategy"] == "regex"


def test_reconnect_limite_alcanzado(monkeypatch):
    dead_page = FakeReconnectPage(closed=True)

    async def fake_open_page():
        return None, dead_page

    async def fake_goto(page, url):
        return None

    async def fake_reconnect(browser, page, cookies, last_url):
        return None, dead_page

    _patch_flow(monkeypatch, fake_open_page, fake_goto, fake_reconnect)

    result = asyncio.run(
        qa_mod.qa_execute_user_flow(
            "https://ejemplo.com",
            ["clic en A", "clic en B", "clic en C", "clic en D", "clic en E"],
        )
    )

    assert result["status"] == "completed"
    errors = [e for e in result["log"] if e["status"] == "error"]
    assert len(errors) == 2
    assert all("límite de reconexiones" in e["error"] for e in errors)


def test_restauracion_cookies(monkeypatch):
    cookies = [{"name": "session", "value": "abc"}]
    page_a = FakeDieAfterPage(cookies=cookies)
    page_b = FakeReconnectPage(closed=False)
    received = []

    async def fake_open_page():
        return None, page_a

    async def fake_goto(page, url):
        return None

    async def fake_reconnect(browser, page, cookies, last_url):
        received.append(cookies)
        await qa_mod._restore_session_state(page_b, cookies)
        return None, page_b

    _patch_flow(monkeypatch, fake_open_page, fake_goto, fake_reconnect)

    result = asyncio.run(
        qa_mod.qa_execute_user_flow(
            "https://ejemplo.com",
            ["clic en Login", "clic en Continuar"],
        )
    )

    assert result["status"] == "completed"
    assert received == [cookies]
    assert page_b.context.added == cookies


def test_sin_reconexion_no_degrada(monkeypatch):
    page = FakeSimplePage()

    async def fake_open_page():
        return None, page

    async def fake_goto(page, url):
        return None

    _patch_flow(monkeypatch, fake_open_page, fake_goto)

    result = asyncio.run(
        qa_mod.qa_execute_user_flow(
            "https://ejemplo.com",
            ["clic en Login", "escribir user en Username"],
        )
    )

    assert result["status"] == "completed"
    assert result["steps_executed"] == 2
    assert all(e["strategy"] == "regex" for e in result["log"])