from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # MongoDB
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "smartdesk_forum"

    # Auth. The forum service issues no tokens of its own: it validates the
    # JWTs signed by the api-service, so jwt_secret must match across services.
    jwt_secret: str = "change-me-in-prod"
    jwt_algorithm: str = "HS256"

    # Pagination
    page_size: int = 20


settings = Settings()
