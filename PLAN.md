## Objetivo
Actualizar `README.md` para que refleje el estado real del código (rutas, tools, vars de entorno, inventario de tests y stack). Tarea exclusivamente documental: sin cambios de lógica ni de manifiestos.

## Hallazgos de discovery (fuente de verdad verificada)
- Servidor FastMCP (`server_mcp.py`) registra exactamente 3 tools: `qa_audit_url`, `qa_execute_user_flow`, `qa_get_runtime_errors`; fragmento `GRAPH = get_compiled_graph()` y `BROWSERBASE_URL` re-exportados para tests.
- Firma real de tools en `app/tools/qa.py`:
  - `qa_audit_url(url: str, expected_screenshot_path: Optional[str] = None) -> Dict` → `url, status_code, console_errors_count, console_errors, js_exceptions, network_errors, screenshot_path, vision_analysis, passed`.
  - `qa_execute_user_flow(url: str, steps: List[str]) -> Dict` → `status ("completed"), url, steps_executed, log`.
  - `qa_get_runtime_errors(url: str) -> Dict` → `url, console_errors, js_exceptions, network_errors`.
  - En fallo las 3 devuelven `{"error": <mensaje>}`.
- Grafo en `app/graph/builder.py`: `START → browser → deep → (route_after_browser) → vision|semantic → semantic → END`; estado tipado en `app/graph/state.py` (`VFAState`).
- Nodos reales en `app/agents/`: `browser_agent.py`, `vision_agent.py`, `semantic_agent.py`, `deep_agent.py` (usa `deepagents.create_deep_agent` con modelo `provider:model`).
- Proveedores LLM soportados (`app/llm.py::provider_map`): `openai, anthropic, google (google_genai), open-router (openrouter), local (ollama), azure (azure_openai), aws-bedrock (bedrock_converse), huggingface`.
- **Vars obsoletas/no-efectivas detectadas:** `STAGEHAND_BROWSER` no se referencia en ningún módulo; `VISION_MODEL` solo lo lee `config.get_vision_model()`, que no tiene ninguna llamada en el código. Deben marcarse como legacy/no-op.
- **Inventario de tests incompleto en README:** faltan `test_parser.py`, `test_parser_actions.py`, `test_qa_scroll.py`, `test_semantic_deterministic.py`, `test_vfa_semantic_llm.py`, `test_qa_reconnect.py` (12 archivos en total).
- Runner real de tests: `pytest` (importado en 8 de los 12 archivos); `requirements.txt` no incluye `pytest` → documentarlo como dependencia de desarrollo.

## Cambios concretos en `README.md`
- **Cabecera (L1–L5):** eliminar la línea huérfana `# AIDevTeam`; mantener título `VFA — Visual & Functional Auditor`; aclarar que no requiere `playwright install chromium` (usa CDP Browserless).
- **§1 Arquitectura (L7–L56):**
  - Mantener diagrama Mermaid; ajustar etiqueta del nodo `browser` a `app/agents/browser_agent.py` y `deep` a `app/agents/deep_agent.py`.
  - Ampliar la lista de bullets: añadir `app/agents/{browser,vision,semantic,deep}_agent.py`, `app/graph/{builder,state,nodes}.py`, `app/llm.py` (fábrica agnóstica al proveedor + `InMemoryRateLimiter`), `app/vision.py`, `app/semantic.py`.
  - Corregir la línea de "Captura" que repite el enlace `app/capture.py` dos veces.
- **Nueva §2 "Tools QA (referencia)":** tabla con nombre, parámetros, retorno y casos de error de las 3 tools (según firmas verificadas). Renumerar secciones siguientes.
- **§ Requisitos/Instalación:** añadir nota de dependencia de desarrollo `pytest` y comando exacto `pip install pytest` (temporal hasta que se añada a `requirements.txt`/extra dev).
- **§ Configuración (tabla de variables):**
  - Marcar `STAGEHAND_BROWSER` y `VISION_MODEL` como **legacy / sin efecto** (o eliminarlas de la tabla y del ejemplo `.env`, dejando nota).
  - Añadir filas faltantes verificadas contra `app/config.py`: `VFA_SESSION_STORAGE_STATE`, y confirmar `NAVIGATION_WAIT_UNTIL`, `HEADLESS`, `VFA_SESSION_POOL_*`, `VFA_LLM_REQUESTS_PER_SECOND`, `VFA_LLM_CHECKS_PER_SECOND`.
  - Documentar el `provider_map` de proveedores válidos para `VFA_LLM_PROVIDER`/`VFA_VISION_PROVIDER`.
  - Actualizar el ejemplo `.env` (L138–L161) alineándolo con `.env.example` vigente.
- **§ Ejecución de pruebas (L189–L206):** cambiar `pytest tests/` por el runner real y listar los **12** archivos de test; describir cobertura por área (parser/acciones/scroll, semantic, sesiones/pool, grafo, llm, deep agent, reconexión, server MCP).
- **Nueva § "Estructura del proyecto":** árbol de directorios (`server_mcp.py`, `app/`, `app/agents/`, `app/graph/`, `app/tools/`, `tests/`, `.env.example`).
- **Nueva § "Configuración del cliente MCP":** ejemplo de bloque `mcpServers` (transporte `stdio`, comando `python server_mcp.py` con intérprete del venv).
- **§ Solución de problemas:** conservar sección Windows; añadir entrada sobre `GraphRecursionError`/límite `MAX_RECONNECTS=3` y sobre TTL del session pool si procede.
- **Coherencia de estilo:** español, sin voseo, identificadores y rutas en inglés; conservar badges/encabezados existentes.

## Riesgos y validaciones
- No introducir documentación de comportamiento no verificable (p. ej. no prometer `playwright install`).
- Verificar que cada variable documentada tenga un `os.getenv` correspondiente en `app/config.py` o `app/tools/qa.py`.
- No tocar código, manifiestos ni tests.