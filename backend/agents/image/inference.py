"""Image assessment and candidate proposals, never autonomous identity confirmation."""

import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid5

import httpx
import numpy as np
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from backend.agents.image.model import XceptionModel
from backend.agents.image.preprocessing import validate_image
from backend.agents.image.quality import assess_quality
from backend.agents.image.ranking import rank
from backend.agents.image.retrieval import ImageVectorStore
from backend.agents.text.resolver import normalize
from backend.agents.text.search import HybridNameSearch
from backend.config.settings import Settings
from backend.contracts.agents import CandidatePlant, ImageAgentResult, ImageReference
from backend.contracts.evidence import Evidence, Modality, Provenance
from backend.database.postgres.client import PostgresClient


class ImageInference:
    def __init__(
        self,
        settings: Settings,
        model: XceptionModel,
        vectors: ImageVectorStore,
        postgres: PostgresClient,
        catalog: HybridNameSearch,
    ) -> None:
        self.settings, self.model, self.vectors = settings, model, vectors
        self.postgres, self.catalog = postgres, catalog
        self.dataset_id = ""

    async def open(self) -> None:
        manifest = json.loads(
            await asyncio.to_thread(
                Path(self.settings.image_manifest_path or "").read_text, encoding="utf-8"
            )
        )
        if (
            manifest["model_id"] != self.model.model_id
            or manifest["dimensions"] != 2048
            or manifest["collection"] != self.vectors.collection
        ):
            raise ValueError("Image index/model fingerprint mismatch; rebuild explicitly")
        self.dataset_id = manifest["dataset_id"]
        await self.vectors.validate()
        if await self.vectors.count(self.model.model_id, self.dataset_id) != manifest["count"]:
            raise ValueError("Image index is incomplete")

    async def infer(self, image: ImageReference, session_id: UUID) -> ImageAgentResult:
        row = await self.postgres.single(
            "SELECT content FROM chat_image WHERE session_id=$1 AND image_id=$2",
            session_id,
            image.image_id,
        )
        if row is None:
            raise ValueError("Image is unavailable in this session")
        content = bytes(row["content"])
        await validate_image(
            content,
            image.metadata.mime_type,
            self.settings.max_image_bytes,
            self.settings.max_image_pixels,
        )
        quality = await asyncio.to_thread(assess_quality, content)
        result = ImageAgentResult(
            quality=quality,
            placeholder=False,
            strategy=self.settings.image_strategy,
            model_id=self.model.model_id,
        )
        if quality.usable is False:
            result.clarification_question = (
                "Please upload a clearer, well-lit close-up of one leaf."
            )
            return result
        probabilities, vector = await self.model.infer(content)
        hits = []
        try:
            hits = await self.vectors.search(vector.tolist(), self.model.model_id, self.dataset_id)
        except (httpx.HTTPError, ResponseHandlingException, UnexpectedResponse, TimeoutError):
            result.strategy = "cnn_fallback"
            result.limitations.append(
                "Image retrieval unavailable; CNN-only suggestions need confirmation"
            )
        max_similarity = max((float(h["similarity"]) for h in hits), default=0.0)
        result.limitations.extend(
            [
                "Model covers 40 leaf classes; other species and parts are unsupported",
                "Uncalibrated scores; independent accuracy and non-plant rejection are unverified",
            ]
        )
        if hits and max_similarity < self.settings.image_min_similarity:
            result.clarification_question = (
                "No supported leaf reference. Please upload a clear leaf or provide its name."
            )
            result.quality.issues.append("Insufficient similarity to supported leaf images")
            return result
        # Positive similarity is supporting evidence, not proof of plantness or leaf anatomy.
        result.quality.is_plant = None
        strategy = "cnn" if result.strategy == "cnn_fallback" else self.settings.image_strategy
        fused = rank(probabilities, self.model.labels, hits, strategy)
        _, names = await self.catalog.catalog()
        mapped: dict[str, dict[str, str]] = {}
        for record in names:
            mapped.setdefault(normalize(record.name), {})[str(record.plant_id)] = record.plant_name
        for index in np.argsort(-fused)[:5]:
            label = self.model.labels[int(index)]
            targets = mapped.get(normalize(label), {})
            similarity = max(
                (float(h["similarity"]) for h in hits if h.get("label") == label), default=0.0
            )
            result.scores.append(
                {
                    "label": label,
                    "cnn_score": float(probabilities[index]),
                    "retrieval_similarity": similarity,
                    "ranking_score": float(fused[index]),
                    "graph_mapped": len(targets) == 1,
                }
            )
            if len(targets) != 1:
                result.limitations.append(
                    f"{label}: no unique exact name/alias link in the knowledge graph"
                )
                continue
            if float(fused[index]) < max(0.02, float(fused.max()) * 0.1):
                continue
            plant_id, plant_name = next(iter(targets.items()))
            provenance = Provenance(
                source_id=str(image.image_id),
                source_type="image_inference",
                reference=f"Xception leaf candidate: {label}; requires user confirmation",
                provider_version=self.model.model_id,
            )
            candidate = CandidatePlant(
                plant_id=plant_id,
                label=plant_name,
                confidence=min(0.79, float(fused[index])),
                match_method="image_" + (result.strategy or self.settings.image_strategy),
                provenance=[provenance],
            )
            result.candidates.append(candidate)
            result.evidence.append(
                Evidence(
                    evidence_id=uuid5(image.image_id, self.model.model_id + plant_id),
                    modality=Modality.IMAGE,
                    claim=f"Unconfirmed visual candidate: {plant_name}",
                    confidence=candidate.confidence,
                    provenance=provenance,
                    supports=[plant_id],
                )
            )
        result.alternatives = result.candidates[1:]
        result.reference_ids = [str(h["point_id"]) for h in hits[:10]]
        result.clarification_question = (
            "The image suggests these plants. Please confirm one candidate or provide its name."
            if result.candidates
            else "No supported graph-linked plant was identified. Please provide its name."
        )
        return result
