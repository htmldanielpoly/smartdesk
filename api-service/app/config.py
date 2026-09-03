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

    # Long-term memory: when a new ticket repeats an already-resolved one
    # (similarity decided by the AI service, cosine >= 0.95 by default) the AI
    # answers it with the stored resolution and takes it out of the agent
    # queue. Disable to always route every ticket to a human.
    auto_resolve_enabled: bool = True
    # How many recently resolved tickets (with a stored resolution) form the
    # memory that a new ticket is compared against.
    auto_resolve_candidate_limit: int = 300
    # RESOLVED (default) lets the customer confirm or reopen; CLOSED closes
    # the ticket outright (the customer can still reopen it).
    auto_resolve_close_ticket: bool = False

    # Forum service (internal), proxied through this gateway.
    forum_service_url: str = "http://localhost:8001"
    forum_timeout_seconds: float = 10.0

    # Rate limiting (simple in-memory limiter)
    rate_limit_requests: int = 30
    rate_limit_window_seconds: int = 60


settings = Settings()
