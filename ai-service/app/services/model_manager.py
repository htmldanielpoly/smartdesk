"""Lifecycle of the local open-weights models (download, load, status).

The service must be useful the moment it starts: model download/load happens
in the background, and until the models are ready every caller transparently
gets the rule-based fallback. Status is reported on /health.

States: disabled -> (unloaded) -> downloading -> loading -> ready | error
"""
import logging
import threading
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state: dict = {
    "status": "disabled" if not settings.local_ai_enabled else "unloaded",
    "detail": None,
}
_chat_model = None
_embed_model = None


def status() -> dict:
    """Current model status, as reported on /health."""
    return {
        "status": _state["status"],
        "detail": _state["detail"],
        "chat_model": settings.chat_model_filename,
        "embed_model": settings.embed_model_filename,
    }


def get_chat_model():
    """The loaded chat model, or None if not (yet) available."""
    return _chat_model


def get_embed_model():
    """The loaded embedding model, or None if not (yet) available."""
    return _embed_model


def _set_state(state: str, detail: str | None = None) -> None:
    _state["status"] = state
    _state["detail"] = detail


def _download(url: str, dest: Path) -> None:
    """Stream a model file to disk (via a .part file so an interrupted
    download is never mistaken for a complete model)."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    logger.info("Downloading %s -> %s", url, dest)
    with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as resp:
        resp.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=1 << 20):
                fh.write(chunk)
    tmp.replace(dest)
    logger.info("Downloaded %s (%.1f MB)", dest.name, dest.stat().st_size / 2**20)


def _ensure_file(url: str, filename: str) -> Path | None:
    models_dir = Path(settings.models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    dest = models_dir / filename
    if dest.exists():
        return dest
    if not settings.auto_download_models:
        logger.warning("Model %s missing and auto-download disabled", filename)
        return None
    _download(url, dest)
    return dest


def prepare() -> None:
    """Download (if needed) and load both models. Blocking; run me in a
    worker thread. Safe to call more than once."""
    global _chat_model, _embed_model

    if not settings.local_ai_enabled:
        _set_state("disabled")
        return

    with _lock:
        if _state["status"] == "ready":
            return
        try:
            _set_state("downloading")
            chat_path = _ensure_file(settings.chat_model_url, settings.chat_model_filename)
            embed_path = _ensure_file(settings.embed_model_url, settings.embed_model_filename)
            if chat_path is None or embed_path is None:
                _set_state("error", "model files missing (auto-download disabled)")
                return

            _set_state("loading")
            # Imported lazily: llama-cpp-python is only needed when local AI
            # actually runs (tests exercise the fallback paths without it).
            from llama_cpp import Llama

            threads = {"n_threads": settings.llm_threads} if settings.llm_threads else {}
            _chat_model = Llama(
                model_path=str(chat_path),
                n_ctx=settings.llm_context_tokens,
                verbose=False,
                **threads,
            )
            _embed_model = Llama(
                model_path=str(embed_path),
                embedding=True,
                n_ctx=512,
                verbose=False,
                **threads,
            )
            _set_state("ready")
            logger.info("Local models loaded and ready")
        except Exception as exc:  # noqa: BLE001 - degrade to fallbacks on any failure
            logger.exception("Failed to prepare local models")
            _set_state("error", str(exc))
