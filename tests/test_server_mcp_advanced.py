"""Pruebas unitarias de las capacidades avanzadas de server_mcp.py.

Cubren la captura de errores de red, la degradación elegante del análisis
visual con LLM y el registro de tools, sin llamar a APIs reales (solo fakes,
mocks y monkeypatch).
"""

import asyncio

import pytest

import server_mcp
import app.tools.qa as qa_mod


class FakePage:
    """Fake mínimo de una Page de Playwright para probar _capture_network_errors."""

    def __init__(self):
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler


class FakeResponse:
    def __init__(self, status, method="GET", url="https://ejemplo.com/recurso"):
        self.status = status
        self.url = url
        self.request = FakeRequest(method, url)


class FakeRequest:
    def __init__(self, method, url):
        self.method = method
        self.url = url


def test_capture_network_errors_estructura():
    page = FakePage()
    js_exceptions, network_errors = server_mcp._capture_network_errors(page)
    assert isinstance(js_exceptions, list)
    assert isinstance(network_errors, list)
    assert "pageerror" in page.handlers
    assert "response" in page.handlers


def test_capture_network_errors_filtra_http():
    page = FakePage()
    _, network_errors = server_mcp._capture_network_errors(page)
    handler = page.handlers["response"]

    # Status 200 no debe capturarse.
    handler(FakeResponse(status=200))
    assert network_errors == []

    # Status 500 debe capturarse.
    handler(FakeResponse(status=500, method="POST", url="https://ejemplo.com/fallo"))
    assert network_errors == [
        {"method": "POST", "url": "https://ejemplo.com/fallo", "status": 500}
    ]


def test_capture_network_errors_pageerror():
    page = FakePage()
    js_exceptions, _ = server_mcp._capture_network_errors(page)
    handler = page.handlers["pageerror"]
    handler(ValueError("error de prueba"))
    assert js_exceptions == ["error de prueba"]


