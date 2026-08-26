"""Configuracion central del agente VFA.

Unica fuente de verdad para las variables de entorno del proyecto. Expone
funciones getter (no constantes) para que la lectura se realice en tiempo de
llamada: esto permite que un reload de server_mcp re-lea BROWSERBASE_URL y que
el analisis visual lea las API keys tras un monkeypatch.delenv en los tests.
"""

import os
from typing import Optional

from dotenv import load_dotenv

# Cargar variables de entorno desde .env (si existe).
load_dotenv()


def get_browserbase_url() -> str:
    """Retorna la URL del navegador Browserless, con fallback local."""
    return os.getenv("BROWSERBASE_URL", "ws://localhost:3000")


def get_openai_key() -> Optional[str]:
    """Retorna la API key de OpenAI (o None si no esta configurada)."""
    return os.getenv("OPENAI_API_KEY")


def get_anthropic_key() -> Optional[str]:
    """Retorna la API key de Anthropic (o None si no esta configurada)."""
    return os.getenv("ANTHROPIC_API_KEY")


def get_vision_model() -> Optional[str]:
    """Retorna el modelo de vision configurado (o None para usar el default)."""
    return os.getenv("VISION_MODEL")


def get_llm_provider() -> str:
    """Retorna el proveedor LLM por defecto (VFA_LLM_PROVIDER, fallback 'openai')."""
    return os.getenv("VFA_LLM_PROVIDER", "openai")


def get_llm_model() -> str:
    """Retorna el modelo LLM por defecto (VFA_LLM_MODEL, fallback 'gpt-4o')."""
    return os.getenv("VFA_LLM_MODEL", "gpt-4o")


def get_llm_api_key() -> Optional[str]:
    """Retorna la API key LLM generica (VFA_LLM_API_KEY o OPENAI_API_KEY)."""
    return os.getenv("VFA_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")


def get_vision_provider() -> str:
    """Retorna el proveedor de vision (VFA_VISION_PROVIDER o VFA_LLM_PROVIDER o 'openai')."""
    return os.getenv("VFA_VISION_PROVIDER") or os.getenv("VFA_LLM_PROVIDER") or "openai"


def get_vision_model_name() -> str:
    """Retorna el modelo de vision (VFA_VISION_MODEL o VFA_LLM_MODEL o 'gpt-4o')."""
    return os.getenv("VFA_VISION_MODEL") or os.getenv("VFA_LLM_MODEL") or "gpt-4o"


def get_vision_api_key(provider: str) -> Optional[str]:
    """Retorna la API key de vision (VFA_VISION_API_KEY o VFA_LLM_API_KEY o OPENAI_API_KEY).

    Si el proveedor es 'anthropic' y aun no hay key, acepta ANTHROPIC_API_KEY.
    """
    key = (
        os.getenv("VFA_VISION_API_KEY")
        or os.getenv("VFA_LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    if not key and provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY")
    return key


def get_rate_limiter_settings() -> tuple[float, float]:
    """Retorna (requests_per_second, check_every_n_seconds) para el rate limiter.

    Lee VFA_LLM_REQUESTS_PER_SECOND (default '0', desactiva el limiter) y
    VFA_LLM_CHECKS_PER_SECOND (default '10.0'), ambos parseados a float.
    """
    rps = float(os.getenv("VFA_LLM_REQUESTS_PER_SECOND", "0"))
    checks = float(os.getenv("VFA_LLM_CHECKS_PER_SECOND", "10.0"))
    return rps, checks