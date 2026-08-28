"""Resolucion semantica de pasos en lenguaje natural via accesibilidad de Playwright."""

import json
import re

from langchain_core.messages import HumanMessage

from app import config
from app.llm import get_vision_llm


def _flatten_accessibility_snapshot(snapshot) -> list:
    """Aplana el arbol de accesibilidad a una lista compacta de {role, name}."""
    flat = []
    if not isinstance(snapshot, dict):
        return flat
    stack = [snapshot]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        flat.append({"role": node.get("role", ""), "name": node.get("name", "") or ""})
        children = node.get("children") or []
        stack.extend(children)
    return flat


async def _resolve_semantic_step_with_llm(page, step: str) -> str:
    """Resuelve un paso no soportado por reglas usando el LLM de vision como fallback.

    Degradacion elegante: sin API key, ante fallo de llamada o de parseo retorna
    "unsupported" sin lanzar excepcion (mismo patron que app/vision.py).
    """
    provider = config.get_vision_provider()
    api_key = config.get_vision_api_key(provider)
    if not api_key:
        return "unsupported"

    try:
        snapshot = await page.accessibility.snapshot()
        context = json.dumps(_flatten_accessibility_snapshot(snapshot), ensure_ascii=False)

        prompt = (
            "Interpreta el paso de usuario sobre la pagina web y responde EXCLUSIVAMENTE "
            "con un JSON estricto con estas claves: "
            '{"action": "click"|"fill"|"hover"|"scroll"|"press_key"|"select"|"dblclick"'
            '|"verify"|"wait_for"|"screenshot"|"navigate"|"unsupported", '
            '"selector_role": string|null, "selector_name": string|null, '
            '"fill_text": string|null, "key": string|null, "option": string|null, '
            '"url": string|null}. No anadas texto fuera del JSON.\n'
            f"Paso del usuario: {step}\n"
            f"Snapshot de accesibilidad: {context}"
        )

        llm = get_vision_llm()
        resp = await llm.ainvoke(
            [HumanMessage(content=[{"type": "text", "text": prompt}])]
        )
        text = resp.content
        if isinstance(text, list):
            # Compatibilidad multi-proveedor: algunos devuelven bloques de contenido.
            text = "".join(
                part.get("text", "") for part in text if isinstance(part, dict)
            )

        # Parseo tolerante a bloques markdown ```json```.
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)

        action = data.get("action")
        role = data.get("selector_role")
        name = data.get("selector_name")
        fill_text = data.get("fill_text")
        key = data.get("key")
        option = data.get("option")
        url = data.get("url")

        if action == "click" and role and name:
            await page.get_by_role(role, name=name, exact=False).first.click()
            return "semantic"
        if action == "hover" and role and name:
            await page.get_by_role(role, name=name, exact=False).first.hover()
            return "semantic"
        if action == "fill" and role and name and fill_text:
            await page.get_by_role(role, name=name, exact=False).first.fill(fill_text)
            return "semantic"
        if action == "dblclick" and role and name:
            await page.get_by_role(role, name=name, exact=False).first.dblclick()
            return "semantic"
        if action == "scroll":
            await page.evaluate("window.scrollBy(0, 500)")
            return "semantic"
        if action == "press_key" and key:
            await page.keyboard.press(key)
            return "semantic"
        if action == "select" and role and name and option:
            await page.get_by_role(role, name=name, exact=False).first.select_option(label=option)
            return "semantic"
        if action == "verify" and role and name:
            loc = page.get_by_role(role, name=name, exact=False).first
            return "semantic" if await loc.is_visible() else "unsupported"
        if action == "wait_for" and role and name:
            await page.get_by_role(role, name=name, exact=False).first.wait_for(
                state="visible", timeout=10000
            )
            return "semantic"
        if action == "screenshot":
            await page.screenshot(path="flow_semantic.png", full_page=True)
            return "semantic"
        if action == "navigate" and url:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            return "semantic"
        return "unsupported"
    except Exception:
        return "unsupported"


