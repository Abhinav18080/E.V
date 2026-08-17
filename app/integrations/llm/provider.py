"""
LLM provider abstraction.

Nodes call get_chat_model(some_config) instead of constructing a specific
LangChain chat model directly, so switching providers is a one-line env var
change (LLM_PROVIDER=groq) rather than a code change in every node.

Only Ollama's dependency (langchain-ollama) is a hard requirement — Groq and
Gemini support live behind the optional "hosted-llm" extra
(`pip install -e ".[hosted-llm]"`) since the free/local stack doesn't need
them. Selecting LLM_PROVIDER=groq or =gemini without that extra installed
raises a clear error rather than a confusing ImportError deep in LangChain.
"""

from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from app.config import get_settings
from app.integrations.llm.model_config import GEMINI_MODEL, GROQ_MODEL, NodeGenerationConfig


@lru_cache
def _ollama_model(temperature: float) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    settings = get_settings()
    return ChatOllama(model=settings.ollama_model, base_url=settings.ollama_base_url, temperature=temperature)


@lru_cache
def _groq_model(temperature: float) -> BaseChatModel:
    try:
        from langchain_groq import ChatGroq
    except ImportError as exc:
        raise RuntimeError(
            "LLM_PROVIDER=groq requires the 'hosted-llm' extra: "
            "pip install -e '.[hosted-llm]'"
        ) from exc

    settings = get_settings()
    if not settings.groq_api_key:
        raise RuntimeError("LLM_PROVIDER=groq requires GROQ_API_KEY to be set")
    return ChatGroq(model=GROQ_MODEL, api_key=settings.groq_api_key, temperature=temperature)


@lru_cache
def _gemini_model(temperature: float) -> BaseChatModel:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:
        raise RuntimeError(
            "LLM_PROVIDER=gemini requires the 'hosted-llm' extra: "
            "pip install -e '.[hosted-llm]'"
        ) from exc

    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("LLM_PROVIDER=gemini requires GEMINI_API_KEY to be set")
    return ChatGoogleGenerativeAI(
        model=GEMINI_MODEL, google_api_key=settings.gemini_api_key, temperature=temperature
    )


def get_chat_model(config: NodeGenerationConfig) -> BaseChatModel:
    """
    Returns a configured chat model for the currently selected provider
    (settings.llm_provider). Pass a NodeGenerationConfig from model_config.py
    so each node gets its own temperature regardless of which provider is
    active.
    """
    settings = get_settings()
    if settings.llm_provider == "ollama":
        return _ollama_model(config.temperature)
    if settings.llm_provider == "groq":
        return _groq_model(config.temperature)
    if settings.llm_provider == "gemini":
        return _gemini_model(config.temperature)
    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider}")