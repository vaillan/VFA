# VFA — Visual & Functional Auditor

**VFA — Visual & Functional Auditor** es un servidor MCP
(Model Context Protocol) construido con **FastMCP** que expone tres herramientas
de QA para auditar aplicaciones web en un navegador remoto **Browserless**
(ejecutado en Docker). El agente usa **Playwright** para conectarse al navegador
remoto vía CDP, captura errores de consola y de red, ejecuta flujos de usuario en
lenguaje natural y analiza visualmente las páginas con un modelo LLM multimodal.

El servidor expone exactamente **3 tools QA**:

- `qa_audit_url` — audita una URL y reporta errores de consola, excepciones JS y fallos HTTP.
- `qa_execute_user_flow` — ejecuta un flujo de usuario descrito en lenguaje natural.
- `qa_get_runtime_errors` — recupera los errores de ejecución capturados durante la auditoría.

---

## 1. Arquitectura general

```
Cliente MCP (stdio)
        │
        ▼
server_mcp.py  (FastMCP — punto de entrada, registra las 3 tools QA)
        │
        ▼
app/  (agents, graph, tools, config, browser, capture, vision, semantic)
        │
        ▼
Playwright (async)  ──CDP──►  Browserless (Docker, puerto 3000)
```

- La configuración central del proyecto vive en **`app/config.py`**, que lee las
  variables de entorno (con carga automática desde un archivo `.env` vía
  `python-dotenv`).
- El orquestador es un **grafo LangGraph** que vive en `app/graph/`:
  - `state.py` — define el estado tipado `VFAState` que fluye entre los nodos.
  - `nodes.py` — re-export de compatibilidad: la implementación real de los
    nodos async `browser_node`, `deep_node`, `vision_node` y `semantic_node` y
    del router condicional `route_after_browser` vive en `app/agents/`
    (`browser_agent.py`, `deep_agent.py`, `vision_agent.py`, `semantic_agent.py`).
  - `builder.py` — expone `build_graph()`/`get_compiled_graph()` y ensambla el
    `StateGraph` con el flujo:
    `START → browser → deep → condicional (route_after_browser: semantic si hay steps, vision si no) → vision → semantic → END`.
- `server_mcp.py` compila y usa el grafo LangGraph; la API pública de las 3 tools
  MCP no cambió.
- `requirements.txt` incluye `langgraph>=0.2` y ya no incluye `crewai`.
- La conexión al navegador remoto se realiza en `app/browser.py` mediante
  Playwright y el endpoint CDP de Browserless.
- `app/session_pool.py` implementa un **pool de sesiones persistentes** de
  navegador con TTL configurable y evicción LRU, reutilizables entre llamadas MCP.
- `app/tools/qa.py` implementa **reconexión automática** cuando la sesión remota
  muere a mitad de ejecución, restaurando las cookies de sesión.

### 1.1 Session Pool (`app/session_pool.py`)

Pool de sesiones de navegador reutilizables con TTL configurable y evicción LRU.
La clase `SessionPool` expone `acquire()`/`release()` y mantiene la conexión viva
entre llamadas MCP, identificando cada sesión por `session_id` vía ContextVar.

### 1.2 Deep Agent (`app/agents/deep_agent.py`)

Agente autónomo construido con la librería `deepagents` (`create_deep_agent()`)
que envuelve las 3 tools QA como tools de LangChain y se ejecuta como nodo `deep`
del grafo.

### 1.3 Reconexión automática (`app/tools/qa.py`)

`qa_execute_user_flow` y `qa_audit_url` reconectan automáticamente
(`MAX_RECONNECTS=3`) cuando la sesión remota muere a mitad de ejecución,
capturando y restaurando las cookies de sesión.

---

## 2. Requisitos previos en Windows

- **Docker Desktop** (con WSL2 habilitado) para ejecutar el contenedor Browserless.
- **Python 3.10 o superior** (agregado al `PATH` de Windows).
- **Git** para clonar el repositorio.

---

## 3. Instalación paso a paso (PowerShell)

Abre **Windows PowerShell** y ejecuta:

```powershell
# 1. Clonar el repositorio
git clone <URL-del-repositorio>
cd browserless

# 2. Crear y activar el entorno virtual
python -m venv .venv
.venv\Scripts\Activate.ps1

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Instalar el navegador Chromium de Playwright
playwright install chromium
```

