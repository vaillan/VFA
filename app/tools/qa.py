"""Definicion de las tools QA del agente VFA como funciones planas.

Las tools se definen aqui SIN decorador @mcp.tool() para evitar una dependencia
circular con server_mcp.py (que crea la instancia FastMCP). El registro se
realiza en server_mcp.py mediante mcp.tool()(func).
"""

import base64
import json
import os
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage
from playwright.async_api import async_playwright

from app import config
from app.browser import _close_browser, _is_session_dead, _new_page
from app.capture import _attach_console_capture, _capture_network_errors
from app.llm import get_vision_llm
from app.semantic import _resolve_semantic_step
from app.session_pool import get_current_session_id, pool
from app.tools import parser
from app.vision import _analyze_visual_with_llm

# Configuración de navegación y captura.
NAVIGATION_TIMEOUT_MS = 30000
# Timeout acotado para acciones de interacción del flujo (evita matar la sesión remota de Browserless).
STEP_TIMEOUT_MS = 10000
# Máximo de reconexiones permitidas ante la muerte de la sesión remota a mitad de flujo.
MAX_RECONNECTS = 3
NAVIGATION_WAIT_UNTIL = os.environ.get("NAVIGATION_WAIT_UNTIL", "load")
AUDIT_SCREENSHOT_FILENAME = "audit_screenshot.png"

# Mapeo de nombres de teclas comunes a los códigos de Playwright.
_KEY_MAP: dict[str, str] = {
    "enter": "Enter",
    "tab": "Tab",
    "escape": "Escape",
    "esc": "Escape",
    "backspace": "Backspace",
    "delete": "Delete",
    "del": "Delete",
    "arrowup": "ArrowUp",
    "arrowdown": "ArrowDown",
    "arrowleft": "ArrowLeft",
    "arrowright": "ArrowRight",
    "space": "Space",
    "home": "Home",
    "end": "End",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "f1": "F1",
    "f2": "F2",
    "f3": "F3",
    "f4": "F4",
    "f5": "F5",
    "f6": "F6",
    "f7": "F7",
    "f8": "F8",
    "f9": "F9",
    "f10": "F10",
    "f11": "F11",
    "f12": "F12",
}


async def _open_page():
    """Conecta al Browserless Docker vía CDP y crea una página nueva.

    El MCP VisualQA siempre usa el navegador remoto de Browserless en vez de
    lanzar Chromium local (no requiere `playwright install chromium`).

    Returns:
        Tupla (browser, page): instancia del navegador conectado y la página nueva creada.
    """
    p = await async_playwright().start()
    try:
        browser = await p.chromium.connect_over_cdp(config.get_browserbase_url())
    except Exception:
        await p.stop()
        raise
    # Mantener el driver vivo para que _close_browser pueda detenerlo.
    browser._playwright = p
    page = await _new_page(browser)
    return browser, page


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


async def _describe_screenshot_with_llm(screenshot_path: str) -> Dict[str, Any]:
    """Describe un screenshot con un LLM multimodal (análisis descriptivo puro).

    Degradación elegante: sin API key configurada, o si la llamada al LLM o el
    parseo fallan, retorna status "first_capture" con description vacía y reason.

    Args:
        screenshot_path: ruta absoluta del screenshot capturado.

    Returns:
        Dict con status "first_capture" y, en caso de éxito, la clave
        description (str) con la descripción visual.
    """
    provider = config.get_vision_provider()
    api_key = config.get_vision_api_key(provider)
    if not api_key:
        return {
            "status": "first_capture",
            "description": "",
            "reason": "No hay API key configurada para el proveedor de vision.",
        }

    try:
        with open(screenshot_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        prompt = (
            "Describe esta captura de pantalla de una página web en detalle: "
            "estructura visual, secciones, elementos destacados, colores y "
            "posibles problemas de layout. Responde EXCLUSIVAMENTE con un JSON "
            'estricto con la clave "description" (string). '
            "No añadas texto fuera del JSON."
        )

        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                },
            ]
        )

        llm = get_vision_llm()
        resp = await llm.ainvoke([message])
        text = resp.content
        if isinstance(text, list):
            # Compatibilidad multi-proveedor: algunos devuelven bloques de contenido.
            text = "".join(
                part.get("text", "") for part in text if isinstance(part, dict)
            )

        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {
                "status": "first_capture",
                "description": "",
                "reason": "Respuesta del LLM no fue JSON válido.",
            }

        return {
            "status": "first_capture",
            "description": data.get("description", ""),
        }
    except Exception as e:
        return {"status": "first_capture", "description": "", "reason": str(e)}