async def _resolve_semantic_step_deterministic(page, step: str) -> str:
    """Resuelve un paso en lenguaje natural mediante reglas y accesibilidad de Playwright.

    Actua como fallback semantico al parser regex de qa_execute_user_flow.
    Usa el snapshot de accesibilidad de Playwright (get_by_role, get_by_label,
    get_by_placeholder, get_by_text) para interpretar acciones de clic y de
    relleno de campos.
    """
    step_lower = step.lower()

    # Acciones de clic / pulsación.
    if any(k in step_lower for k in ("clic", "click", "enviar", "botón", "boton", "pulsar", "presionar")):
        texto = step_lower
        for prefijo in ("enviar ", "clic en ", "click en ", "pulsar ", "presionar ", "botón ", "boton "):
            if prefijo in texto:
                texto = texto.split(prefijo, 1)[1]
                break
        texto = texto.strip().strip("'\"")
        if not texto:
            return "unsupported"
        try:
            await page.get_by_role("button", name=texto, exact=False).first.click()
            return "semantic"
        except Exception:
            pass
        try:
            await page.get_by_text(texto, exact=False).first.click()
            return "semantic"
        except Exception:
            return "unsupported"

    # Claves de relleno de campos.
    if any(k in step_lower for k in ("escribir", "llenar", "rellenar", "completar", "introducir")):
        # Formato esperado: "<verbo> <texto> en <campo>"
        match = re.match(r"(?:escribir|llenar|rellenar|completar|introducir) (.+) en (.+)", step_lower)
        if not match:
            return "unsupported"
        texto = match.group(1).strip().strip("'\"")
        campo = match.group(2).strip().strip("'\"")
        if not texto or not campo:
            return "unsupported"
        try:
            await page.get_by_label(campo).fill(texto)
            return "semantic"
        except Exception:
            pass
        try:
            await page.get_by_placeholder(campo).fill(texto)
            return "semantic"
        except Exception:
            return "unsupported"

    # Scroll.
    if any(k in step_lower for k in ("scroll", "desplazar", "bajar", "subir", "ir abajo", "ir arriba")):
        try:
            if any(k in step_lower for k in ("arriba", "up", "top", "inicio", "start")):
                await page.evaluate("window.scrollTo(0, 0)")
            elif any(k in step_lower for k in ("abajo", "down", "bottom", "fin", "end")):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            else:
                await page.evaluate("window.scrollBy(0, 500)")
            return "semantic"
        except Exception:
            return "unsupported"

    # Presionar tecla.
    if any(k in step_lower for k in ("presionar", "press", "apretar", "tecla", "key")):
        tecla = step_lower
        for prefijo in ("presionar ", "press ", "apretar ", "tecla ", "key "):
            if prefijo in tecla:
                tecla = tecla.split(prefijo, 1)[1]
                break
        tecla = tecla.strip().strip("'\"")
        if not tecla:
            return "unsupported"
        try:
            await page.keyboard.press(tecla)
            return "semantic"
        except Exception:
            return "unsupported"

    # Verificar elemento.
    if any(k in step_lower for k in ("verificar", "verify", "asegurar", "validar", "comprobar", "confirm")):
        texto = step_lower
        for prefijo in ("verificar que ", "verificar ", "verify that ", "verify ", "asegurar que ", "validar que ", "comprobar que ", "confirm "):
            if prefijo in texto:
                texto = texto.split(prefijo, 1)[1]
                break
        texto = texto.strip().strip("'\"")
        if not texto:
            return "unsupported"
        try:
            return "semantic" if await page.get_by_text(texto, exact=False).first.is_visible() else "unsupported"
        except Exception:
            return "unsupported"

    # Capturar pantalla.
    if any(k in step_lower for k in ("capturar", "capture", "screenshot", "tomar captura", "snapshot")):
        try:
            await page.screenshot(path="flow_semantic.png", full_page=True)
            return "semantic"
        except Exception:
            return "unsupported"

    # Retroceder.
    if any(k in step_lower for k in ("volver", "back", "retroceder", "atrás", "atras", "regresar", "go back")):
        try:
            await page.go_back()
            return "semantic"
        except Exception:
            return "unsupported"

    return "unsupported"


async def _resolve_semantic_step(page, step: str) -> str:
    """Resuelve un paso en lenguaje natural, delegando al LLM si las reglas fallan."""
    result = await _resolve_semantic_step_deterministic(page, step)
    if result == "unsupported":
        return await _resolve_semantic_step_with_llm(page, step)
    return result