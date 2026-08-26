"""Definicion de las tools QA del agente VFA como funciones planas.

Las tools se definen aqui SIN decorador @mcp.tool() para evitar una dependencia
circular con server_mcp.py (que crea la instancia FastMCP). El registro se
realiza en server_mcp.py mediante mcp.tool()(func).
"""

import os
from typing import Any, Dict, List, Optional

from app.browser import _connect_browser, _new_page
from app.capture import _attach_console_capture, _capture_network_errors
from app.semantic import _resolve_semantic_step
from app.tools import parser
from app.vision import _analyze_visual_with_llm

# Configuración de navegación y captura.
NAVIGATION_TIMEOUT_MS = 30000
# Timeout acotado para acciones de interacción del flujo (evita matar la sesión remota de Browserless).
STEP_TIMEOUT_MS = 10000
# Máximo de reconexiones permitidas ante la muerte de la sesión remota a mitad de flujo.
MAX_RECONNECTS = 3
NAVIGATION_WAIT_UNTIL = "networkidle"
AUDIT_SCREENSHOT_FILENAME = "audit_screenshot.png"


async def _open_page():
    """Conecta al navegador remoto y crea una página nueva.

    Returns:
        Tupla (browser, page): instancia del navegador conectado y la página nueva creada.
    """
    browser = await _connect_browser()
    page = await _new_page(browser)
    return browser, page


async def _close_browser(browser) -> None:
    """Cierra el navegador solo si sigue abierto.

    Args:
        browser: instancia del navegador a cerrar; si es None no hace nada.
    """
    if browser is not None:
        await browser.close()
        playwright = getattr(browser, "_playwright", None)
        if playwright is not None:
            await playwright.stop()


async def _goto(page, url):
    """Navega a la URL con wait_until y timeout estandarizados.

    Usa NAVIGATION_WAIT_UNTIL como wait_until y NAVIGATION_TIMEOUT_MS como timeout.

    Args:
        page: página de Playwright sobre la que navegar.
        url: URL absoluta a la que navegar.

    Returns:
        Response de Playwright de la navegación, o None si no se produjo respuesta.
    """
    return await page.goto(url, wait_until=NAVIGATION_WAIT_UNTIL, timeout=NAVIGATION_TIMEOUT_MS)


def _is_session_dead(browser, page) -> bool:
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


async def _capture_session_state(page) -> List[Dict[str, Any]]:
    """Captura las cookies de la sesión actual para restaurarlas tras reconectar."""
    try:
        context = getattr(page, "context", None)
        if context is None:
            return []
        cookies = await context.cookies()
        return cookies or []
    except Exception:
        return []


async def _restore_session_state(page, cookies) -> None:
    """Restaura las cookies de sesión capturadas en la página reconectada."""
    if not cookies:
        return
    try:
        context = getattr(page, "context", None)
        if context is not None:
            await context.add_cookies(cookies)
    except Exception:
        pass


async def _reconnect_flow(browser, page, cookies, last_url):
    """Reconecta al navegador remoto y restaura el estado de sesión.

    Cierra la sesión muerta, abre una nueva página, re-adjunta los listeners de
    captura, restaura las cookies y navega a la última URL conocida.

    Returns:
        Tupla (browser, page) con la nueva conexión.
    """
    await _close_browser(browser)
    browser, page = await _open_page()
    _attach_console_capture(page)
    _capture_network_errors(page)
    await _restore_session_state(page, cookies)
    if last_url:
        await _goto(page, last_url)
    return browser, page


