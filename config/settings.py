"""Centralized, validated configuration for the Memory-First CI Copilot."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration, loaded from environment / .env, fully typed."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(default="meta-llama/llama-3.3-70b-instruct:free", alias="OPENROUTER_MODEL")
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL")

    # Search
    tavily_api_key: str | None = Field(default=None, alias="TAVILY_API_KEY")
    serper_api_key: str | None = Field(default=None, alias="SERPER_API_KEY")
    use_duckduckgo: bool = Field(default=True, alias="USE_DUCKDUCKGO")

    @property
    def _tavily_key(self) -> str | None:
        k = self.tavily_api_key
        if not k or k.startswith("tvly-your") or k == "tvly-your-key":
            return None
        return k

    @property
    def _serper_key(self) -> str | None:
        k = self.serper_api_key
        if not k or "your" in k.lower():
            return None
        return k

    # Execution / governance limits
    max_sources: int = Field(default=15, alias="MAX_SOURCES")
    max_steps: int = Field(default=20, alias="MAX_STEPS")
    max_retries_per_tool_call: int = Field(default=2, alias="MAX_RETRIES_PER_TOOL_CALL")
    search_timeout_seconds: int = Field(default=12, alias="SEARCH_TIMEOUT_SECONDS")

    # LLM call retries / timeout
    llm_max_retries: int = Field(default=6, alias="LLM_MAX_RETRIES")
    llm_timeout: int = Field(default=120, alias="LLM_TIMEOUT")

    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Auth (preserved from original)
    auth_username: str = Field(default="admin", alias="AUTH_USERNAME")
    auth_name: str = Field(default="Administrator", alias="AUTH_NAME")
    auth_email: str = Field(default="admin@ci-briefing.local", alias="AUTH_EMAIL")
    auth_password_hash: str = Field(
        default="$2b$12$KIXVJbTkLdGSwxvjH5XVxuY8yN/2bX0G.WUJHq3eTiYg6ZxjDlLsC",
        alias="AUTH_PASSWORD_HASH",
    )
    auth_cookie_name: str = Field(default="ci_briefing_auth", alias="AUTH_COOKIE_NAME")
    auth_cookie_key: str = Field(default="ci_briefing_super_secret_key_change_me", alias="AUTH_COOKIE_KEY")
    auth_cookie_expiry_days: int = Field(default=7, alias="AUTH_COOKIE_EXPIRY_DAYS")

    # ── FastAPI ──────────────────────────────────────────────────────────────
    fastapi_host: str = Field(default="0.0.0.0", alias="FASTAPI_HOST")
    fastapi_port: int = Field(default=8000, alias="FASTAPI_PORT")
    cors_origins: str = Field(default="http://localhost:5173", alias="CORS_ORIGINS")

    # ── Hindsight Memory ─────────────────────────────────────────────────────
    hindsight_memory_path: str = Field(default="data/memory", alias="HINDSIGHT_MEMORY_PATH")

    @property
    def has_search_provider(self) -> bool:
        return bool(self._tavily_key or self._serper_key or self.use_duckduckgo)

    @property
    def has_llm_provider(self) -> bool:
        return bool(self.openai_api_key or self.openrouter_api_key)

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]


settings = Settings()
