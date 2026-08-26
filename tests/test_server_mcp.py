"""Pruebas unitarias de server_mcp.py (importación y registro de tools)."""

import importlib

import pytest

import server_mcp
from mcp.server.fastmcp import FastMCP


def test_import_sin_errores():
    """El módulo importa sin excepciones (verifica imports y sintaxis)."""
    importlib.reload(server_mcp)


def test_mcp_es_fastmcp():
    """La instancia mcp es de tipo FastMCP."""
    assert isinstance(server_mcp.mcp, FastMCP)


def test_tools_registradas():
    """Las tres tools QA están registradas con sus nombres exactos."""
    tools = server_mcp.mcp._tool_manager._tools
    nombres = set(tools.keys())
    assert {"qa_audit_url", "qa_execute_user_flow", "qa_get_runtime_errors"} <= nombres


def test_browserbase_url_fallback(monkeypatch):
    """BROWSERBASE_URL usa el fallback ws://localhost:3000 sin variable de entorno."""
    monkeypatch.delenv("BROWSERBASE_URL", raising=False)
    importlib.reload(server_mcp)
    assert server_mcp.BROWSERBASE_URL == "ws://localhost:3000"