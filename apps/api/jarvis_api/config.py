from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    database_url: str = "sqlite:///./data/jarvis.db"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices("OLLAMA_BASE_URL", "JARVIS_OLLAMA_BASE_URL"),
    )
    ollama_model: str = Field(
        default="llama3.2:3b",
        validation_alias=AliasChoices("OLLAMA_MODEL", "JARVIS_OLLAMA_MODEL"),
    )
    projects_root: Path = Field(
        default_factory=lambda: Path.home() / "Developer",
        validation_alias=AliasChoices("PROJECTS_ROOT", "JARVIS_PROJECTS_ROOT"),
    )
    conversation_ttl_seconds: int = Field(
        default=1800,
        ge=60,
        le=86400,
        validation_alias=AliasChoices(
            "CONVERSATION_TTL_SECONDS", "JARVIS_CONVERSATION_TTL_SECONDS"
        ),
    )
    conversation_max_turns: int = Field(
        default=12,
        ge=1,
        le=50,
        validation_alias=AliasChoices(
            "CONVERSATION_MAX_TURNS", "JARVIS_CONVERSATION_MAX_TURNS"
        ),
    )
    conversation_max_characters: int = Field(
        default=12000,
        ge=1000,
        le=100000,
        validation_alias=AliasChoices(
            "CONVERSATION_MAX_CHARACTERS", "JARVIS_CONVERSATION_MAX_CHARACTERS"
        ),
    )
    memory_max_user_entries: int = Field(default=50, ge=1, le=500)
    memory_max_project_entries: int = Field(default=25, ge=1, le=250)
    memory_max_characters: int = Field(default=500, ge=50, le=4000)
    memory_max_injected_characters: int = Field(default=2000, ge=100, le=10000)
    run_timeout_seconds: float = Field(default=90, gt=0, le=600)
    tool_timeout_seconds: float = Field(default=15, gt=0, le=120)
    run_terminal_ttl_seconds: int = Field(default=900, ge=30, le=86400)
    run_max_entries: int = Field(default=100, ge=1, le=1000)
    run_max_events: int = Field(default=200, ge=10, le=1000)

    model_config = SettingsConfigDict(env_prefix="JARVIS_", env_file=".env")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
