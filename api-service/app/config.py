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

    # Abuse protection (see app/rate_limit.py and app/middleware.py).
    # General budget per user (or per address when unauthenticated) per window.
    rate_limit_requests: int = 30
    # Stricter budget for content creation: comments, forum posts, messages.
    rate_limit_writes: int = 20
    rate_limit_window_seconds: int = 60
    # Take the client address from X-Forwarded-For. Only behind a reverse
    # proxy you control (Caddy/nginx); otherwise the header can be spoofed.
    trust_proxy_headers: bool = False
    # Requests with a bigger body are refused with 413 before being read.
    max_request_body_bytes: int = 1_048_576  # 1 MiB
    # Refuse to start with the public default JWT secret (set in production).
    require_strong_secret: bool = False


settings = Settings()
