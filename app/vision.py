"""Analisis visual de screenshots con un LLM multimodal y degradacion elegante."""

import base64
import json
from typing import Any, Dict

from langchain_core.messages import HumanMessage

from app import config
from app.llm import get_vision_llm


async def _analyze_visual_with_llm(screenshot_path: str, expected_path: str) -> Dict[str, Any]:
    """Compara dos screenshots con un LLM multimodal y retorna análisis estructurado.

    Obtiene el modelo de vision a traves de la fabrica agnostica al proveedor
    (app.llm.get_vision_llm) y lo invoca con mensajes multimodales estandar de
    LangChain (HumanMessage con bloques de texto e imagen en data URI base64).

    Degradación elegante: si no hay API key configurada retorna
    {"status": "skipped", "reason": ...}; si la llamada al LLM o el parseo
    fallan, retorna {"status": "error"|"ok", ...} sin lanzar excepción.

    Args:
        screenshot_path: ruta absoluta del screenshot capturado.
        expected_path: ruta absoluta de la imagen esperada.

    Returns:
        Dict con status ("ok"|"skipped"|"error") y, en caso de éxito, las
        claves verdict ("match"|"mismatch"|"uncertain"), differences (List[str])
        y layout_broken (bool).
    """
    provider = config.get_vision_provider()
    api_key = config.get_vision_api_key(provider)
    if not api_key:
        return {
            "status": "skipped",
            "reason": "No hay API key configurada para el proveedor de vision.",
        }

    try:
        with open(screenshot_path, "rb") as f:
            b64_actual = base64.b64encode(f.read()).decode()
        with open(expected_path, "rb") as f:
            b64_expected = base64.b64encode(f.read()).decode()

        prompt = (
            "Compara estas dos capturas de pantalla de una misma página web "
            "(la primera es la actual, la segunda la esperada). Responde "
            "EXCLUSIVAMENTE con un JSON estricto con estas claves: "
            '{"verdict": "match"|"mismatch"|"uncertain", '
            '"differences": [string], "layout_broken": boolean}. '
            "No añadas texto fuera del JSON."
        )

        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64_actual}"},
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64_expected}"},
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

        # Extraer el JSON de la respuesta (puede venir envuelto en markdown).
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {
                "status": "ok",
                "verdict": "uncertain",
                "differences": [],
                "layout_broken": False,
            }

        return {
            "status": "ok",
            "verdict": data.get("verdict", "uncertain"),
            "differences": data.get("differences", []),
            "layout_broken": data.get("layout_broken", False),
        }
    except Exception as e:
        return {"status": "error", "reason": str(e)}