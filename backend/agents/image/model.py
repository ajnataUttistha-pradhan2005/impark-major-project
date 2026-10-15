"""One shared Xception forward pass produces classification and retrieval features."""

import asyncio
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageOps

FloatArray = NDArray[np.float32]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class XceptionModel:
    dimensions = 2048

    def __init__(self, model_path: str, classes_path: str, threads: int = 4) -> None:
        self.path, self.classes_path = Path(model_path), Path(classes_path)
        self.threads = threads
        self.labels: list[str] = []
        self.model_id = ""
        self._model: Any = None
        self.gate = asyncio.Lock()

    def load(self) -> None:
        import tensorflow as tf  # type: ignore[import-untyped]

        mapping = json.loads(self.classes_path.read_text(encoding="utf-8"))
        if (
            not isinstance(mapping, dict)
            or not mapping
            or sorted(mapping.values()) != list(range(len(mapping)))
        ):
            raise ValueError("Class mapping must contain contiguous unique output indices")
        self.labels = sorted(mapping, key=lambda key: int(mapping[key]))
        # Native Windows TF has no current CUDA support. Leave the 4GB GPU to Ollama.
        try:
            tf.config.set_visible_devices([], "GPU")
            tf.config.threading.set_intra_op_parallelism_threads(self.threads)
            tf.config.threading.set_inter_op_parallelism_threads(1)
        except RuntimeError:
            pass  # TensorFlow was already initialized; never reset the process runtime.
        model = tf.keras.models.load_model(self.path, compile=False, safe_mode=True)
        if tuple(model.input_shape[1:]) != (300, 400, 3) or model.output_shape[-1] != len(
            self.labels
        ):
            raise ValueError("CNN input/output does not match supplied artifact contract")
        pooled = model.get_layer("global_average_pooling2d").output
        if pooled.shape[-1] != self.dimensions:
            raise ValueError("Unexpected feature dimensions")
        self._model = tf.keras.Model(model.input, [model.output, pooled])
        self.model_id = hashlib.sha256(
            (
                digest(self.path) + digest(self.classes_path) + "rgb-nearest-400x300-minus1plus1-v1"
            ).encode()
        ).hexdigest()

    @staticmethod
    def pixels(content: bytes) -> FloatArray:
        with Image.open(io.BytesIO(content)) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
            return (
                np.asarray(image.resize((400, 300), Image.Resampling.NEAREST), dtype=np.float32)
                / 127.5
                - 1
            )

    def batch(self, contents: list[bytes]) -> tuple[FloatArray, FloatArray]:
        if self._model is None:
            raise RuntimeError("Image model is not loaded")
        if not 1 <= len(contents) <= 16:
            raise ValueError("Inference batch must contain 1..16 images")
        probability, vector = self._model(
            np.stack([self.pixels(c) for c in contents]), training=False
        )
        probabilities = np.asarray(probability, dtype=np.float32)
        vectors = np.asarray(vector, dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if (
            not np.isfinite(probabilities).all()
            or not np.isfinite(vectors).all()
            or np.any(norms <= 0)
        ):
            raise ValueError("Non-finite or empty model output")
        return probabilities, vectors / norms

    async def infer(self, content: bytes) -> tuple[FloatArray, FloatArray]:
        async with self.gate:
            task = asyncio.create_task(asyncio.to_thread(self.batch, [content]))
            try:
                probabilities, vectors = await asyncio.shield(task)
            except asyncio.CancelledError:
                # Do not release the inference slot while the native worker is still running.
                await asyncio.shield(task)
                raise
            return probabilities[0], vectors[0]