async def qa_audit_url(url: str, expected_screenshot_path: Optional[str] = None) -> Dict[str, Any]:
    """Audita una URL: navega, captura errores de consola/red y toma un screenshot.

    Usa NAVIGATION_WAIT_UNTIL y NAVIGATION_TIMEOUT_MS para la navegación. Sin
    expected_screenshot_path ejecuta análisis visual descriptivo puro
    (vision_analysis con status "first_capture"); con una imagen esperada
    existente, añade análisis visual comparativo multimodal.

    Args:
        url: URL absoluta a auditar.
        expected_screenshot_path: ruta opcional de la imagen esperada.

    Returns:
        Dict con: url, status_code, console_errors_count, console_errors,
        js_exceptions, network_errors, screenshot_path, vision_analysis y passed.
        En fallo devuelve {"error": <mensaje>}.
    """
    session = await pool.acquire(get_current_session_id())
    browser, page = session.browser, session.page
    try:
        console_errors = _attach_console_capture(page)
        js_exceptions, network_errors = _capture_network_errors(page)

        response = await _goto(page, url)
        status_code = response.status if response is not None else 0

        await page.screenshot(path=AUDIT_SCREENSHOT_FILENAME, full_page=True)
        screenshot_path = os.path.abspath(AUDIT_SCREENSHOT_FILENAME)

        if expected_screenshot_path is None:
            vision_analysis = await _describe_screenshot_with_llm(screenshot_path)
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


async def _scroll_into_view(loc) -> None:
    """Desplaza el elemento al viewport antes de interactuar (evita errores de viewport)."""
    scroll = getattr(loc, "scroll_into_view_if_needed", None)
    if scroll is None:
        return
    try:
        await scroll(timeout=STEP_TIMEOUT_MS)
    except Exception:
        pass


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
    """Rellena un campo localizado por role (textbox/searchbox/combobox) y nombre accesible."""
    getter = getattr(page, "get_by_role", None)
    if getter is None:
        return False
    for role in ("textbox", "searchbox", "combobox"):
        try:
            loc = getter(role, name=candidate, exact=not partial)
        except TypeError:
            loc = getter(role, name=candidate)
        if not await _is_unique(loc):
            continue
        try:
            await loc.fill(texto, timeout=STEP_TIMEOUT_MS)
            return True
        except Exception:
            continue
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


async def _fill_unico_campo_visible(page, texto: str) -> bool:
    """Rellena el único campo de escritura visible sin restricción de nombre (último recurso).

    Combobox cubre buscadores que exponen role=combobox (p.ej. Google).
    """
    getter = getattr(page, "get_by_role", None)
    if getter is None:
        return False
    for role in ("searchbox", "textbox", "combobox"):
        try:
            loc = getter(role)
        except Exception:
            continue
        if not await _is_unique(loc):
            continue
        visible = getattr(loc, "is_visible", None)
        if visible is not None:
            try:
                if not await visible():
                    continue
            except Exception:
                continue
        try:
            await loc.fill(texto, timeout=STEP_TIMEOUT_MS)
            return True
        except Exception:
            continue
    return False


async def _fill_campo(page, campo, texto) -> bool:
    """Resuelve el campo objetivo probando candidatos exactos y luego parciales."""
    for partial in (False, True):
        for candidate in parser.generate_candidates(campo):
            if await _fill_candidate(page, candidate, texto, partial):
                return True
    # Último recurso: único campo de escritura visible en la página.
    return await _fill_unico_campo_visible(page, texto)


async def _click_via_text(page, texto, method: str = "click") -> bool:
    """Hace clic en un elemento localizado por su texto visible.

    Si el texto no es único (p.ej. "English" en Wikipedia), hace clic en el
    primer match en lugar de descartar la resolución.
    """
    getter = getattr(page, "get_by_text", None)
    if getter is None:
        return False
    try:
        loc = getter(texto, exact=False)
    except TypeError:
        loc = getter(texto)
    first = getattr(loc, "first", loc)
    if not await _is_unique(loc):
        try:
            await _scroll_into_view(first)
            await getattr(first, method)(timeout=STEP_TIMEOUT_MS)
            return True
        except Exception:
            return False
    try:
        await _scroll_into_view(loc)
        await getattr(loc, method)(timeout=STEP_TIMEOUT_MS)
        return True
    except Exception:
        # Fallback: si el locator no soporta .click() directo, intentar con .first
        try:
            await _scroll_into_view(first)
            await getattr(first, method)(timeout=STEP_TIMEOUT_MS)
            return True
        except Exception:
            return False


