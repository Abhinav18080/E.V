"""
Centralized app configuration.

Loads from environment variables / .env via pydantic-settings. Every field here
should have a matching entry in .env.example — keep them in sync.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    secret_key: str = "change-me-to-a-random-string"

    # --- LLM ---
    llm_provider: Literal["ollama", "groq", "gemini"] = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    groq_api_key: str | None = None
    gemini_api_key: str | None = None

    # --- Google OAuth / APIs ---
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/callback"
    google_scopes: str = (
        "https://www.googleapis.com/auth/calendar,"
        "https://www.googleapis.com/auth/gmail.send,"
        "https://www.googleapis.com/auth/gmail.readonly"
    )

    @property
    def google_scopes_list(self) -> list[str]:
        return [s.strip() for s in self.google_scopes.split(",") if s.strip()]

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Database ---
    database_url: str = "sqlite:///./dev.db"

    # --- Vector memory ---
    chroma_persist_dir: str = "./data/chroma"

    # --- MCP servers ---
    mcp_calendar_server_url: str = "http://localhost:9001"
    mcp_email_server_url: str = "http://localhost:9002"
    mcp_tasks_server_url: str = "http://localhost:9003"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings singleton. Import and call this rather than instantiating
    Settings() directly, so the whole app shares one parsed config.
    """
    return Settings()