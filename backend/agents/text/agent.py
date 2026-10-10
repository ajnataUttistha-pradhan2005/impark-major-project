import re

from backend.agents.common.parts import PART_NAMES
from backend.agents.text.interpretation import interpret, mentioned_parts, scoped_queries
from backend.agents.text.providers import EntitySearchProvider
from backend.agents.text.resolver import normalize
from backend.agents.text.search import HybridNameSearch
from backend.contracts.actions import Capability
from backend.contracts.agents import (
    Failure,
    FailureType,
    Observation,
    ResolvedMention,
    TextAgentInput,
    TextResult,
)
from backend.database.postgres.client import StoreError


class TextAgent:
    def __init__(
        self,
        provider: EntitySearchProvider | None = None,
    ) -> None:
        self.provider = provider

    async def execute(self, request: TextAgentInput) -> Observation | Failure:
        query = normalize(request.text)
        intents, part, safety = interpret(query)
        if safety:
            return Observation(
                invocation=request.invocation,
                component=Capability.TEXT,
                payload=TextResult(
                    placeholder=False,
                    intent="HEALTH_SAFETY",
                    safety_abstention=True,
                    stages=["deterministic_safety"],
                ),
            )
        stages: list[str] = []
        limitations: list[str] = []
        entities: list[ResolvedMention] = []
        try:
            if isinstance(self.provider, HybridNameSearch):
                candidates, stages = await self.provider.resolve(request.text, exact_only=True)
                if not candidates or not any(
                    query == normalize(c.matched_name or c.label) for c in candidates
                ):
                    entity_lookup = getattr(self.provider.repository, "entities", None)
                    if entity_lookup:
                        entities = await entity_lookup(request.text)
                if not candidates:
                    candidates, stages = await self.provider.resolve(
                        request.text, use_semantic=not entities
                    )
            else:
                candidates = await self.provider.search(query, limit=5) if self.provider else []
        except StoreError:
            return Failure(
                invocation=request.invocation,
                error_type=FailureType.DEPENDENCY_UNAVAILABLE,
                reason="Entity catalog unavailable",
                retryable=True,
            )
        exact = any(c.match_method == "exact_alias" for c in candidates)
        # Pronouns require an established antecedent; never override an explicit new name.
        if (
            not exact
            and request.active_plant
            and not request.reassessment
            and (intents or part or re.search(r"\b(its|it|this plant|that plant)\b", query))
        ):
            residual = re.sub(r"\b(its|it|this plant|that plant)\b", "", query).strip()
            from backend.agents.text.search import STOP

            allowed = STOP | {
                "targets",
                "proteins",
                "evidence",
                "sources",
                "bioactivity",
                "bark",
                "seeds",
                "used",
                "therapeutic",
                "parts",
                "phytochemicals",
                "constituents",
                "references",
                "papers",
                "studies",
                "documents",
                "activities",
                "assays",
            }
            allowed.update(
                word for names in PART_NAMES.values() for name in names for word in name.split()
            )
            if all(word in allowed for word in residual.split()):
                candidates = [
                    request.active_plant.model_copy(update={"match_method": "coreference"})
                ]
                stages.append("coreference")
        if (
            request.active_plant
            and not exact
            and (
                entities
                or re.search(
                    r"\b(?:trace|citation|evidence)\s*:?\s*[0-9a-f]{8}-", request.text.casefold()
                )
            )
        ):
            candidates = [request.active_plant.model_copy(update={"match_method": "coreference"})]
        candidates = [c for c in candidates if c.plant_id not in request.excluded_plant_ids]
        queries = scoped_queries(request.text, candidates, entities, intents, part)
        exact_ids = {c.plant_id for c in candidates if c.match_method == "exact_alias"}
        locked = request.active_plant_id or (
            request.active_plant.plant_id if request.active_plant else None
        )
        scope_rejected = (
            bool(
                re.search(r"\b(compare|versus|vs|difference between)\b", query)
                and len(exact_ids) > 1
            )
            or bool(locked and exact_ids - {locked})
            or bool(re.search(r"\b(which plants|list plants|what plants)\b", query))
        )
        if scope_rejected:
            return Observation(
                invocation=request.invocation,
                component=Capability.TEXT,
                payload=TextResult(placeholder=False, scope_rejected=True),
            )
        if len({c.plant_id for c in candidates if c.match_method == "exact_alias"}) > 1:
            limitations.append("Multiple plants or an ambiguous alias; select the intended plant")
        if part:
            limitations.append(f"Requested plant part: {part}")
        if not candidates and not queries:
            limitations.append("No supported plant identity; provide a name or select a candidate")
        named_only = any(
            query in {normalize(c.label), normalize(c.matched_name or ""), normalize(c.plant_id)}
            for c in candidates
        )
        identification = bool(re.search(r"^(?:identify|find|search|plant name)\b", query))
        intent_uncertain = bool(
            candidates
            and not queries
            and not intents
            and not named_only
            and not identification
            and not any(c.match_method == "coreference" for c in candidates)
            and any(c.confidence >= 0.95 for c in candidates)
        )
        multiple_parts = len(mentioned_parts(query)) > 1
        if multiple_parts:
            queries = []
            intent_uncertain = True
            limitations.append("Multiple part scopes require a single-part clarification")
        clarification_question = None
        if multiple_parts:
            clarification_question = "Which plant part should I retrieve first?"
        elif intent_uncertain:
            clarification_question = (
                "Do you want plant details, compounds, reported uses, targets, or sources?"
            )
        elif not candidates or max(c.confidence for c in candidates) < 0.95:
            clarification_question = (
                "Please select a candidate or provide its scientific/common name."
            )
        return Observation(
            invocation=request.invocation,
            component=Capability.TEXT,
            payload=TextResult(
                candidates=candidates,
                placeholder=self.provider is None,
                intent="HEALTH_SAFETY"
                if safety
                else (intents[0].value if intents else "DISCOVER_PLANT"),
                query_types=intents,
                queries=queries,
                entities=entities,
                part=part,
                stages=stages,
                limitations=limitations,
                needs_clarification=(
                    intent_uncertain
                    or not candidates
                    or max(c.confidence for c in candidates) < 0.95
                ),
                safety_abstention=safety,
                intent_uncertain=intent_uncertain,
                clarification_question=clarification_question,
            ),
            confidence=max((c.confidence for c in candidates), default=0),
        )