async def _click_via_role(page, candidate, method: str = "click") -> bool:
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
            await _scroll_into_view(loc)
            await getattr(loc, method)(timeout=STEP_TIMEOUT_MS)
            return True
        except Exception:
            continue
    return False


async def _click_via_attr(page, attr, candidate, partial, method: str = "click") -> bool:
    """Hace clic en un elemento localizado por atributo CSS."""
    locator = getattr(page, "locator", None)
    if locator is None:
        return False
    selector = f'[{attr}="{candidate}" i]' if not partial else f'[{attr}*="{candidate}" i]'
    loc = locator(selector)
    if not await _is_unique(loc):
        return False
    try:
        await _scroll_into_view(loc)
        await getattr(loc, method)(timeout=STEP_TIMEOUT_MS)
        return True
    except Exception:
        return False


async def _click_via_class(page, token, method: str = "click") -> bool:
    """Hace clic en un elemento localizado por fragmento de clase CSS."""
    locator = getattr(page, "locator", None)
    if locator is None:
        return False
    loc = locator(f'[class*="{token}"]')
    if not await _is_unique(loc):
        return False
    try:
        await _scroll_into_view(loc)
        await getattr(loc, method)(timeout=STEP_TIMEOUT_MS)
        return True
    except Exception:
        return False


async def _click_via_input_valor(page, candidate: str, method: str = "click") -> bool:
    """Hace clic en un <input type=submit|button> cuyo value contenga el candidato (case-insensitive)."""
    locator = getattr(page, "locator", None)
    if locator is None or not candidate:
        return False
    for selector in (
        f'input[type="submit"][value*="{candidate}" i]',
        f'input[type="button"][value*="{candidate}" i]',
    ):
        loc = locator(selector)
        if not await _is_unique(loc):
            continue
        try:
            await _scroll_into_view(loc)
            await getattr(loc, method)(timeout=STEP_TIMEOUT_MS)
            return True
        except Exception:
            continue
    return False


async def _click_objetivo(page, texto) -> bool:
    """Resuelve el objetivo de un clic con espera activa, scroll y reintento (SPAs dinámicos)."""
    for intento in range(2):
        # Espera activa corta: el SPA puede tardar en renderizar el nodo.
        try:
            getter = getattr(page, "get_by_text", None)
            if getter is not None:
                await getter(texto, exact=False).first.wait_for(
                    state="visible", timeout=3000
                )
        except Exception:
            pass  # Si no aparece, se intenta resolver igualmente.
        # Flujo de resolución existente: texto, rol, candidatos, atributos y clases.
        if await _click_via_text(page, texto):
            return True
        if await _click_via_role(page, texto):
            return True
        for candidate in parser.generate_candidates(texto):
            if await _click_via_role(page, candidate):
                return True
        # Selector genérico "clic en <texto>" también resuelve inputs submit/button por value.
        for candidate in parser.generate_candidates(texto):
            if await _click_via_input_valor(page, candidate):
                return True
        for partial in (False, True):
            for candidate in parser.generate_candidates(texto):
                for attr in ("aria-label", "title", "data-test", "data-testid", "id"):
                    if await _click_via_attr(page, attr, candidate, partial):
                        return True
        for token in parser.raw_tokens(texto):
            if await _click_via_class(page, token):
                return True
        # Primer intento fallido: scroll y reintento (elemento fuera de viewport o aún renderizándose).
        if intento == 0:
            try:
                await page.evaluate("window.scrollBy(0, 500)")
                await page.wait_for_timeout(500)
            except Exception:
                pass
    return False


async def _click_boton(page, texto: str) -> bool:
    """Resuelve un clic de botón: texto visible, role=button, value de input, atributos y fallback genérico."""
    if await _click_via_text(page, texto):
        return True
    if await _click_via_role(page, texto):
        return True
    for candidate in parser.generate_candidates(texto):
        if await _click_via_role(page, candidate):
            return True
        if await _click_via_input_valor(page, candidate):
            return True
    for partial in (False, True):
        for candidate in parser.generate_candidates(texto):
            for attr in ("aria-label", "title", "data-test", "data-testid", "id"):
                if await _click_via_attr(page, attr, candidate, partial):
                    return True
    return await _click_objetivo(page, texto)


