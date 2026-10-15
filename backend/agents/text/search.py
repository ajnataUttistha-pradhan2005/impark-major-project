"""Deterministic-first retrieval; semantic scores never become identity probabilities."""

import asyncio
import re
from typing import Protocol
from uuid import UUID

import httpx
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from rapidfuzz.fuzz import ratio

from backend.agents.text.catalog import NameRecord, SearchHit
from backend.agents.text.embeddings import EmbeddingProvider
from backend.agents.text.resolver import normalize
from backend.contracts.agents import CandidatePlant
from backend.contracts.evidence import Provenance
from backend.database.qdrant.client import QdrantStore


class NameRepository(Protocol):
    async def generation(self) -> UUID: ...
    async def names(self, generation: UUID) -> list[NameRecord]: ...
    async def lexical(self, generation: UUID, query: str, limit: int = 40) -> list[SearchHit]: ...
    async def prefix(self, generation: UUID, query: str, limit: int = 20) -> list[NameRecord]: ...


STOP = set(
    "a an the is are it its this that plant plants leaf leaves root roots flower flowers "
    "what which tell me about show list find identify name of in for with and or does do "
    "has have contain contains compounds chemicals uses medicinal benefits please "
    "scientific common "
    "called known can you give details information compare versus vs not no instead i mean".split()
)


def candidate(record: NameRecord, score: float, method: str) -> CandidatePlant:
    return CandidatePlant(
        plant_id=str(record.plant_id),
        label=record.plant_name,
        confidence=score,
        matched_name=record.name,
        match_method=method,
        language=record.language,
        alias_type=record.alias_type,
        provenance=[
            Provenance(
                source_id=str(record.name_id),
                source_type="neo4j_name_projection",
                reference=f"PlantDetails:{record.plant_name}; alias:{record.name}",
            )
        ],
    )


