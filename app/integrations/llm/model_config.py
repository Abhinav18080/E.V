"""
Per-provider model configuration and per-node generation settings.

Node-specific settings live here rather than in each node file so tuning
temperature/etc. doesn't require touching node logic — e.g. planner wants
deterministic tool routing, responder benefits from a little variance so
replies don't feel robotic.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeGenerationConfig:
    temperature: float


PLANNER_CONFIG = NodeGenerationConfig(temperature=0.0)
RESPONDER_CONFIG = NodeGenerationConfig(temperature=0.3)
SUMMARIZER_CONFIG = NodeGenerationConfig(temperature=0.0)

# Free-tier hosted fallback model names, used only when LLM_PROVIDER is set
# to "groq" or "gemini" instead of the default "ollama". Providers
# periodically retire/rename free-tier models — check their docs if a
# hosted call starts failing with a "model not found" error.
GROQ_MODEL = "llama-3.1-8b-instant"
GEMINI_MODEL = "gemini-1.5-flash"