"""Parser de pasos en lenguaje natural para qa_execute_user_flow.

Funciones puras y testables: tokenización, generación de candidatos de
selectores y patrones regex de acciones. Agnóstico al idioma: la resolución
del objetivo (campo/ícono) no usa diccionarios de un solo idioma, sino
candidatos generados dinámicamente validados contra el DOM real.
"""

import re
from typing import List, Optional

# Patrones regex de acciones (agnósticos al idioma). El conjunto de verbos es
# reducido y multilingüe; la resolución del objetivo NO depende de diccionarios.
RE_CLIC = re.compile(r"(?:clic|click|pulsar|tap|hacer clic|hacer click)\s+(?:en|on|in)?\s*(.+)")
RE_ESCRIBIR = re.compile(
    r"(?:escribir|write|type|enter|fill|llenar|rellenar|introducir)\s+(.+?)\s+(?:en|in|into|at)\s+(.+)$"
)
RE_ESPERAR = re.compile(r"esperar\s+(\d+)")
RE_HOVER = re.compile(r"(?:hover|pasar|mouseover|encima)\s+(?:sobre|on|over|de)?\s*(.+)")
RE_HOVER_CLIC = re.compile(
    r"(?:hover|pasar|mouseover)\s+(?:sobre|on|over|de)?\s*(.+?)\s+(?:y luego|then|y)\s+(?:clic|click)\s+(?:en|on)?\s*(.+)"
)

# Acciones de interacción web ampliadas (scroll, teclado, selección, doble
# clic, verificación, espera de elemento, captura, navegación, archivos,
# drag & drop, cierre de modales y retroceso).
RE_SCROLL = re.compile(
    r"(?:scroll|desplazar|bajar|subir|ir abajo|ir arriba|navigate down|navigate up)\s*"
    r"(?:(?:hacia|to|a|al|into)?\s*(.+))?",
    re.IGNORECASE,
)
RE_PRESIONAR_TECLA = re.compile(
    r"(?:press|presionar|apretar|hit|keyboard|tecla|key)\s+(?:la\s+|el\s+|the\s+)?(.+)",
    re.IGNORECASE,
)
RE_SELECCIONAR = re.compile(
    r"(?:seleccionar|select|elegir|choose|pick|marcar|check|tildar)\s+"
    r"(?:el|la|los|las|the|a|an)?\s*(.+?)\s+"
    r"(?:de|en|por|from|in|del|of|from the)\s*(.+)",
    re.IGNORECASE,
)
RE_DOBLE_CLIC = re.compile(
    r"(?:doble clic|double click|doble click|dblclick|dos clics)\s+"
    r"(?:en|on|in|sobre|over)?\s*(.+)",
    re.IGNORECASE,
)
RE_VERIFICAR = re.compile(
    r"(?:verificar|verify|check|asegurar|ensure|validar|validate|comprobar|confirm)\s+"
    r"(?:que|that|the|el|la)?\s*(.+)",
    re.IGNORECASE,
)
RE_ESPERAR_ELEMENTO = re.compile(
    r"(?:esperar|wait|wait for|waiting)\s+"
    r"(?:a que|que|for|until|hasta que)?\s*"
    r"(?:el|la|the|a|an)?\s*(.+?)\s+"
    r"(?:aparezca|appear|visible|este visible|be visible|cargue|load|este disponible|be available)?",
    re.IGNORECASE,
)
RE_CAPTURAR = re.compile(
    r"(?:capturar|capture|screenshot|take screenshot|tomar captura|snapshot|guardar imagen)",
    re.IGNORECASE,
)
RE_NAVEGAR = re.compile(
    r"(?:navegar|navigate|go to|ir a|abrir|open|acceder|access)\s+"
    r"(?:a|al|to|the|la|el)?\s*(.+)",
    re.IGNORECASE,
)
RE_SUBIR_ARCHIVO = re.compile(
    r"(?:upload|subir|subir archivo|upload file|adjuntar|attach|seleccionar archivo)\s*"
    r"(?:el|la|the|a|an)?\s*(.+)?",
    re.IGNORECASE,
)
RE_ARRASTRAR = re.compile(
    r"(?:drag|arrastrar|arrastar|mover|move|drop|soltar)\s+"
    r"(.+?)\s+"
    r"(?:to|hacia|a|al|into|en)\s+(.+)",
    re.IGNORECASE,
)
RE_CERRAR = re.compile(
    r"(?:cerrar|close|dismiss|descartar|aceptar|accept)\s*"
    r"(?:el|la|the|a|an|modal|popup|dialog|banner|cookie|cookies|overlay|aviso)?\s*(.+)?",
    re.IGNORECASE,
)
RE_ATRAS = re.compile(
    r"(?:volver|back|go back|retroceder|atrás|regresar|return|previous)",
    re.IGNORECASE,
)

# Stopwords multilingües mínimas: SOLO poda de último recurso, nunca mecanismo
# principal. No incluye palabras de contenido (username, carrito, cart, etc.).
STOPWORDS = frozenset({
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "en",
    "al", "a", "the", "a", "an", "of", "in", "on", "at", "to", "for", "and",
    "or", "campo", "field", "botón", "boton", "button", "enlace", "link",
    "icono", "ícono", "icon",
})


