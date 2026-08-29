# VFA — Visual & Functional Auditor

VFA (Visual & Functional Auditor) es un servidor MCP construido con FastMCP que audita aplicaciones web usando el navegador remoto Browserless (Docker) via CDP con Playwright y analisis LLM multimodal. Expone 3 tools QA: `qa_audit_url` (audita una URL y reporta errores de consola, excepciones JS y fallos HTTP), `qa_execute_user_flow` (ejecuta un flujo de usuario en lenguaje natural) y `qa_get_runtime_errors` (recupera los errores de ejecucion capturados).

## 1. Arquitectura general

```mermaid
flowchart TB
    Client["🌐 Cliente MCP · stdio"] -->|"stdio"| MCP["⚡ FastMCP · server_mcp.py"]

    MCP --> T1["📋 qa_audit_url\nAudita URL completa"]
    MCP --> T2["▶️ qa_execute_user_flow\nEjecuta pasos de usuario"]
    MCP --> T3["🔍 qa_get_runtime_errors\nRecupera errores capturados"]

    T1 & T2 & T3 -->|"compilan y ejecutan el grafo"| Grafo

    subgraph Grafo["📊 Grafo LangGraph — app/graph/"]
        S((START)) --> Browser["🌐 browser_node\nPlaywright CDP → Browserless\no Chromium local visible"]
        Browser --> Deep["🧠 deep_node\nDeep Agent · envuelve las 3 Tools QA"]
        Deep --> Router{"🔀 route_after_browser"}
        Router -->|"Con steps"| Semantic["💬 semantic_node\nResolución semántica\n① regex NLP\n② accessibility snapshot\n③ LLM fallback"]
        Router -->|"Sin steps"| Vision["👁️ vision_node\nAnálisis visual LLM"]
        Vision --> Semantic
        Semantic --> E((END))
    end

    subgraph toolsQA["🔧 tools QA — NLP Parser · parser.py"]
        direction LR
        NLP["🗣️ 22+ regex multilingües\nES · EN → acciones"]
        PW["🎭 Playwright Locators\nget_by_text · get_by_role · get_by_label · locator()"]
        NLP --> PW
    end

    subgraph Infra["🏗️ Infraestructura"]
        direction LR
        Pool["🔄 Session Pool\nTTL + Evicción LRU"]
        BR["🐳 Browserless\nDocker · Puerto 3000"]
        LLM["🤖 LLM Providers\nOpenAI · Anthropic"]
    end

    Browser --> Pool
    Pool --> BR
    Semantic --> LLM
    Vision --> LLM
    Semantic --> toolsQA
```

- **Config:** `app/config.py` lee las variables de entorno con carga automatica desde `.env` vía `python-dotenv`.
- **Grafo LangGraph** (`app/graph/`): `state.py` define el estado tipado `VFAState`; `builder.py` expone `build_graph()`/`get_compiled_graph()` ensamblando el `StateGraph`; los nodos async `browser_node`, `deep_node`, `vision_node`, `semantic_node` y el router `route_after_browser` viven en `app/agents/` (browser_agent.py, deep_agent.py, vision_agent.py, semantic_agent.py), con re-exports de compatibilidad en `app/graph/nodes.py`. Flujo: START → browser → deep → condicional (semantic si hay steps, vision si no) → vision → semantic → END. `server_mcp.py` compila y usa el grafo; la API publica de las 3 tools MCP no cambia.
- **Session Pool** (`app/session_pool.py`): pool de sesiones de navegador reutilizables entre llamadas MCP, con TTL configurable y eviccion LRU; la clase `SessionPool` expone `acquire()`/`release()` e identifica cada sesion por `session_id` vía ContextVar. La conexion al navegador remoto se realiza en `app/browser.py` (Playwright + CDP Browserless; modo local visible si `HEADLESS=false`).
- **Deep Agent** (`app/agents/deep_agent.py`): agente autónomo de `deepagents` (`create_deep_agent()`) que envuelve las 3 tools QA como tools de LangChain y se ejecuta como nodo `deep` del grafo.
- **Reconexion automatica** (`app/tools/qa.py`): `qa_audit_url` y `qa_execute_user_flow` reconectan automáticamente (MAX_RECONNECTS=3) cuando la sesion remota muere a mitad de ejecucion, capturando y restaurando las cookies de sesion.
- **Capa NLP → Playwright** (`app/tools/parser.py` → `app/tools/qa.py`): 22+ patrones regex multilingues (ES/EN) convierten lenguaje natural en acciones estructuradas, resueltas con locators nativos de Playwright (`get_by_text`, `get_by_role`, `get_by_label`, `locator()`). `app/semantic.py` implementa el fallback de 3 capas: regex NLP → snapshot de accesibilidad → LLM multimodal. `requirements.txt` incluye `langgraph>=0.2` y ya no incluye `crewai`.

