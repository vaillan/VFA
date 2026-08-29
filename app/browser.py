"""Helpers de conexion y ciclo de vida del navegador (remoto Browserless o Chromium local visible)."""

from typing import Any

from playwright.async_api import async_playwright

from app.config import get_browserbase_url, get_headless


async def _connect_browser():
    """Conecta al navegador remoto de Browserless vía CDP o lanza Chromium local visible.

    El modo se decide por HEADLESS: con 'true' (default) se conecta al CDP de
    Browserless; con 'false' se lanza un Chromium local maximizado y visible.

    Returns:
        Browser: instancia del navegador conectado o lanzado.
    """
    p = await async_playwright().start()
    try:
        if get_headless():
            browser = await p.chromium.connect_over_cdp(get_browserbase_url())
        else:
            browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
    except Exception:
        await p.stop()
        raise
    # Mantener el driver vivo durante todo el ciclo de vida del navegador.
    browser._playwright = p
    return browser


async def _new_page(browser):
    """Crea una nueva página; el viewport solo se fuerza en modo headless.

    En modo visible (HEADLESS=false) no se define viewport para que la página
    ocupe la ventana maximizada del Chromium local.

    Args:
        browser: instancia del navegador conectado o lanzado.

    Returns:
        Page: página recién creada.
    """
    if get_headless():
        return await browser.new_page(viewport={"width": 1280, "height": 720})
    return await browser.new_page()


async def _close_browser(browser: Any) -> None:
    """Cierra el navegador solo si sigue abierto."""
    if browser is not None:
        await browser.close()
        playwright = getattr(browser, "_playwright", None)
        if playwright is not None:
            await playwright.stop()


def _is_session_dead(browser: Any, page: Any) -> bool:
    """Detecta si la página o el navegador remoto se cerraron.

    Defensivo: si los métodos de vida no existen (fakes) o lanzan excepción,
    se asume sesión muerta solo ante evidencia real de cierre.
    """
    try:
        is_closed = getattr(page, "is_closed", None)
        if is_closed is not None and is_closed():
            return True
        is_connected = getattr(browser, "is_connected", None)
        if is_connected is not None and not is_connected():
            return True
    except Exception:
        return True
    return False