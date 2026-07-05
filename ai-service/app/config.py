from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Local AI (open-weights models served in-process via llama.cpp) ---
    # Set LOCAL_AI_ENABLED=false to run purely on rule-based fallbacks.
    local_ai_enabled: bool = True
    models_dir: str = "models"
    # Download missing model files at startup (into models_dir). Disable in
    # air-gapped setups and mount the files into models_dir instead.
    auto_download_models: bool = True

    # Chat model: Qwen2.5 0.5B Instruct, 4-bit quantised (~400 MB). Small
    # enough to run on CPU inside the container.
    chat_model_url: str = (
        "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF"
        "/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"
    )
    chat_model_filename: str = "qwen2.5-0.5b-instruct-q4_k_m.gguf"

    # Embedding model: all-MiniLM-L6-v2, 8-bit quantised (~25 MB). Used for
    # duplicate detection and knowledge-base retrieval.
    embed_model_url: str = (
        "https://huggingface.co/leliuga/all-MiniLM-L6-v2-GGUF"
        "/resolve/main/all-MiniLM-L6-v2.Q8_0.gguf"
    )
    embed_model_filename: str = "all-MiniLM-L6-v2.Q8_0.gguf"

    # Generation settings. Low temperature: we want deterministic, grounded
    # output, not creativity.
    llm_context_tokens: int = 4096
    llm_max_output_tokens: int = 512
    llm_temperature: float = 0.2

    # --- Knowledge-base grounding (anti-hallucination) ---
    # Copilot answers must be grounded in a KB article at least this similar
    # to the ticket (cosine, embedding path); otherwise we refuse to generate
    # and return a safe template instead.
    kb_min_similarity: float = 0.40
    # Jaccard threshold for the lexical retrieval fallback (scores lower than
    # cosine on embeddings, so this is intentionally small).
    kb_lexical_min_similarity: float = 0.10
    kb_top_k: int = 3

    # --- Duplicate detection thresholds ---
    # Cosine similarity threshold for the embedding path.
    duplicate_similarity_threshold: float = 0.55
    # Token-overlap (Jaccard) threshold for the offline fallback. Lexical
    # overlap scores lower than embeddings, so this is intentionally smaller.
    duplicate_fallback_threshold: float = 0.3
    duplicate_max_results: int = 5

    # --- Guardrail limits on inputs handed to the LLM ---
    max_title_chars: int = 200
    max_description_chars: int = 4000
    max_conversation_messages: int = 20
    max_conversation_chars: int = 6000


settings = Settings()