async def qa_audit_url(url: str, expected_screenshot_path: Optional[str] = None) -> Dict[str, Any]:
    """Audita una URL: navega, captura errores de consola/red y toma un screenshot.

    Usa NAVIGATION_WAIT_UNTIL y NAVIGATION_TIMEOUT_MS para la navegación. Si se
    proporciona expected_screenshot_path existente, añade un análisis visual
    multimodal (vision_analysis).

    Args:
        url: URL absoluta a auditar.
        expected_screenshot_path: ruta opcional de la imagen esperada.

    Returns:
        Dict con: url, status_code, console_errors_count, console_errors,
        js_exceptions, network_errors, screenshot_path, vision_analysis y passed.
        En fallo devuelve {"error": <mensaje>}.
    """
    browser = None
    try:
        browser, page = await _open_page()
        console_errors = _attach_console_capture(page)
        js_exceptions, network_errors = _capture_network_errors(page)

        response = await _goto(page, url)
        status_code = response.status if response is not None else 0

        await page.screenshot(path=AUDIT_SCREENSHOT_FILENAME, full_page=True)
        screenshot_path = os.path.abspath(AUDIT_SCREENSHOT_FILENAME)

        if expected_screenshot_path is None:
            vision_analysis = {
                "status": "skipped",
                "reason": "expected_screenshot_path no proporcionado",
            }
        elif not os.path.exists(expected_screenshot_path):
            vision_analysis = {
                "status": "skipped",
                "reason": "expected_screenshot_path no existe",
            }
        else:
            vision_analysis = await _analyze_visual_with_llm(
                screenshot_path, expected_screenshot_path
            )

        return {
            "url": url,
            "status_code": status_code,
            "console_errors_count": len(console_errors),
            "console_errors": console_errors,
            "js_exceptions": js_exceptions,
            "network_errors": network_errors,
            "screenshot_path": screenshot_path,
            "vision_analysis": vision_analysis,
            "passed": (
                status_code == 200
                and len(console_errors) == 0
                and len(js_exceptions) == 0
                and len(network_errors) == 0
            ),
        }
    except Exception as e:
        return {"error": f"No se pudo auditar la URL: {str(e)}"}
    finally:
        await _close_browser(browser)


async def _is_unique(loc) -> bool:
    """Verifica que un locator resuelva a un único elemento del DOM."""
    count = getattr(loc, "count", None)
    if count is None:
        return True
    try:
        return await count() == 1
    except Exception:
        return True


async def _fill_via(page, getter_name, candidate, texto, partial) -> bool:
    """Rellena un campo mediante un getter de nombre si resuelve de forma única."""
    getter = getattr(page, getter_name, None)
    if getter is None:
        return False
    try:
        loc = getter(candidate, exact=not partial)
    except TypeError:
        loc = getter(candidate)
    if not await _is_unique(loc):
        return False
    try:
        await loc.fill(texto, timeout=STEP_TIMEOUT_MS)
        return True
    except Exception:
        return False


async def _fill_via_role(page, candidate, texto, partial) -> bool:
    """Rellena un campo localizado por role textbox y nombre accesible."""
    getter = getattr(page, "get_by_role", None)
    if getter is None:
        return False
    try:
        loc = getter("textbox", name=candidate, exact=not partial)
    except TypeError:
        loc = getter("textbox", name=candidate)
    if not await _is_unique(loc):
        return False
    try:
        await loc.fill(texto, timeout=STEP_TIMEOUT_MS)
        return True
    except Exception:
        return False


async def _fill_via_attr(page, attr, candidate, texto, partial) -> bool:
    """Rellena un campo localizado por atributo CSS (aria-label, name, id, title)."""
    locator = getattr(page, "locator", None)
    if locator is None:
        return False
    selector = f'[{attr}="{candidate}" i]' if not partial else f'[{attr}*="{candidate}" i]'
    loc = locator(selector)
    if not await _is_unique(loc):
        return False
    try:
        await loc.fill(texto, timeout=STEP_TIMEOUT_MS)
        return True
    except Exception:
        return False


async def _fill_candidate(page, candidate, texto, partial) -> bool:
    """Prueba un candidato con label, placeholder, role y atributos CSS."""
    if await _fill_via(page, "get_by_label", candidate, texto, partial):
        return True
    if await _fill_via(page, "get_by_placeholder", candidate, texto, partial):
        return True
    if await _fill_via_role(page, candidate, texto, partial):
        return True
    for attr in ("aria-label", "name", "id", "title"):
        if await _fill_via_attr(page, attr, candidate, texto, partial):
            return True
    return False


