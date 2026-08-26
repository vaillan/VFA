"""Punto de entrada del servidor MCP del Agente Visual & Functional Auditor (VFA).

Crea la instancia FastMCP, registra las tres tools QA definidas en app.tools y
re-exporta los nombres que usan los tests (BROWSERBASE_URL,
_capture_network_errors y _analyze_visual_with_llm) para compatibilidad.
"""

from mcp.server.fastmcp import FastMCP

from app import config
from app.capture import _capture_network_errors
from app.graph import get_compiled_graph
from app.tools import qa_audit_url, qa_execute_user_flow, qa_get_runtime_errors
from app.vision import _analyze_visual_with_llm

# Re-exporta la variable que comprueba test_browserbase_url_fallback.
BROWSERBASE_URL = config.get_browserbase_url()

# Grafo LangGraph compilado al importar el servidor (orquestación VFA).
GRAPH = get_compiled_graph()

mcp = FastMCP("Visual-QA-Browserless-Agent")

# Registro de las 3 tools QA (exactamente 3, sin duplicados).
mcp.tool()(qa_audit_url)
mcp.tool()(qa_execute_user_flow)
mcp.tool()(qa_get_runtime_errors)

if __name__ == "__main__":
    mcp.run(transport="stdio")