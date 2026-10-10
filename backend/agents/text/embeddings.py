import asyncio
import threading
from typing import Any, Protocol

from backend.database.search_config import SearchSettings


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedProvider:
    """CPU ONNX inference off the event loop, one model per application lifecycle."""

    def __init__(self, config: SearchSettings) -> None:
        self.config = config
        self.model: Any = None
        self.lock = asyncio.Lock()
        self.inference_lock = threading.Lock()
        self.worker: asyncio.Task[list[list[float]]] | None = None

    def _encode(self, texts: list[str]) -> list[list[float]]:
        # A cancelled await cannot stop an ONNX worker. Keep the model serialized even then.
        with self.inference_lock:
            return self._encode_locked(texts)

    def _encode_locked(self, texts: list[str]) -> list[list[float]]:
        from fastembed import TextEmbedding

        if self.model is None:
            self.model = TextEmbedding(
                model_name=self.config.embedding_model,
                cache_dir=self.config.embedding_cache_dir,
                threads=2,
            )
        vectors = [vector.tolist() for vector in self.model.embed(texts, batch_size=32)]
        if any(len(v) != self.config.embedding_dimensions for v in vectors):
            raise ValueError("Embedding dimension differs from configuration")
        return vectors

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts or len(texts) > 128:
            raise ValueError("Embedding batch must contain 1..128 texts")
        async with self.lock:
            if self.worker is not None and not self.worker.done():
                # Cancellation cannot stop native inference: do not queue abandoned workers.
                raise OSError("Embedding inference is still finishing a cancelled request")
            self.worker = asyncio.create_task(asyncio.to_thread(self._encode, texts))
            self.worker.add_done_callback(
                lambda task: task.exception() if not task.cancelled() else None
            )
            return await asyncio.shield(self.worker)
