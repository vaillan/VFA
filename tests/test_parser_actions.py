"""Pruebas unitarias del dispatch de las 17 acciones de parser.parse_step."""

import pytest

import app.tools.parser as parser


@pytest.mark.parametrize(
    "paso,esperado",
    [
        # 1. Scroll (RE_SCROLL captura el destino en grupo 1).
        ("scroll down", {"action": "scroll", "texto": "down"}),
        # 2. Presionar tecla.
        ("press Enter", {"action": "presionar_tecla", "tecla": "enter"}),
        # 3. Seleccionar opción en dropdown.
        (
            "seleccionar Option de dropdown",
            {"action": "seleccionar", "opcion": "option", "dropdown": "dropdown"},
        ),
        # 4. Doble clic.
        ("doble clic en item", {"action": "doble_clic", "texto": "item"}),
        # 5. Verificar.
        (
            "verificar que el mensaje existe",
            {"action": "verificar", "texto": "el mensaje existe"},
        ),
        # 6. Esperar elemento (el determinante "el" lo consume el patrón).
        (
            "esperar que el boton aparezca",
            {"action": "esperar_elemento", "texto": "boton"},
        ),
        # 7. Capturar pantalla.
        ("capturar pantalla", {"action": "capturar"}),
        # 8. Navegar a URL.
        ("navegar a https://x.com", {"action": "navegar", "url": "https://x.com"}),
        # 9. Subir archivo.
        (
            "upload file cv.pdf",
            {"action": "subir_archivo", "archivo": "file cv.pdf"},
        ),
        # 10. Arrastrar y soltar.
        (
            "arrastrar item hacia la papelera",
            {"action": "arrastrar", "origen": "item", "destino": "la papelera"},
        ),
        # 11. Cerrar modal (el determinante "el" lo consume el patrón).
        ("cerrar el modal", {"action": "cerrar", "texto": "modal"}),
        # 12. Retroceder en el historial.
        ("go back", {"action": "atras"}),
        # 13. Hover.
        ("hover sobre Products", {"action": "hover", "texto": "products"}),
        # 14. Hover + clic.
        (
            "hover sobre X y luego clic en Y",
            {"action": "hover_clic", "hover_texto": "x", "clic_texto": "y"},
        ),
        # 15. Clic.
        ("clic en Login", {"action": "clic", "texto": "login"}),
        # 16. Escribir.
        (
            "escribir user en campo",
            {"action": "escribir", "texto": "user", "campo": "campo"},
        ),
        # 17. Esperar segundos.
        ("esperar 3", {"action": "esperar", "segundos": 3}),
        # 18. Escribir con comillas simples y artículo.
        (
            "escribir 'hola mundo' en el campo",
            {"action": "escribir", "texto": "hola mundo", "campo": "campo"},
        ),
        # 19. Escribir en inglés con artículo.
        (
            "write user in the username field",
            {"action": "escribir", "texto": "user", "campo": "username field"},
        ),
    ],
)
def test_parse_step_17_acciones(paso: str, esperado: dict) -> None:
    """Cada paso en lenguaje natural se resuelve a la acción estructurada."""
    assert parser.parse_step(paso) == esperado


def test_parse_step_caso_invalido() -> None:
    """Un paso sin verbo de acción reconocido no coincide con ningún patrón."""
    assert parser.parse_step("texto sin accion") is None


@pytest.mark.parametrize(
    "paso,esperado",
    [
        # 20. Limpiar campo.
        ("limpiar campo username", {"action": "limpiar", "campo": "username"}),
        ("clear the field email", {"action": "limpiar", "campo": "email"}),
        ("borrar la caja de busqueda", {"action": "limpiar", "campo": "caja de busqueda"}),
        ("limpiar username", {"action": "limpiar", "campo": "username"}),
        # 21. Capturar contenido.
        ("capturar el título principal", {"action": "capturar_contenido", "tipo": "título"}),
        (
            "capturar el contenido de la sección",
            {"action": "capturar_contenido", "tipo": "contenido"},
        ),
        ("extraer texto", {"action": "capturar_contenido", "tipo": "texto"}),
        ("capture the title", {"action": "capturar_contenido", "tipo": "title"}),
        # 22. Clic cuantificador.
        (
            "clic en el primer enlace",
            {"action": "clic_cuantificador", "ordinal": 1, "tipo": "enlace"},
        ),
        (
            "click on the second button",
            {"action": "clic_cuantificador", "ordinal": 2, "tipo": "button"},
        ),
        (
            "clic en el tercer elemento",
            {"action": "clic_cuantificador", "ordinal": 3, "tipo": "elemento"},
        ),
        # 23. Ir al inicio.
        ("ir al inicio", {"action": "ir_inicio"}),
        ("go home", {"action": "ir_inicio"}),
        ("volver arriba", {"action": "ir_inicio"}),
        ("scroll to top", {"action": "ir_inicio"}),
    ],
)
def test_parse_step_nuevas_acciones(paso: str, esperado: dict) -> None:
    """Las 4 acciones nuevas (limpiar, capturar_contenido, clic_cuantificador, ir_inicio) se despachan correctamente."""
    assert parser.parse_step(paso) == esperado


@pytest.mark.parametrize(
    "paso,esperado",
    [
        # "volver" no debe colisionar con ir_inicio (que exige "volver arriba").
        ("volver", {"action": "atras"}),
        # "capturar screenshot" no es capturar_contenido (screenshot no es un tipo).
        ("capturar screenshot", {"action": "capturar"}),
        # "tomar captura" no es capturar_contenido (tomar no es verbo de captura de contenido).
        ("tomar captura", {"action": "capturar"}),
        # "clic en inicio" no es clic_cuantificador (inicio no es ordinal).
        ("clic en inicio", {"action": "clic", "texto": "inicio"}),
    ],
)
def test_parse_step_nuevas_acciones_no_colision(paso: str, esperado: dict) -> None:
    """El orden de dispatch evita colisiones entre las regex nuevas y las preexistentes."""
    assert parser.parse_step(paso) == esperado