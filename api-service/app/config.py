from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # MongoDB
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "smartdesk"

    # Auth
    jwt_secret: str = "change-me-in-prod"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Bootstrap admin, created at startup when no ADMIN exists yet (solves
    # the first-admin chicken-and-egg: self-registration only creates USERs).
    # Leave empty to skip.
    admin_email: str = ""
    admin_password: str = ""

    # AI service (internal). Local LLM inference on CPU can take tens of
    # seconds; callers must never block the core ticketing flow on it.
    ai_service_url: str = "http://localhost:8000"
    ai_timeout_seconds: float = 60.0

    # Forum service (internal), proxied through this gateway.
    forum_service_url: str = "http://localhost:8001"
    forum_timeout_seconds: float = 10.0

    # Rate limiting (simple in-memory limiter)
    rate_limit_requests: int = 30
    rate_limit_window_seconds: int = 60


settings = Settings()