async def _hover_via_text(page, texto) -> bool:
    """Hace hover sobre un elemento localizado por su texto visible."""
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
        await first.hover(timeout=STEP_TIMEOUT_MS)
        return True
    except Exception:
        return False


async def _hover_via_role(page, candidate) -> bool:
    """Hace hover sobre un elemento localizado por rol y nombre accesible."""
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
            await loc.hover(timeout=STEP_TIMEOUT_MS)
            return True
        except Exception:
            continue
    return False


async def _hover_via_attr(page, attr, candidate, partial) -> bool:
    """Hace hover sobre un elemento localizado por atributo CSS."""
    locator = getattr(page, "locator", None)
    if locator is None:
        return False
    selector = f'[{attr}="{candidate}" i]' if not partial else f'[{attr}*="{candidate}" i]'
    loc = locator(selector)
    if not await _is_unique(loc):
        return False
    try:
        await loc.hover(timeout=STEP_TIMEOUT_MS)
        return True
    except Exception:
        return False


async def _hover_via_class(page, token) -> bool:
    """Hace hover sobre un elemento localizado por fragmento de clase CSS."""
    locator = getattr(page, "locator", None)
    if locator is None:
        return False
    loc = locator(f'[class*="{token}"]')
    if not await _is_unique(loc):
        return False
    try:
        await loc.hover(timeout=STEP_TIMEOUT_MS)
        return True
    except Exception:
        return False


async def _hover_objetivo(page, texto) -> bool:
    """Resuelve el objetivo de un hover por texto, candidatos, atributos y clases."""
    if await _hover_via_text(page, texto):
        return True
    for candidate in parser.generate_candidates(texto):
        if await _hover_via_role(page, candidate):
            return True
    for partial in (False, True):
        for candidate in parser.generate_candidates(texto):
            for attr in ("aria-label", "title", "data-test", "data-testid", "id"):
                if await _hover_via_attr(page, attr, candidate, partial):
                    return True
    for token in parser.raw_tokens(texto):
        if await _hover_via_class(page, token):
            return True
    return False


async def _scroll_objetivo(page, texto) -> bool:
    """Desplaza la página hacia arriba, abajo o hasta un elemento visible."""
    try:
        if texto in ("arriba", "up", "top", "inicio", "start"):
            await page.evaluate("window.scrollTo(0, 0)")
            return True
        if texto in ("abajo", "down", "bottom", "fin", "end"):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            return True
        if texto:
            getter = getattr(page, "get_by_text", None)
            if getter is not None:
                loc = getter(texto, exact=False)
                if await _is_unique(loc):
                    await loc.scroll_into_view_if_needed(timeout=STEP_TIMEOUT_MS)
                    return True
        await page.evaluate("window.scrollBy(0, 500)")
        return True
    except Exception:
        return False


async def _press_key(page, tecla) -> bool:
    """Presiona una tecla del teclado sobre la página."""
    try:
        key = _KEY_MAP.get(tecla.strip().lower(), tecla.strip())
        await page.keyboard.press(key)
        return True
    except Exception:
        return False


async def _seleccionar_opcion(page, opcion, dropdown) -> bool:
    """Selecciona una opción de un dropdown localizado por atributos."""
    locator = getattr(page, "locator", None)
    if locator is not None:
        for attr in ("aria-label", "name", "id", "title"):
            for candidate in parser.generate_candidates(dropdown):
                for partial in (False, True):
                    selector = (
                        f'[{attr}="{candidate}" i]'
                        if not partial
                        else f'[{attr}*="{candidate}" i]'
                    )
                    loc = locator(selector)
                    if not await _is_unique(loc):
                        continue
                    try:
                        await loc.select_option(label=opcion, timeout=STEP_TIMEOUT_MS)
                        return True
                    except Exception:
                        continue
    try:
        if await _click_objetivo(page, dropdown) and await _click_objetivo(page, opcion):
            return True
    except Exception:
        pass
    return False


