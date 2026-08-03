import logging
from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Known dev-default secrets that must never be used in production
_DEV_DEFAULT_SECRETS = {
    "CHANGE-ME-in-production-use-a-real-secret-key-at-least-64-chars",
    "dev-secret-please-change-in-production",
    "changeme",
    "secret",
}


def _find_env_file() -> str:
    """Find .env file in current dir or parent dir."""
    cwd = Path.cwd()
    if (cwd / ".env").exists():
        return str(cwd / ".env")
    if (cwd.parent / ".env").exists():
        return str(cwd.parent / ".env")
    return ".env"


class Settings(BaseSettings):
    """Application configuration settings."""
    
    # Database
    database_url: str = "postgresql://newsuser:newspass@postgres:5432/news_db"
    
    # Kafka
    kafka_bootstrap_servers: str = "kafka:29092"
    
    # Gemini AI
    gemini_api_key: Optional[str] = None
    
    # OpenAI
    openai_api_key: Optional[str] = None
    
    # Google OAuth
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_redirect_uri: str = "http://localhost:3000/auth/callback"
    
    # News API
    news_api_key: Optional[str] = None
    news_api_base_url: str = "https://newsapi.org/v2"
    
    # JWT Authentication — NO default; Pydantic raises if env var is missing
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 hours
    
    # Application
    app_name: str = "AI News Ecosystem"
    debug: bool = False
    frontend_url: str = "http://localhost:3000"
    environment: str = "development"
    dev_login_enabled: bool = False
    # When False (default), articles are summarized ONLY on demand (when a user
    # opens one) — the background reconcile job that pre-summarizes new articles
    # is disabled, so it can't burn the daily Gemini quota before real requests.
    # Enable only if you have generous/paid AI quota and want summaries pre-warmed.
    presummarize_enabled: bool = False

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        """Reject secrets shorter than 32 characters."""
        if len(v) < 32:
            raise ValueError(
                "JWT_SECRET_KEY must be at least 32 characters long. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
            )
        return v
    
    class Config:
        env_file = _find_env_file()
        case_sensitive = False
        # Ignore unrelated keys in .env (e.g. frontend vars) instead of crashing.
        # pydantic-settings v2 forbids unknown .env keys by default.
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