> **Nota:** si la activación del entorno virtual falla por la política de
> ejecución de PowerShell, consulta la sección [Solución de problemas](#10-solución-de-problemas-comunes-en-windows).

---

## 4. Levantar Browserless con Docker

Ejecuta el siguiente comando para levantar el contenedor de Browserless en el
puerto **3000**:

```powershell
docker run -d -p 3000:3000 --name browserless -e "CONCURRENCY=10" ghcr.io/browserless/chromium
```

- **`-p 3000:3000`** — mapea el puerto 3000 del contenedor al puerto 3000 del host.
  Es el puerto que usa la variable `BROWSERBASE_URL` (`ws://localhost:3000`).
- **`-e "CONCURRENCY=10"`** — limita a 10 el número de peticiones concurrentes que
  Browserless procesa a la vez.
- **`--name browserless`** — asigna un nombre fijo al contenedor para gestionarlo
  fácilmente (`docker start browserless`, `docker stop browserless`, `docker logs browserless`).

Verifica que el contenedor esté corriendo:

```powershell
docker ps
```

---

## 5. Configuración

Toda la configuración se realiza mediante **variables de entorno**, que se leen en
tiempo de ejecución desde `app/config.py`. Si existe un archivo `.env` en la raíz
del proyecto, `python-dotenv` lo carga automáticamente.

### 5.1 Tabla de variables de entorno

| Variable | Default | Descripción |
| --- | --- | --- |
| `BROWSERBASE_URL` | `ws://localhost:3000` | URL del navegador remoto Browserless (endpoint CDP). |
| `STAGEHAND_BROWSER` | *(sin default)* | Selecciona el navegador remoto usado por Playwright (`browserless`). |
| `OPENAI_API_KEY` | *(sin default)* | API key de OpenAI. Usada como fallback para LLM y visión. |
| `ANTHROPIC_API_KEY` | *(sin default)* | API key de Anthropic. Usada como fallback de visión si el proveedor es `anthropic`. |
| `VISION_MODEL` | *(sin default)* | Modelo de visión configurado (si se omite, se usa el default del proveedor). |
| `VFA_LLM_PROVIDER` | `openai` | Proveedor LLM por defecto (`openai`, `anthropic`, `ollama`, etc.). |
| `VFA_LLM_MODEL` | `gpt-4o` | Modelo LLM por defecto. |
| `VFA_LLM_API_KEY` | *(sin default)* | API key LLM genérica. Si no se define, se usa `OPENAI_API_KEY`. |
| `VFA_VISION_PROVIDER` | `VFA_LLM_PROVIDER` o `openai` | Proveedor de visión. Si no se define, hereda de `VFA_LLM_PROVIDER` y, en su defecto, `openai`. |
| `VFA_VISION_MODEL` | `VFA_LLM_MODEL` o `gpt-4o` | Modelo de visión. Si no se define, hereda de `VFA_LLM_MODEL` y, en su defecto, `gpt-4o`. |
| `VFA_VISION_API_KEY` | *(sin default)* | API key de visión. Si no se usa, hereda de `VFA_LLM_API_KEY`/`OPENAI_API_KEY`; si el proveedor es `anthropic`, acepta `ANTHROPIC_API_KEY`. |
| `VFA_LLM_REQUESTS_PER_SECOND` | `0` | Peticiones por segundo del rate limiter. `0` desactiva el rate limiter. |
| `VFA_LLM_CHECKS_PER_SECOND` | `10.0` | Frecuencia (en segundos) con la que el rate limiter revisa el cupo. |
| `VFA_SESSION_POOL_ENABLED` | `true` | Activa el pool de sesiones persistentes entre llamadas a tools QA. |
| `VFA_SESSION_POOL_TTL` | `300` | Segundos de inactividad antes de cerrar una sesión. |
| `VFA_SESSION_POOL_MAX_SIZE` | `5` | Máximo de sesiones simultáneas (evicción LRU). |

### 5.2 Ejemplo de archivo `.env`

Crea un archivo `.env` en la raíz del proyecto (se carga automáticamente):

```dotenv
# Navegador remoto
BROWSERBASE_URL=ws://localhost:3000
STAGEHAND_BROWSER=browserless

# LLM
VFA_LLM_PROVIDER=openai
VFA_LLM_MODEL=gpt-4o
OPENAI_API_KEY=tu-api-key-de-openai

# Visión (opcional; si se omite, hereda del LLM)
VFA_VISION_PROVIDER=openai
VFA_VISION_MODEL=gpt-4o

# Rate limiter (opcional)
VFA_LLM_REQUESTS_PER_SECOND=0
VFA_LLM_CHECKS_PER_SECOND=10.0
```

---

## 6. Configuración en Windows PowerShell

Puedes definir las variables de entorno directamente en la sesión de PowerShell
con `$env:`. Los dos comandos originales del proyecto son:

```powershell
$env:STAGEHAND_BROWSER="browserless"
$env:BROWSERBASE_URL="ws://localhost:3000"
```

Variables opcionales de LLM y visión:

```powershell
$env:VFA_LLM_PROVIDER="openai"
$env:VFA_LLM_MODEL="gpt-4o"
$env:OPENAI_API_KEY="tu-api-key"
```

### Alternativas de persistencia

- **`setx` (persistente a nivel de usuario):** define la variable de forma
  permanente para futuras sesiones de PowerShell.

  ```powershell
  setx BROWSERBASE_URL "ws://localhost:3000"
  setx STAGEHAND_BROWSER "browserless"
  ```

- **Archivo `.env`:** la opción recomendada. Crea un archivo `.env` en la raíz del
  proyecto (ver sección 5.2); `python-dotenv` lo carga automáticamente al importar
  `app.config`.

---

## 7. Ejecución del servidor MCP

Con el entorno virtual activado y las variables configuradas, inicia el servidor:

```powershell
python server_mcp.py
```

El servidor usa el **transporte `stdio`** de MCP. Para conectarte desde un cliente
MCP compatible, configura el comando `python server_mcp.py` como servidor MCP de
tipo `stdio` (apuntando al intérprete de tu entorno virtual si es necesario). Una
vez conectado, el servidor expone las **3 tools QA** descritas al inicio.

---

## 8. Ejecución de pruebas

Ejecuta la suite de pruebas existente en `tests/`:

```powershell
pytest tests/
```

O, de forma equivalente:

```powershell
python -m pytest tests/
```

La suite incluye:

- `tests/test_server_mcp.py`
- `tests/test_server_mcp_advanced.py`
- `tests/test_vfa_graph.py`
- `tests/test_vfa_llm.py`
- `tests/test_deep_agent.py`
- `tests/test_session_pool.py`
- `tests/test_qa_reconnect.py`
- `tests/test_vfa_semantic_llm.py`

La suite completa consta de 8 archivos de test, todos pasando.

---

## 9. Solución de problemas comunes en Windows

### 9.1 El puerto 3000 está ocupado

Si el contenedor no arranca porque el puerto 3000 ya está en uso, identifica el
proceso que lo ocupa y deténlo, o cambia el mapeo de puertos:

```powershell
Get-NetTCPConnection -LocalPort 3000
```

Si prefieres usar otro puerto, cambia el mapeo del contenedor y la variable
`BROWSERBASE_URL` en consecuencia (p. ej. `-p 3001:3000` y
`BROWSERBASE_URL=ws://localhost:3001`).

### 9.2 El contenedor no arranca

Verifica que Docker Desktop esté en ejecución y revisa los logs del contenedor:

```powershell
docker logs browserless
```

Si el contenedor quedó en un estado erróneo, elimínalo y vuelve a crearlo:

```powershell
docker rm -f browserless
docker run -d -p 3000:3000 --name browserless -e "CONCURRENCY=10" ghcr.io/browserless/chromium
```

### 9.3 Error de conexión `ws://`

Si Playwright no consigue conectarse al navegador remoto, comprueba que:

1. El contenedor Browserless esté corriendo (`docker ps`).
2. `BROWSERBASE_URL` apunte a `ws://localhost:3000` (o al puerto mapeado).

```powershell
$env:BROWSERBASE_URL="ws://localhost:3000"
```

### 9.4 PowerShell bloquea la activación del entorno virtual

Si `.venv\Scripts\Activate.ps1` falla por la política de ejecución, permite
scripts firmados de forma remota para el usuario actual:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

o ejecuta PowerShell con la política omitida:

```powershell
powershell -ExecutionPolicy Bypass
```