async def _dblclick_objetivo(page, texto) -> bool:
    """Hace doble clic sobre un objetivo resuelto por texto, rol, atributos o clase."""
    if await _click_via_text(page, texto, method="dblclick"):
        return True
    for candidate in parser.generate_candidates(texto):
        if await _click_via_role(page, candidate, method="dblclick"):
            return True
    for partial in (False, True):
        for candidate in parser.generate_candidates(texto):
            for attr in ("aria-label", "title", "data-test", "data-testid", "id"):
                if await _click_via_attr(page, attr, candidate, partial, method="dblclick"):
                    return True
    for token in parser.raw_tokens(texto):
        if await _click_via_class(page, token, method="dblclick"):
            return True
    return False


async def _verificar_elemento(page, texto) -> bool:
    """Verifica que un elemento con el texto dado sea visible."""
    try:
        getter = getattr(page, "get_by_text", None)
        if getter is None:
            return False
        loc = getter(texto, exact=False)
        return await loc.first.is_visible()
    except Exception:
        return False


async def _esperar_elemento(page, texto) -> bool:
    """Espera a que un elemento con el texto dado sea visible."""
    try:
        getter = getattr(page, "get_by_text", None)
        if getter is None:
            return False
        loc = getter(texto, exact=False)
        await loc.first.wait_for(state="visible", timeout=STEP_TIMEOUT_MS)
        return True
    except Exception:
        return False


async def _capturar_pantalla(page) -> bool:
    """Captura un screenshot de página completa."""
    try:
        await page.screenshot(path="flow_screenshot.png", full_page=True)
        return True
    except Exception:
        return False


async def _navegar_a_url(page, url) -> bool:
    """Navega a la URL indicada."""
    try:
        await _goto(page, url)
        return True
    except Exception:
        return False


async def _subir_archivo(page, archivo) -> bool:
    """Sube un archivo a un input de tipo file."""
    if not archivo:
        return False
    locator = getattr(page, "locator", None)
    if locator is not None:
        for attr in ("name", "id", "title"):
            for candidate in parser.generate_candidates(archivo):
                for partial in (False, True):
                    selector = (
                        f'[{attr}="{candidate}" i]'
                        if not partial
                        else f'[{attr}*="{candidate}" i]'
                    )
                    loc = locator(selector)
                    if not await _is_unique(loc):
                        continue
                    try:
                        await loc.set_input_files(archivo, timeout=STEP_TIMEOUT_MS)
                        return True
                    except Exception:
                        continue
    try:
        loc = locator("input[type=file]")
        if await _is_unique(loc):
            await loc.set_input_files(archivo, timeout=STEP_TIMEOUT_MS)
            return True
    except Exception:
        pass
    return False


async def _arrastrar(page, origen, destino) -> bool:
    """Arrastra un elemento origen hasta un elemento destino."""
    try:
        getter = getattr(page, "get_by_text", None)
        if getter is None:
            return False
        await getter(origen).first.drag_to(
            getter(destino).first, timeout=STEP_TIMEOUT_MS
        )
        return True
    except Exception:
        return False


async def _cerrar(page, texto) -> bool:
    """Cierra un modal, popup o banner de cookies."""
    if texto and await _click_objetivo(page, texto):
        return True
    for etiqueta in ("cerrar", "close", "aceptar", "accept", "ok", "x"):
        if await _click_objetivo(page, etiqueta):
            return True
    return False


async def _navegar_atras(page) -> bool:
    """Retrocede a la página anterior del historial."""
    try:
        await page.go_back(wait_until=NAVIGATION_WAIT_UNTIL, timeout=NAVIGATION_TIMEOUT_MS)
        return True
    except Exception:
        return False


async def _capturar_contenido(page, tipo: str) -> Optional[str]:
    """Extrae el texto de un encabezado (h1/h2/h3) o del cuerpo de la página."""
    try:
        if tipo in ("título", "titulo", "title", "heading", "encabezado", "h1", "h2", "h3"):
            for selector in ("h1", "h2", "h3"):
                loc = page.locator(selector)
                if await loc.count() > 0:
                    return (await loc.first.inner_text()).strip()
        return (await page.evaluate("document.body.innerText")).strip()
    except Exception:
        return None