class HybridNameSearch:
    def __init__(
        self,
        names: NameRepository,
        vectors: QdrantStore | None = None,
        embeddings: EmbeddingProvider | None = None,
    ) -> None:
        self.repository, self.vectors, self.embeddings = names, vectors, embeddings
        self._generation: UUID | None = None
        self._names: list[NameRecord] = []
        self._catalog_lock = asyncio.Lock()
        self._exact: dict[str, list[NameRecord]] = {}
        self._ids: dict[str, list[NameRecord]] = {}
        self._phrase_lengths: set[int] = set()

    async def catalog(self) -> tuple[UUID, list[NameRecord]]:
        generation = await self.repository.generation()
        async with self._catalog_lock:
            if generation != self._generation:
                records = await self.repository.names(generation)
                exact: dict[str, list[NameRecord]] = {}
                ids: dict[str, list[NameRecord]] = {}
                for record in records:
                    exact.setdefault(record.normalized_name, []).append(record)
                    ids.setdefault(str(record.plant_id), []).append(record)
                self._exact, self._ids = exact, ids
                self._phrase_lengths = {len(name.split()) for name in exact}
                self._names, self._generation = records, generation
        return generation, self._names

    async def search(self, normalized_text: str, limit: int = 5) -> list[CandidatePlant]:
        result, _ = await self.resolve(normalized_text, limit)
        return result

    async def resolve(
        self, text: str, limit: int = 5, *, use_semantic: bool = True, exact_only: bool = False
    ) -> tuple[list[CandidatePlant], list[str]]:
        if not 1 <= limit <= 20 or not text.strip() or len(text) > 8000:
            raise ValueError("Invalid entity search input")
        generation, records = await self.catalog()
        query = normalize(text)
        # Indexed fast path; correction/language/negation retain the full scoped path below.
        if not re.search(r"\b(not|instead|i mean|in)\b", query):
            words = query.split()
            exact_phrases = {
                " ".join(words[i : i + n])
                for n in self._phrase_lengths
                for i in range(len(words) - n + 1)
            }
            found = [
                record
                for phrase in exact_phrases
                if phrase == query or (len(phrase) >= 3 and phrase not in STOP)
                for record in self._exact.get(phrase, [])
            ]
            found = self._ids.get(text.strip(), found)
            found = [
                r
                for r in found
                if not any(
                    r.normalized_name != other.normalized_name
                    and f" {r.normalized_name} " in f" {other.normalized_name} "
                    for other in found
                )
            ]
            if found:
                score = 0.99 if len({r.plant_id for r in found}) == 1 else 0.79
                unique = {
                    r.plant_id: candidate(r, score, "exact_alias")
                    for r in sorted(found, key=lambda r: str(r.name_id))
                }
                return sorted(unique.values(), key=lambda c: (c.label, c.plant_id))[:limit], [
                    "exact_alias"
                ]
        language_hints = {
            normalize(r.language)
            for r in records
            if r.language
            and r.language != "scientific"
            and re.search(r"\bin\s+" + re.escape(normalize(r.language)) + r"\b", query)
        }
        if len(language_hints) == 1:
            language = next(iter(language_hints))
            records = [
                r
                for r in records
                if r.language is None or normalize(r.language) in {language, "scientific"}
            ]
        # Explicit correction ignores the rejected phrase for candidate retrieval.
        correction = re.search(r"\b(?:not .+? but|instead|i mean)\s+(.+)$", query)
        if correction:
            query = correction.group(1)
        rejected = (
            {
                r.plant_id
                for r in records
                if re.search(
                    r"\bnot\s+(?:the\s+)?" + re.escape(r.normalized_name) + r"(?=\s|$)", query
                )
            }
            if re.search(r"\bnot\b", query)
            else set()
        )
        records = [r for r in records if r.plant_id not in rejected]
        words = query.split()
        stages = ["exact_alias"]
        matches: list[NameRecord] = []
        for record in records:
            alias_value = record.normalized_name
            if (
                str(record.plant_id) == text.strip()
                or alias_value == query
                or (
                    len(alias_value) >= 3
                    and alias_value not in STOP
                    and f" {alias_value} " in f" {query} "
                )
            ):
                matches.append(record)
        # Prefer a complete scientific/longer alias over its embedded shorter alias.
        matches = [
            r
            for r in matches
            if not any(
                r.normalized_name != other.normalized_name
                and f" {r.normalized_name} " in f" {other.normalized_name} "
                for other in matches
            )
        ]
        if matches:
            ids = {r.plant_id for r in matches}
            confidence = 0.99 if len(ids) == 1 else 0.79
            unique = {r.plant_id: candidate(r, confidence, "exact_alias") for r in matches}
            return sorted(unique.values(), key=lambda c: (c.label, c.plant_id))[:limit], stages
        if exact_only:
            return [], stages
        stages.append("fts_trigram_fuzzy")
        useful = [word for word in words if word not in STOP]
        phrases = sorted(
            {" ".join(useful[i : i + n]) for n in (1, 2, 3, 4) for i in range(len(useful) - n + 1)}
        )
        lexical = await self.repository.lexical(generation, " ".join(useful) or query)
        ranked: dict[str, CandidatePlant] = {}
        # Small bounded alias dictionary catches typos PostgreSQL trigrams miss in short names.
        for record, score in await asyncio.to_thread(fuzzy_matches, records, phrases):
            if score >= 0.78:
                confidence = min(0.94, 0.65 + 0.30 * score)
                value = candidate(record, confidence, "fuzzy")
                old = ranked.get(value.plant_id)
                if old is None or old.confidence < value.confidence:
                    ranked[value.plant_id] = value
        for hit in lexical:
            if hit.record.plant_id in rejected:
                continue
            key = str(hit.record.plant_id)
            if key not in ranked and hit.score >= 0.3:
                ranked[key] = candidate(hit.record, min(0.79, 0.5 + hit.score * 0.25), hit.method)
        if not ranked or max(c.confidence for c in ranked.values()) < 0.85:
            if use_semantic and self.vectors and self.embeddings:
                stages.append("semantic")
                try:
                    async with asyncio.timeout(8):
                        embedding = (await self.embeddings.embed([query]))[0]
                        hits = await self.vectors.search(generation, embedding, 20)
                    for hit in hits:
                        if hit.record.plant_id in rejected:
                            continue
                        if hit.score < 0.65:
                            continue
                        value = candidate(hit.record, min(0.79, hit.score * 0.79), "semantic")
                        if value.plant_id not in ranked:
                            ranked[value.plant_id] = value
                except (
                    TimeoutError,
                    OSError,
                    httpx.HTTPError,
                    UnexpectedResponse,
                    ResponseHandlingException,
                ):
                    stages.append("semantic_unavailable")
        values = sorted(ranked.values(), key=lambda c: (-c.confidence, c.label))[:limit]
        return values, stages

    async def autocomplete(self, query: str, limit: int = 10) -> list[CandidatePlant]:
        generation, _ = await self.catalog()
        records = await self.repository.prefix(generation, normalize(query), 50)
        unique = {r.plant_id: candidate(r, 0.79, "prefix") for r in records}
        if unique:
            return list(unique.values())[:limit]
        return await self.search(query, limit)


def fuzzy_matches(records: list[NameRecord], phrases: list[str]) -> list[tuple[NameRecord, float]]:
    """CPU dictionary matching stays off the server event loop."""
    return [
        (
            record,
            max(
                (
                    ratio(phrase, record.normalized_name) / 100
                    for phrase in phrases
                    if len(phrase) >= 4
                ),
                default=0,
            ),
        )
        for record in records
    ]