## 2. Requisitos previos (Windows)

- Docker Desktop (con WSL2 habilitado) para Browserless.
- Python 3.10 o superior (agregado al PATH).
- Git.

## 3. Instalación (PowerShell)

```powershell
# 1. Clonar el repositorio
git clone <URL-del-repositorio>
cd browserless

# 2. Crear y activar el entorno virtual
python -m venv .venv
.venv\Scripts\Activate.ps1

# 3. Instalar dependencias
pip install -r requirements.txt
```

> Si la activacion falla por la politica de ejecucion de PowerShell, consulta la seccion [Solución de problemas](#8-solución-de-problemas-comunes-en-windows).

## 4. Levantar Browserless con Docker

```powershell
docker run -d -p 3000:3000 --name browserless -e "CONCURRENCY=10" ghcr.io/browserless/chromium
```

- `-p 3000:3000` — mapea el puerto 3000 usado por `BROWSERBASE_URL` (`ws://localhost:3000`).
- `-e "CONCURRENCY=10"` — limita a 10 las peticiones concurrentes.
- `--name browserless` — nombre fijo para gestionarlo (`docker start/stop/logs browserless`). Verificar con `docker ps`.

## 5. Configuración

Variables de entorno leidas en tiempo de ejecucion por `app/config.py`; un archivo `.env` en la raiz se carga automáticamente via `python-dotenv`.

### 5.1 Variables de entorno

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
| `NAVIGATION_WAIT_UNTIL` | `load` | Estrategia de espera de Playwright para navegación (`load`, `domcontentloaded`, `networkidle`, `commit`). Configurable vía variable de entorno. |

### 5.2 Ejemplo de archivo `.env`

```dotenv
# Navegador remoto
BROWSERBASE_URL=ws://localhost:3000
STAGEHAND_BROWSER=browserless

# LLM
VFA_LLM_PROVIDER=openai
VFA_LLM_MODEL=gpt-4o
OPENAI_API_KEY=tu-api-key-de-openai

# Visión (opcional; hereda del LLM si se omite)
VFA_VISION_PROVIDER=openai
VFA_VISION_MODEL=gpt-4o

# Rate limiter (opcional)
VFA_LLM_REQUESTS_PER_SECOND=0
VFA_LLM_CHECKS_PER_SECOND=10.0
```

### 5.3 Variables en PowerShell

```powershell
$env:STAGEHAND_BROWSER="browserless"
$env:BROWSERBASE_URL="ws://localhost:3000"
$env:VFA_LLM_PROVIDER="openai"
$env:VFA_LLM_MODEL="gpt-4o"
$env:OPENAI_API_KEY="tu-api-key"
```

Persistencia: `setx BROWSERBASE_URL "ws://localhost:3000"` y `setx STAGEHAND_BROWSER "browserless"` (permanente a nivel de usuario), o el archivo `.env` (recomendado).

## 6. Ejecución del servidor MCP

```powershell
python server_mcp.py
```

Servidor MCP con transporte `stdio`: configuralo como servidor MCP tipo stdio en tu cliente (apuntando al interprete del venv si es necesario). Una vez conectado, expone las 3 tools QA descritas al inicio.

## 7. Ejecución de pruebas

```powershell
pytest tests/
```

- `tests/test_server_mcp.py`
- `tests/test_server_mcp_advanced.py`
- `tests/test_vfa_graph.py`
- `tests/test_vfa_llm.py`
- `tests/test_deep_agent.py`
- `tests/test_session_pool.py`
- `tests/test_qa_reconnect.py`
- `tests/test_vfa_semantic_llm.py`

## 8. Solución de problemas comunes (Windows)

**Puerto 3000 ocupado:**

```powershell
Get-NetTCPConnection -LocalPort 3000
```

O cambia el mapeo (p. ej. `-p 3001:3000`) y `BROWSERBASE_URL=ws://localhost:3001`.

**El contenedor no arranca:** verifica Docker Desktop; revisa logs o recrea el contenedor:

```powershell
docker logs browserless

docker rm -f browserless
docker run -d -p 3000:3000 --name browserless -e "CONCURRENCY=10" ghcr.io/browserless/chromium
```

**Error de conexión `ws://`:** comprueba `docker ps` y que `BROWSERBASE_URL` apunte al puerto mapeado:

```powershell
$env:BROWSERBASE_URL="ws://localhost:3000"
```

**PowerShell bloquea la activación del venv:**

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

O ejecuta con la politica omitida: `powershell -ExecutionPolicy Bypass`.