async def _clic_cuantificador(page, ordinal: int, tipo: str) -> bool:
    """Hace clic en el elemento ordinal (1-based) de un tipo dado."""
    selector = parser.CLIC_CUANTIFICADOR_SELECTORES.get(
        tipo, "a, button, [role=link], [role=button]"
    )
    try:
        loc = page.locator(selector)
        if await loc.count() < ordinal:
            return False
        target = loc.nth(ordinal - 1)
        if not await target.is_visible():
            await target.scroll_into_view_if_needed(timeout=STEP_TIMEOUT_MS)
        await target.click(timeout=STEP_TIMEOUT_MS)
        return True
    except Exception:
        return False


async def _execute_step(page, paso: str) -> Dict[str, Any]:
    """Ejecuta un único paso del flujo y retorna su entrada de log.

    Parsea la acción con parser.parse_step y resuelve el objetivo contra el DOM
    real (campos y clics). Si no coincide, usa el fallback semántico.
    """
    strategy = "regex"
    matched = False
    resultado: Optional[str] = None
    parsed = parser.parse_step(paso)
    regex_matched = parsed is not None
    if parsed is not None:
        if parsed["action"] == "clic":
            if await _click_objetivo(page, parsed["texto"]):
                matched = True

        elif parsed["action"] == "clic_boton":
            if await _click_boton(page, parsed["texto"]):
                matched = True
        elif parsed["action"] == "escribir":
            campo = re.sub(r"^(?:el|la|los|las|the|un|una|unos|unas)\s+", "", parsed["campo"])
            if await _fill_campo(page, campo, parsed["texto"]):
                matched = True
        elif parsed["action"] == "esperar":
            await page.wait_for_timeout(parsed["segundos"] * 1000)
            matched = True
        elif parsed["action"] == "hover":
            if await _hover_objetivo(page, parsed["texto"]):
                matched = True
        elif parsed["action"] == "hover_clic":
            if await _hover_objetivo(page, parsed["hover_texto"]) and await _click_objetivo(
                page, parsed["clic_texto"]
            ):
                matched = True
        elif parsed["action"] == "scroll":
            if await _scroll_objetivo(page, parsed["texto"]):
                matched = True
        elif parsed["action"] == "presionar_tecla":
            if await _press_key(page, parsed["tecla"]):
                matched = True
        elif parsed["action"] == "seleccionar":
            if await _seleccionar_opcion(page, parsed["opcion"], parsed["dropdown"]):
                matched = True
        elif parsed["action"] == "doble_clic":
            if await _dblclick_objetivo(page, parsed["texto"]):
                matched = True
        elif parsed["action"] == "verificar":
            if await _verificar_elemento(page, parsed["texto"]):
                matched = True
        elif parsed["action"] == "esperar_elemento":
            if await _esperar_elemento(page, parsed["texto"]):
                matched = True
        elif parsed["action"] == "capturar":
            if await _capturar_pantalla(page):
                matched = True
        elif parsed["action"] == "navegar":
            if await _navegar_a_url(page, parsed["url"]):
                matched = True
        elif parsed["action"] == "subir_archivo":
            if await _subir_archivo(page, parsed["archivo"]):
                matched = True
        elif parsed["action"] == "arrastrar":
            if await _arrastrar(page, parsed["origen"], parsed["destino"]):
                matched = True
        elif parsed["action"] == "cerrar":
            if await _cerrar(page, parsed["texto"]):
                matched = True
        elif parsed["action"] == "atras":
            if await _navegar_atras(page):
                matched = True
        elif parsed["action"] == "limpiar":
            if await _fill_campo(page, parsed["campo"], ""):
                matched = True
        elif parsed["action"] == "capturar_contenido":
            texto = await _capturar_contenido(page, parsed["tipo"])
            if texto is not None:
                matched = True
                resultado = texto
        elif parsed["action"] == "clic_cuantificador":
            if await _clic_cuantificador(page, parsed["ordinal"], parsed["tipo"]):
                matched = True
        elif parsed["action"] == "ir_inicio":
            if await _scroll_objetivo(page, "top"):
                matched = True

    if not matched:
        if regex_matched:
            strategy = "regex"
        else:
            strategy = await _resolve_semantic_step(page, paso)
            if strategy == "unsupported":
                return {
                    "step": paso,
                    "status": "error",
                    "strategy": strategy,
                    "error": "Paso no soportado por el parser regex ni por el fallback semántico.",
                }
    entry: Dict[str, Any] = {"step": paso, "status": "ok", "strategy": strategy}
    if resultado is not None:
        entry["resultado"] = resultado
    return entry


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
    session = await pool.acquire(get_current_session_id())
    browser, page = session.browser, session.page
    try:
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