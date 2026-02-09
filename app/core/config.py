from pydantic_settings import BaseSettings
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    """Application configuration settings."""
    
    # Database
    database_url: str = "postgresql://newsuser:newspass@postgres:5432/news_db"
    
    # Kafka
    kafka_bootstrap_servers: str = "kafka:29092"
    
    # Gemini AI
    gemini_api_key: Optional[str] = None
    
    # Google OAuth
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_redirect_uri: str = "http://localhost:3000/auth/callback"
    
    # News API
    news_api_key: Optional[str] = None
    news_api_base_url: str = "https://newsapi.org/v2"
    
    # JWT Authentication
    jwt_secret_key: str = "supersecretkey-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 hours
    
    # Application
    app_name: str = "AI News Ecosystem"
    debug: bool = False
    frontend_url: str = "http://localhost:3000"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