def tokenize(text: str) -> List[str]:
    """Divide el texto en tokens normalizados (minúsculas, sin puntuación)."""
    return re.findall(r"[a-z0-9áéíóúüñ]+", text.lower())


def generate_candidates(text: str) -> List[str]:
    """Genera todas las sub-frases y sub-tokens contiguos, de mayor a menor.

    Ej.: "el campo username" -> ["el campo username", "el campo",
    "campo username", "el", "campo", "username"].
    """
    tokens = tokenize(text)
    candidates = []
    for length in range(len(tokens), 0, -1):
        for i in range(len(tokens) - length + 1):
            candidates.append(" ".join(tokens[i:i + length]))
    return candidates


def raw_tokens(text: str) -> List[str]:
    """Tokens crudos normalizados sin stopwords, para selectores CSS.

    Poda de último recurso: si todos fueran stopwords, devuelve los tokens
    originales para no vaciar el conjunto.
    """
    tokens = tokenize(text)
    filtered = [t for t in tokens if t not in STOPWORDS]
    return filtered if filtered else tokens


def parse_step(paso: str) -> Optional[dict]:
    """Parsea un paso en lenguaje natural a una acción estructurada.

    Returns:
        dict con "action" y sus parámetros, o None si el paso no coincide con
        ningún patrón. El orden de dispatch evita colisiones entre verbos
        ambiguos (esperar-numérico, subir-archivo, doble-clic).
    """
    paso_lower = paso.lower()

    # 1. Esperar segundos (antes que esperar_elemento).
    match_esperar = RE_ESPERAR.match(paso_lower)
    if match_esperar:
        return {"action": "esperar", "segundos": int(match_esperar.group(1))}

    # 2. Doble clic (antes que clic).
    match_doble_clic = RE_DOBLE_CLIC.match(paso_lower)
    if match_doble_clic:
        return {"action": "doble_clic", "texto": match_doble_clic.group(1).strip()}

    # 3. Subir archivo (antes que scroll, por el verbo "subir").
    match_subir = RE_SUBIR_ARCHIVO.match(paso_lower)
    if match_subir:
        return {"action": "subir_archivo", "archivo": (match_subir.group(1) or "").strip()}

    # 4. Navegar a URL.
    match_navegar = RE_NAVEGAR.match(paso_lower)
    if match_navegar:
        return {"action": "navegar", "url": match_navegar.group(1).strip()}

    # 5. Retroceder en el historial.
    if RE_ATRAS.match(paso_lower):
        return {"action": "atras"}

    # 6. Cerrar modal/cookie.
    match_cerrar = RE_CERRAR.match(paso_lower)
    if match_cerrar:
        return {"action": "cerrar", "texto": (match_cerrar.group(1) or "").strip()}

    # 7. Arrastrar y soltar.
    match_arrastrar = RE_ARRASTRAR.match(paso_lower)
    if match_arrastrar:
        return {
            "action": "arrastrar",
            "origen": match_arrastrar.group(1).strip(),
            "destino": match_arrastrar.group(2).strip(),
        }

    # 8. Seleccionar opción en un dropdown.
    match_seleccionar = RE_SELECCIONAR.match(paso_lower)
    if match_seleccionar:
        return {
            "action": "seleccionar",
            "opcion": match_seleccionar.group(1).strip(),
            "dropdown": match_seleccionar.group(2).strip(),
        }

    # 9. Presionar tecla.
    match_tecla = RE_PRESIONAR_TECLA.match(paso_lower)
    if match_tecla:
        return {"action": "presionar_tecla", "tecla": match_tecla.group(1).strip()}

    # 10. Verificar/asegurar.
    match_verificar = RE_VERIFICAR.match(paso_lower)
    if match_verificar:
        return {"action": "verificar", "texto": match_verificar.group(1).strip()}

    # 11. Esperar elemento (después de esperar-numérico).
    match_esperar_el = RE_ESPERAR_ELEMENTO.match(paso_lower)
    if match_esperar_el:
        return {"action": "esperar_elemento", "texto": match_esperar_el.group(1).strip()}

    # 12. Capturar pantalla.
    if RE_CAPTURAR.match(paso_lower):
        return {"action": "capturar"}

    # 13. Scroll.
    match_scroll = RE_SCROLL.match(paso_lower)
    if match_scroll:
        return {"action": "scroll", "texto": (match_scroll.group(1) or "").strip()}

    # 14. Clic.
    match_clic = RE_CLIC.match(paso_lower)
    if match_clic:
        return {"action": "clic", "texto": match_clic.group(1).strip()}

    # 15. Escribir.
    match_escribir = RE_ESCRIBIR.match(paso_lower)
    if match_escribir:
        return {
            "action": "escribir",
            "texto": match_escribir.group(1).strip(),
            "campo": match_escribir.group(2).strip(),
        }

    # 16. Hover + clic.
    match_hover_clic = RE_HOVER_CLIC.match(paso_lower)
    if match_hover_clic:
        return {
            "action": "hover_clic",
            "hover_texto": match_hover_clic.group(1).strip(),
            "clic_texto": match_hover_clic.group(2).strip(),
        }

    # 17. Hover.
    match_hover = RE_HOVER.match(paso_lower)
    if match_hover:
        return {"action": "hover", "texto": match_hover.group(1).strip()}

    return None