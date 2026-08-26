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
            '{"action": "click"|"fill"|"unsupported", '
            '"selector_role": string|null, "selector_name": string|null, '
            '"fill_text": string|null}. No anadas texto fuera del JSON.\n'
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

        if action == "click" and role and name:
            await page.get_by_role(role, name=name, exact=False).first.click()
            return "semantic"
        if action == "fill" and role and name and fill_text:
            await page.get_by_role(role, name=name, exact=False).first.fill(fill_text)
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

    return "unsupported"


async def _resolve_semantic_step(page, step: str) -> str:
    """Resuelve un paso en lenguaje natural, delegando al LLM si las reglas fallan."""
    result = await _resolve_semantic_step_deterministic(page, step)
    if result == "unsupported":
        return await _resolve_semantic_step_with_llm(page, step)
    return result