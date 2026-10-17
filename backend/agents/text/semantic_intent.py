"""Fast semantic topic matching for paraphrases outside the deterministic parser."""

import asyncio
import math

from backend.agents.text.embeddings import EmbeddingProvider
from backend.agents.text.intent_model import IntentModel, IntentSuggestion
from backend.contracts.agents import QueryType

EXAMPLES: dict[QueryType, tuple[str, ...]] = {
    QueryType.GET_PLANT_DETAILS: (
        "Give me an overview of this plant",
        "What is this plant and what is its conservation status",
        "What are its common names and basic botanical details",
    ),
    QueryType.GET_PLANT_PARTS: (
        "Which parts of this plant are recorded",
        "What sections of the plant are documented",
        "Does the catalog have leaves roots flowers or fruit",
    ),
    QueryType.GET_PHYTOCHEMICALS: (
        "Which molecules have researchers found in this plant",
        "What chemical constituents occur in it",
        "What natural substances are present in the leaves",
    ),
    QueryType.GET_BIOACTIVITY: (
        "How did its compounds perform in laboratory testing",
        "Explain the experimental assay measurements",
        "What binding or activity values were measured",
    ),
    QueryType.GET_PROTEIN_TARGETS: (
        "Which proteins do its compounds interact with",
        "What biological targets were tested",
        "What are the molecular targets",
    ),
    QueryType.GET_THERAPEUTIC_USES: (
        "What illnesses is this plant traditionally associated with",
        "What illnesses is it traditionally associated with",
        "Which ailments has it been linked to",
        "What conditions has it been reported for",
        "How have people traditionally used it for health",
    ),
    QueryType.GET_DOCUMENTS: (
        "Where was this finding published",
        "Which publications report this information",
        "Show the papers behind these records",
    ),
    QueryType.GET_EVIDENCE: (
        "What support is there for this claim",
        "How strong is the research behind it",
        "What scientific findings support the reported use",
    ),
}
FOLLOWUPS = (
    "Could you expand on that",
    "Please explain the previous answer in more detail",
    "What do those findings mean",
    "Why does that matter",
)


def cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(x * x for x in left) * sum(x * x for x in right))
    return numerator / norm if norm else 0.0


class SemanticIntentModel:
    def __init__(self, embeddings: EmbeddingProvider, fallback: IntentModel | None = None) -> None:
        self.embeddings = embeddings
        self.fallback = fallback
        self._vectors: list[list[float]] | None = None
        self._labels = [kind for kind, phrases in EXAMPLES.items() for _ in phrases]
        self._lock = asyncio.Lock()

    async def suggest(
        self, question: str, previous: list[QueryType], active_plant: bool
    ) -> IntentSuggestion | None:
        try:
            async with self._lock:
                if self._vectors is None:
                    phrases = [phrase for examples in EXAMPLES.values() for phrase in examples]
                    self._vectors = await self.embeddings.embed([*phrases, *FOLLOWUPS])
            assert self._vectors is not None
            query = (await self.embeddings.embed([question]))[0]
            scores: dict[QueryType, float] = {}
            for label, vector in zip(self._labels, self._vectors, strict=False):
                scores[label] = max(scores.get(label, -1), cosine(query, vector))
            ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
            followup_score = max(cosine(query, v) for v in self._vectors[-len(FOLLOWUPS):])
            if previous and active_plant and followup_score >= 0.72 and (
                followup_score >= ranked[0][1] + 0.05
            ):
                return IntentSuggestion(reuse_previous_topic=True, confidence=followup_score)
            top, second = ranked[0], ranked[1]
            if max(top[1], followup_score) < 0.45:
                return None
            # Generic 'plant overview' embeddings can score highly on unknown
            # nouns. In that band, clarification is safer than topic guessing.
            if top[0] == QueryType.GET_PLANT_DETAILS and top[1] < 0.85:
                return None
            if top[1] >= 0.73 and top[1] - second[1] >= 0.06:
                return IntentSuggestion(query_types=[top[0]], confidence=top[1])
        except (OSError, ValueError, RuntimeError):
            pass
        return (
            await self.fallback.suggest(question, previous, active_plant)
            if self.fallback is not None
            else None
        )