async def _fill_campo(page, campo, texto) -> bool:
    """Resuelve el campo objetivo probando candidatos exactos y luego parciales."""
    for partial in (False, True):
        for candidate in parser.generate_candidates(campo):
            if await _fill_candidate(page, candidate, texto, partial):
                return True
    return False


async def _click_via_text(page, texto) -> bool:
    """Hace clic en un elemento localizado por su texto visible."""
    getter = getattr(page, "get_by_text", None)
    if getter is None:
        return False
    try:
        loc = getter(texto, exact=False)
    except TypeError:
        loc = getter(texto)
    if not await _is_unique(loc):
        return False
    first = getattr(loc, "first", loc)
    try:
        await first.click(timeout=STEP_TIMEOUT_MS)
        return True
    except Exception:
        return False


async def _click_via_role(page, candidate) -> bool:
    """Hace clic en un elemento localizado por rol y nombre accesible."""
    getter = getattr(page, "get_by_role", None)
    if getter is None:
        return False
    for role in ("link", "button", "img", "menuitem", "tab", "generic"):
        try:
            loc = getter(role, name=candidate, exact=False)
        except TypeError:
            loc = getter(role, name=candidate)
        if not await _is_unique(loc):
            continue
        try:
            await loc.click(timeout=STEP_TIMEOUT_MS)
            return True
        except Exception:
            continue
    return False


async def _click_via_attr(page, attr, candidate, partial) -> bool:
    """Hace clic en un elemento localizado por atributo CSS."""
    locator = getattr(page, "locator", None)
    if locator is None:
        return False
    selector = f'[{attr}="{candidate}" i]' if not partial else f'[{attr}*="{candidate}" i]'
    loc = locator(selector)
    if not await _is_unique(loc):
        return False
    try:
        await loc.click(timeout=STEP_TIMEOUT_MS)
        return True
    except Exception:
        return False


async def _click_via_class(page, token) -> bool:
    """Hace clic en un elemento localizado por fragmento de clase CSS."""
    locator = getattr(page, "locator", None)
    if locator is None:
        return False
    loc = locator(f'[class*="{token}"]')
    if not await _is_unique(loc):
        return False
    try:
        await loc.click(timeout=STEP_TIMEOUT_MS)
        return True
    except Exception:
        return False


async def _click_objetivo(page, texto) -> bool:
    """Resuelve el objetivo de un clic por texto, candidatos, atributos y clases."""
    if await _click_via_text(page, texto):
        return True
    for candidate in parser.generate_candidates(texto):
        if await _click_via_role(page, candidate):
            return True
    for partial in (False, True):
        for candidate in parser.generate_candidates(texto):
            for attr in ("aria-label", "title", "data-test", "data-testid", "id"):
                if await _click_via_attr(page, attr, candidate, partial):
                    return True
    for token in parser.raw_tokens(texto):
        if await _click_via_class(page, token):
            return True
    return False


async def _execute_step(page, paso: str) -> Dict[str, Any]:
    """Ejecuta un único paso del flujo y retorna su entrada de log.

    Parsea la acción con parser.parse_step y resuelve el objetivo contra el DOM
    real (campos y clics). Si no coincide, usa el fallback semántico.
    """
    strategy = "regex"
    matched = False
    parsed = parser.parse_step(paso)
    if parsed is not None:
        if parsed["action"] == "clic":
            if await _click_objetivo(page, parsed["texto"]):
                matched = True
        elif parsed["action"] == "escribir":
            if await _fill_campo(page, parsed["campo"], parsed["texto"]):
                matched = True
        elif parsed["action"] == "esperar":
            await page.wait_for_timeout(parsed["segundos"] * 1000)
            matched = True

    if not matched:
        strategy = await _resolve_semantic_step(page, paso)
        if strategy == "unsupported":
            return {
                "step": paso,
                "status": "error",
                "strategy": strategy,
                "error": "Paso no soportado por el parser regex ni por el fallback semántico.",
            }
    return {"step": paso, "status": "ok", "strategy": strategy}


