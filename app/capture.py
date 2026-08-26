"""Captura de mensajes de consola JS, excepciones JS y fallos HTTP de una pagina."""

from typing import Any, Dict, List


def _attach_console_capture(page) -> List[str]:
    """Adjunta un listener que captura errores y warnings de la consola JS.

    Args:
        page: instancia de Page de Playwright.

    Returns:
        List[str]: lista compartida donde se acumulan los mensajes capturados
        con el formato "[TIPO] mensaje".
    """
    captured: List[str] = []

    def _handler(msg) -> None:
        if msg.type in ("error", "warning"):
            captured.append(f"[{msg.type.upper()}] {msg.text}")

    page.on("console", _handler)
    return captured


def _capture_network_errors(page) -> tuple[List[str], List[Dict[str, Any]]]:
    """Adjunta listeners que capturan excepciones JS y fallos HTTP de la página.

    Equivale en runtime a window.onerror (excepciones JS no capturadas) y a un
    filtro de respuestas HTTP con status >= 400 (errores de red).

    Args:
        page: instancia de Page de Playwright.

    Returns:
        tuple con dos listas compartidas:
            - js_exceptions: List[str] con el texto de cada excepción JS.
            - network_errors: List[Dict[str, Any]] con {method, url, status}
              de cada respuesta HTTP con status >= 400.
    """
    js_exceptions: List[str] = []
    network_errors: List[Dict[str, Any]] = []

    def _on_pageerror(exc) -> None:
        js_exceptions.append(str(exc))

    def _on_response(resp) -> None:
        if resp.status >= 400:
            network_errors.append(
                {
                    "method": resp.request.method,
                    "url": resp.url,
                    "status": resp.status,
                }
            )

    page.on("pageerror", _on_pageerror)
    page.on("response", _on_response)
    return js_exceptions, network_errors