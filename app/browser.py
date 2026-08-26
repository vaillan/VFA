"""Helpers de conexion al navegador remoto de Browserless via CDP."""

from playwright.async_api import async_playwright

from app.config import get_browserbase_url


async def _connect_browser():
    """Conecta al navegador remoto de Browserless vía CDP.

    Returns:
        Browser: instancia del navegador conectado.
    """
    p = await async_playwright().start()
    try:
        browser = await p.chromium.connect_over_cdp(get_browserbase_url())
    except Exception:
        await p.stop()
        raise
    # Mantener el driver vivo durante todo el ciclo de vida del navegador.
    browser._playwright = p
    return browser


async def _new_page(browser):
    """Crea una nueva página con un viewport estándar de 1280x720.

    Args:
        browser: instancia del navegador conectado.

    Returns:
        Page: página recién creada.
    """
    return await browser.new_page(viewport={"width": 1280, "height": 720})