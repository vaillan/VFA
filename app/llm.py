"""Fabrica de modelos LLM agnostica al proveedor basada en LangChain.

Centraliza la creacion de modelos via init_chat_model (proveedores remotos) y
ChatOllama (proveedor local), con un InMemoryRateLimiter opcional configurado
desde VFA_LLM_REQUESTS_PER_SECOND / VFA_LLM_CHECKS_PER_SECOND.

Las variables de entorno se leen EN TIEMPO DE LLAMADA (consistente con
app/config.py), pero la instancia devuelta por get_vision_llm queda cacheada
con @lru_cache. Para tests, get_vision_llm.cache_clear() permite invalidar la
cache y forzar la relectura de las variables de entorno.
"""

from functools import lru_cache

from langchain.chat_models import init_chat_model
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_ollama import ChatOllama

from app import config

provider_map = {
    "google": "google_genai",
    "openai": "openai",
    "anthropic": "anthropic",
    "open-router": "openrouter",
    "local": "ollama",
    "azure": "azure_openai",
    "aws-bedrock": "bedrock_converse",
    "huggingface": "huggingface",
}


def _create_llm(provider: str, model_name: str, api_key: str, temperature: float = 0.0):
    """Crea una instancia de modelo LLM para el proveedor indicado.

    Args:
        provider: clave de proveedor (debe existir en provider_map).
        model_name: nombre del modelo a instanciar.
        api_key: API key del proveedor (ignorada para el proveedor 'local').
        temperature: temperatura de muestreo del modelo.

    Returns:
        Instancia de chat model de LangChain.

    Raises:
        ValueError: si el proveedor no esta soportado o si init_chat_model
            falla por dependencias no instaladas (ImportError).
    """
    if provider not in provider_map:
        raise ValueError(
            f"Unsupported provider: {provider}. Supported providers: {', '.join(provider_map)}"
        )

    rate_limiter = None
    rps, checks = config.get_rate_limiter_settings()
    if rps > 0:
        rate_limiter = InMemoryRateLimiter(
            requests_per_second=rps,
            check_every_n_seconds=checks,
        )

    if provider == "local":
        return ChatOllama(
            model=model_name,
            temperature=temperature,
            rate_limiter=rate_limiter,
        )

    try:
        return init_chat_model(
            model=model_name,
            model_provider=provider_map[provider],
            temperature=temperature,
            api_key=api_key,
            max_retries=5,
            timeout=10000,
            rate_limiter=rate_limiter,
        )
    except ImportError as e:
        raise ValueError(
            f"Failed to initialize model '{model_name}' for provider '{provider}': {e}"
        ) from e


@lru_cache(maxsize=4)
def get_vision_llm(temperature: float = 0.0):
    """Retorna (y cachea) el modelo LLM de vision configurado.

    Lee el proveedor, modelo y API key de vision desde las variables de entorno
    en tiempo de llamada (via vfa.config) y delega en _create_llm. La instancia
    queda cacheada; usa get_vision_llm.cache_clear() para invalidarla (util en
    tests).
    """
    provider = config.get_vision_provider()
    model = config.get_vision_model_name()
    api_key = config.get_vision_api_key(provider)
    return _create_llm(provider, model, api_key, temperature)