def test_analyze_visual_skipped_sin_keys(monkeypatch):
    # Limpiar todas las claves que get_vision_api_key puede consumir
    # (VFA_VISION_API_KEY -> VFA_LLM_API_KEY -> OPENAI_API_KEY) y fijar el
    # proveedor para determinismo.
    monkeypatch.delenv("VFA_VISION_API_KEY", raising=False)
    monkeypatch.delenv("VFA_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("VFA_VISION_PROVIDER", "openai")
    result = asyncio.run(
        server_mcp._analyze_visual_with_llm("a.png", "b.png")
    )
    assert result["status"] == "skipped"


def test_tools_registradas_avanzadas():
    tools = server_mcp.mcp._tool_manager._tools
    assert "qa_audit_url" in tools
    assert "qa_execute_user_flow" in tools
    assert "qa_get_runtime_errors" in tools
    assert len(tools) == 3


class FakeBrowser:
    """Fake mínimo de un Browser de Playwright para probar qa_get_runtime_errors."""

    async def close(self):
        pass


class FakeGotoPage:
    """Fake mínimo de una Page con goto para probar qa_get_runtime_errors."""

    async def goto(self, url, wait_until=None, timeout=None):
        return None


def test_qa_get_runtime_errors_estructura(monkeypatch):
    async def fake_connect():
        return FakeBrowser()

    async def fake_new_page(browser):
        return FakeGotoPage()

    monkeypatch.setattr(qa_mod, "_connect_browser", fake_connect)
    monkeypatch.setattr(qa_mod, "_new_page", fake_new_page)
    monkeypatch.setattr(
        qa_mod, "_attach_console_capture", lambda page: ["[ERROR] algo"]
    )
    monkeypatch.setattr(
        qa_mod,
        "_capture_network_errors",
        lambda page: (
            ["js exc"],
            [{"method": "GET", "url": "https://ejemplo.com/x", "status": 500}],
        ),
    )

    result = asyncio.run(qa_mod.qa_get_runtime_errors("https://ejemplo.com"))

    assert result["console_errors"] == ["[ERROR] algo"]
    assert "errors" not in result
    assert result["js_exceptions"] == ["js exc"]
    assert result["network_errors"] == [
        {"method": "GET", "url": "https://ejemplo.com/x", "status": 500}
    ]
    assert result["url"] == "https://ejemplo.com"


class FakePlaywright:
    """Fake mínimo de una instancia Playwright para probar el ciclo de vida del driver."""

    def __init__(self):
        self.stopped = False
        self.chromium = FakeChromium()

    async def stop(self):
        self.stopped = True


class FakeChromium:
    async def connect_over_cdp(self, url):
        return FakeBrowser()


class FakeAsyncPlaywrightCM:
    """Fake del context manager async_playwright() que expone start()."""

    async def start(self):
        return FakePlaywright()


def test_connect_browser_mantiene_playwright_vivo(monkeypatch):
    fake_cm = FakeAsyncPlaywrightCM()
    monkeypatch.setattr("app.browser.async_playwright", lambda: fake_cm)

    browser = asyncio.run(qa_mod._connect_browser())

    assert isinstance(browser, FakeBrowser)
    assert hasattr(browser, "_playwright")
    assert browser._playwright.stopped is False


def test_close_browser_detiene_playwright(monkeypatch):
    fake_cm = FakeAsyncPlaywrightCM()
    monkeypatch.setattr("app.browser.async_playwright", lambda: fake_cm)

    browser = asyncio.run(qa_mod._connect_browser())
    asyncio.run(qa_mod._close_browser(browser))

    assert browser._playwright.stopped is True


class FakeLocator:
    """Fake de un locator de Playwright que registra el timeout recibido."""

    def __init__(self, page, name):
        self._page = page
        self._name = name

    async def fill(self, texto, timeout=None):
        self._page.timeouts.append((f"fill:{self._name}", timeout))

    async def click(self, timeout=None):
        self._page.timeouts.append((f"click:{self._name}", timeout))


class FakeTextLocator:
    """Fake de un locator de texto que expone .first para el click del flujo."""

    def __init__(self, page, name):
        self.first = FakeLocator(page, name)


class FakeFlowPage:
    """Fake de una Page que registra los timeouts de las acciones del flujo."""

    def __init__(self):
        self.timeouts = []
        self.url = "https://ejemplo.com"

    def get_by_label(self, campo):
        return FakeLocator(self, f"label:{campo}")

    def get_by_placeholder(self, campo):
        return FakeLocator(self, f"placeholder:{campo}")

    def get_by_text(self, texto, exact=False):
        return FakeTextLocator(self, f"text:{texto}")


def test_step_timeout_aplicado_en_flujo(monkeypatch):
    assert qa_mod.STEP_TIMEOUT_MS == 10000

    fake_page = FakeFlowPage()

    async def fake_open_page():
        return None, fake_page

    async def fake_goto(page, url):
        return None

    monkeypatch.setattr(qa_mod, "_open_page", fake_open_page)
    monkeypatch.setattr(qa_mod, "_goto", fake_goto)
    monkeypatch.setattr(qa_mod, "_attach_console_capture", lambda page: [])
    monkeypatch.setattr(qa_mod, "_capture_network_errors", lambda page: ([], []))

    asyncio.run(
        qa_mod.qa_execute_user_flow(
            "https://ejemplo.com",
            ["escribir user en Username", "clic en Login"],
        )
    )

    assert ("fill:label:username", qa_mod.STEP_TIMEOUT_MS) in fake_page.timeouts
    assert ("click:text:login", qa_mod.STEP_TIMEOUT_MS) in fake_page.timeouts


def test_flow_adjunta_listeners_para_mantener_conexion(monkeypatch):
    """El flujo adjunta los listeners de captura antes de navegar (regresión CDP)."""
    fake_page = FakeFlowPage()
    attached = []

    async def fake_open_page():
        return None, fake_page

    async def fake_goto(page, url):
        return None

    def fake_attach(page):
        attached.append("console")

    def fake_capture(page):
        attached.append("network")
        return [], []

    monkeypatch.setattr(qa_mod, "_open_page", fake_open_page)
    monkeypatch.setattr(qa_mod, "_goto", fake_goto)
    monkeypatch.setattr(qa_mod, "_attach_console_capture", fake_attach)
    monkeypatch.setattr(qa_mod, "_capture_network_errors", fake_capture)

    result = asyncio.run(
        qa_mod.qa_execute_user_flow("https://ejemplo.com", ["escribir user en Username"])
    )

    assert "console" in attached
    assert "network" in attached
    assert result["status"] == "completed"
    assert result["steps_executed"] == 1