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
        dict con "action" ("clic"|"escribir"|"esperar") y sus parámetros, o
        None si el paso no coincide con ningún patrón.
    """
    paso_lower = paso.lower()
    match_clic = RE_CLIC.match(paso_lower)
    if match_clic:
        return {"action": "clic", "texto": match_clic.group(1).strip()}
    match_escribir = RE_ESCRIBIR.match(paso_lower)
    if match_escribir:
        return {
            "action": "escribir",
            "texto": match_escribir.group(1).strip(),
            "campo": match_escribir.group(2).strip(),
        }
    match_esperar = RE_ESPERAR.match(paso_lower)
    if match_esperar:
        return {"action": "esperar", "segundos": int(match_esperar.group(1))}
    return None