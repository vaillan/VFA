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

# Clic en botón: el separador (de/del/para/que dice/labeled) es obligatorio para
# no romper el caso histórico "hacer clic en el botón Submit" (clic genérico).
RE_CLIC_BOTON = re.compile(
    r"(?:clic|click|pulsar|tap|hacer clic|hacer click)\s+(?:en|on|in|sobre|over)?\s*(?:el|la|los|las|the|a|an|un|una|unos|unas)?\s*(?:botón|boton|button)\s+(?:de|del|para|que dice|labeled)\s+(.+)",
    re.IGNORECASE,
)
RE_ESCRIBIR = re.compile(
    r"(?:escribir|write|type|enter|fill|llenar|rellenar|introducir)\s+"
    r"(?:\"([^\"]+)\"|'([^']+)'|(.+))\s+"
    r"(?:en|in|into|at)\s+"
    r"(?:el|la|los|las|the|a|an)?\s*"
    r"(.+)$"
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
    r"(?:scroll|desplazar|desplázate|desplazate|escrolea|bajar|subir|muévete|muevete|navega hacia|ir abajo|ir arriba|navigate down|navigate up)\s*"
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
RE_IR_INICIO = re.compile(
    r"(?:ir al inicio|go home|ir al home|scroll to top|volver arriba|go to top|inicio|home)",
    re.IGNORECASE,
)
RE_LIMPIAR = re.compile(
    r"(?:limpiar|clear|borrar|vaciar|reset)\s+"
    r"(?:(?:el|la|the|a|an)\s+)?"
    r"(?:(?:campo|field)\s+)?"
    r"(.+)",
    re.IGNORECASE,
)
RE_CAPTURAR_CONTENIDO = re.compile(
    r"(?:capturar|capture|extraer|extract)\s+"
    r"(?:el|la|the|a|an)?\s*"
    r"(título|titulo|title|contenido|content|texto|text|heading|encabezado|h1|h2|h3|párrafo|parrafo|paragraph)"
    r"(?:\s+(?:de|of|del|from)\s+.+)?",
    re.IGNORECASE,
)
RE_LEER = re.compile(
    r"(?:leer|read|extraer|extract)\s+"
    r"(?:el|la|the|a|an)?\s*"
    r"(?:contenido|content|texto|text|página|pagina|page)"
    r"(?:\s+(?:de|of|del|from)\s+(?:el|la|the)?\s*(?:página|pagina|page))?",
    re.IGNORECASE,
)
RE_CLIC_CUANTIFICADOR = re.compile(
    r"(?:clic|click)\s+(?:en|on)\s+(?:el|la|the)\s+"
    r"(primer|first|segundo|second|tercer|third)\s+"
    r"(resultado|result|enlace|link|botón|boton|button|elemento|element)"
    r"(?:\s+.+)?",
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

# Ordinales soportados por el clic cuantificador (1-based).
ORDINALES: dict[str, int] = {
    "primer": 1,
    "first": 1,
    "segundo": 2,
    "second": 2,
    "tercer": 3,
    "third": 3,
}

# Selectores CSS por tipo de elemento para el clic cuantificador.
CLIC_CUANTIFICADOR_SELECTORES: dict[str, str] = {
    "enlace": "a, [role=link]",
    "link": "a, [role=link]",
    "botón": "button, [role=button]",
    "boton": "button, [role=button]",
    "button": "button, [role=button]",
    "elemento": "a, button, [role=link], [role=button]",
    "element": "a, button, [role=link], [role=button]",
    "resultado": "a, button, [role=link], [role=button]",
    "result": "a, button, [role=link], [role=button]",
}


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
        ambiguos (esperar-numérico, subir-archivo, doble-clic, ir-inicio).
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

    # 5. Ir al inicio (antes que atras: "volver arriba" empieza con "volver").
    if RE_IR_INICIO.match(paso_lower):
        return {"action": "ir_inicio"}

    # 6. Retroceder en el historial.
    if RE_ATRAS.match(paso_lower):
        return {"action": "atras"}

    # 7. Cerrar modal/cookie.
    match_cerrar = RE_CERRAR.match(paso_lower)
    if match_cerrar:
        return {"action": "cerrar", "texto": (match_cerrar.group(1) or "").strip()}

    # 8. Arrastrar y soltar.
    match_arrastrar = RE_ARRASTRAR.match(paso_lower)
    if match_arrastrar:
        return {
            "action": "arrastrar",
            "origen": match_arrastrar.group(1).strip(),
            "destino": match_arrastrar.group(2).strip(),
        }

    # 9. Seleccionar opción en un dropdown.
    match_seleccionar = RE_SELECCIONAR.match(paso_lower)
    if match_seleccionar:
        return {
            "action": "seleccionar",
            "opcion": match_seleccionar.group(1).strip(),
            "dropdown": match_seleccionar.group(2).strip(),
        }

    # 10. Presionar tecla.
    match_tecla = RE_PRESIONAR_TECLA.match(paso_lower)
    if match_tecla:
        return {"action": "presionar_tecla", "tecla": match_tecla.group(1).strip()}

    # 11. Verificar/asegurar.
    match_verificar = RE_VERIFICAR.match(paso_lower)
    if match_verificar:
        return {"action": "verificar", "texto": match_verificar.group(1).strip()}

    # 12. Esperar elemento (después de esperar-numérico).
    match_esperar_el = RE_ESPERAR_ELEMENTO.match(paso_lower)
    if match_esperar_el:
        return {"action": "esperar_elemento", "texto": match_esperar_el.group(1).strip()}

    # 13. Capturar contenido (antes que leer, por "extraer texto").
    match_capturar_contenido = RE_CAPTURAR_CONTENIDO.match(paso_lower)
    if match_capturar_contenido:
        return {
            "action": "capturar_contenido",
            "tipo": match_capturar_contenido.group(1).strip(),
        }

    # 14. Leer contenido (después de capturar contenido).
    match_leer = RE_LEER.match(paso_lower)
    if match_leer:
        return {"action": "leer"}

    # 15. Capturar pantalla.
    if RE_CAPTURAR.match(paso_lower):
        return {"action": "capturar"}

    # 16. Scroll.
    match_scroll = RE_SCROLL.match(paso_lower)
    if match_scroll:
        return {"action": "scroll", "texto": (match_scroll.group(1) or "").strip()}

    # 17. Limpiar campo (antes que clic).
    match_limpiar = RE_LIMPIAR.match(paso_lower)
    if match_limpiar:
        return {"action": "limpiar", "campo": match_limpiar.group(1).strip()}

    # 18. Clic cuantificador (antes que clic genérico).
    match_clic_cuantificador = RE_CLIC_CUANTIFICADOR.match(paso_lower)
    if match_clic_cuantificador:
        return {
            "action": "clic_cuantificador",
            "ordinal": ORDINALES[match_clic_cuantificador.group(1)],
            "tipo": match_clic_cuantificador.group(2).strip(),
        }

    # 19. Clic en botón ("clic en el botón de búsqueda") antes que escribir y clic genérico.
    match_clic_boton = RE_CLIC_BOTON.match(paso_lower)
    if match_clic_boton:
        return {"action": "clic_boton", "texto": match_clic_boton.group(1).strip()}

    # 20. Escribir (antes que clic para eliminar ambigüedad de verbos).
    match_escribir = RE_ESCRIBIR.match(paso_lower)
    if match_escribir:
        texto = next(g for g in match_escribir.groups()[:3] if g is not None)
        return {
            "action": "escribir",
            "texto": texto.strip(),
            "campo": match_escribir.group(4).strip(),
        }

    # 21. Clic.
    match_clic = RE_CLIC.match(paso_lower)
    if match_clic:
        return {"action": "clic", "texto": match_clic.group(1).strip()}

    # 22. Hover + clic.
    match_hover_clic = RE_HOVER_CLIC.match(paso_lower)
    if match_hover_clic:
        return {
            "action": "hover_clic",
            "hover_texto": match_hover_clic.group(1).strip(),
            "clic_texto": match_hover_clic.group(2).strip(),
        }

    # 23. Hover.
    match_hover = RE_HOVER.match(paso_lower)
    if match_hover:
        return {"action": "hover", "texto": match_hover.group(1).strip()}

    return None