from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Leave empty to run with rule-based fallbacks (no external calls).
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    # Cosine similarity threshold for the embedding path.
    duplicate_similarity_threshold: float = 0.55
    # Token-overlap (Jaccard) threshold for the offline fallback. Lexical
    # overlap scores lower than embeddings, so this is intentionally smaller.
    duplicate_fallback_threshold: float = 0.3
    duplicate_max_results: int = 5

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_api_key)


settings = Settings()