async def qa_execute_user_flow(url: str, steps: List[str]) -> Dict[str, Any]:
    """Ejecuta una secuencia de pasos de interacción en lenguaje natural.

    Soporta los pasos regex "clic en <texto>", "escribir <texto> en <campo>" y
    "esperar <segundos>", con fallback semántico por accesibilidad si no coinciden.
    Si la sesión remota muere a mitad de flujo, reconecta y restaura el estado
    (cookies y última URL) hasta MAX_RECONNECTS veces.

    Args:
        url: URL absoluta sobre la que ejecutar el flujo.
        steps: lista de pasos en lenguaje natural.

    Returns:
        Dict con: status ("completed"), url, steps_executed y log (entradas con
        step, status, strategy y, en caso de error, la clave error).
        En fallo devuelve {"error": <mensaje>}.
    """
    browser = None
    try:
        browser, page = await _open_page()
        # Mantener viva la suscripción CDP de la página (mismo patrón que qa_audit_url).
        _attach_console_capture(page)
        _capture_network_errors(page)
        await _goto(page, url)

        log: List[Dict[str, Any]] = []
        steps_executed = 0
        reconnect_count = 0
        cookies: List[Dict[str, Any]] = []
        last_url = url

        for paso in steps:
            strategy = "regex"
            reconnected = False
            try:
                # Comprobación proactiva de vida antes de ejecutar el paso.
                if _is_session_dead(browser, page):
                    if reconnect_count >= MAX_RECONNECTS:
                        log.append(
                            {
                                "step": paso,
                                "status": "error",
                                "strategy": strategy,
                                "error": "Sesión remota cerrada y límite de reconexiones alcanzado.",
                            }
                        )
                        continue
                    browser, page = await _reconnect_flow(browser, page, cookies, last_url)
                    reconnect_count += 1
                    reconnected = True

                entry = await _execute_step(page, paso)
                if entry["status"] == "ok":
                    cookies = await _capture_session_state(page)
                    last_url = page.url
                    steps_executed += 1
                if reconnected:
                    entry["strategy"] = "regex:reconnect"
                log.append(entry)
            except Exception as e:
                # Sesión muerta a mitad de paso: reconectar y reintentar una vez.
                if _is_session_dead(browser, page) and reconnect_count < MAX_RECONNECTS:
                    browser, page = await _reconnect_flow(browser, page, cookies, last_url)
                    reconnect_count += 1
                    try:
                        entry = await _execute_step(page, paso)
                        if entry["status"] == "ok":
                            cookies = await _capture_session_state(page)
                            last_url = page.url
                            steps_executed += 1
                        entry["strategy"] = "regex:reconnect"
                        log.append(entry)
                    except Exception as e2:
                        log.append(
                            {
                                "step": paso,
                                "status": "error",
                                "strategy": "regex:reconnect",
                                "error": str(e2),
                            }
                        )
                else:
                    log.append(
                        {"step": paso, "status": "error", "strategy": strategy, "error": str(e)}
                    )

        return {
            "status": "completed",
            "url": page.url,
            "steps_executed": steps_executed,
            "log": log,
        }
    except Exception as e:
        return {"error": f"No se pudo ejecutar el flujo: {str(e)}"}
    finally:
        await _close_browser(browser)


async def qa_get_runtime_errors(url: str) -> Dict[str, Any]:
    """Retorna los errores de consola JS, excepciones JS y fallos HTTP de una URL.

    Navega usando NAVIGATION_WAIT_UNTIL y NAVIGATION_TIMEOUT_MS, interceptando
    mensajes de consola error/warning, excepciones JS y respuestas HTTP >= 400.

    Args:
        url: URL absoluta a inspeccionar.

    Returns:
        Dict con: url, console_errors, js_exceptions y network_errors.
        En fallo devuelve {"error": <mensaje>}.
    """
    browser = None
    try:
        browser, page = await _open_page()
        console_errors = _attach_console_capture(page)
        js_exceptions, network_errors = _capture_network_errors(page)

        await _goto(page, url)

        return {
            "url": url,
            "console_errors": console_errors,
            "js_exceptions": js_exceptions,
            "network_errors": network_errors,
        }
    except Exception as e:
        return {"error": f"No se pudieron obtener los errores de la URL: {str(e)}"}
    finally:
        await _close_browser(browser)