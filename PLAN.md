## Diagnóstico (discovery)

- Proyecto existente: `VFA` (servidor MCP FastMCP + grafo LangGraph). Rama `release/v1.1.0`.
- Manifiestos presentes: `requirements.txt`, `.env.example`, `server_mcp.py`, `app/`, `tests/` (12 módulos). No hay `pyproject.toml`/`package.json`.
- `README.md` (243 líneas) describe arquitectura, instalación, Browserless, variables de entorno, ejecución y pruebas.

## Inconsistencias detectadas README ↔ código

- **`STAGEHAND_BROWSER` es obsoleto**: documentado en §5.1 (tabla), §5.2 (`.env`) y §5.3 (Windows/Linux + persistencia), pero **ningún módulo lo lee** (`grep` sin coincidencias en `app/`). El modo de navegador lo decide `HEADLESS` vía `app/config.get_headless()` → `app/browser._connect_browser()`.
- **`VISION_MODEL`**: `app/config.get_vision_model()` lo lee pero **no está cableado** (solo se usa `get_vision_model_name()` en `app/llm.py`). Documentarlo como activo es engañoso.
- **§7 comando de pruebas**: indica `pytest tests/`, pero `pytest` **no figura en `requirements.txt`** ni hay `pytest.ini`/`conftest.py`. El comando falla en un entorno recién instalado.
- **§7 lista de tests**: verificar que los 12 módulos de `tests/` estén listados (actualmente sí coinciden).

## Verificaciones que SÍ están correctas (no tocar)

- Diagrama de arquitectura coincide con `app/graph/builder.py`: `START → browser → deep → (vision|semantic) → semantic → END`; router `route_after_browser` en `app/agents/browser_agent.py`.
- Nodos `browser`/`deep`/`vision`/`semantic` y `app/agents/deep_agent.py` (deepagents) correctos.
- Tabla §5.1 (salvo `STAGEHAND_BROWSER`/`VISION_MODEL`) coincide con getters de `app/config.py` y `NAVIGATION_WAIT_UNTIL` de `app/tools/qa.py`.
- `HEADLESS`, `VFA_SESSION_POOL_*`, `VFA_SESSION_STORAGE_STATE`, rate limiter: correctos.

## Cambios a aplicar en `README.md`

- **§5.1**: eliminar la fila `STAGEHAND_BROWSER`; eliminar/ajustar la fila `VISION_MODEL` (marcar como no usada o retirar).
- **§5.2** (ejemplo `.env`): eliminar `STAGEHAND_BROWSER=browserless`.
- **§5.3**: eliminar `STAGEHAND_BROWSER` de los ejemplos PowerShell/bash y de la nota de persistencia (`setx`).
- **§7**: añadir paso previo `pip install pytest` (o nota de dependencia de desarrollo) y confirmar la lista de los 12 módulos de `tests/`.
- **§1**: mantener diagrama; opcionalmente aclarar que el modo navegador se controla con `HEADLESS` (Browserless CDP vs Chromium local visible).
- Revisar coherencia de encabezados/anclas tras eliminar filas (p. ej. enlace a §8).

## Criterios de aceptación

- Ninguna variable documentada queda sin lector en `app/` (o marcada explícitamente como no usada).
- El comando de pruebas de §7 es ejecutable tras seguir §3 (instalación).
- Diagrama y descripción de nodos siguen coincidiendo con `app/graph/builder.py`.