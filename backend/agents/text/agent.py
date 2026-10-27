import re
import time
from typing import Any

from backend.agents.common.callbacks import emit_agent_end, emit_agent_start
from backend.agents.text.intent_model import IntentModel
from backend.agents.text.interpretation import interpret, mentioned_parts, scoped_queries
from backend.agents.text.providers import EntitySearchProvider
from backend.agents.text.resolver import normalize
from backend.agents.text.search import HybridNameSearch
from backend.contracts.actions import Capability
from backend.contracts.agents import (
    Failure,
    FailureType,
    Observation,
    QueryType,
    ResolvedMention,
    TextAgentInput,
    TextResult,
)
from backend.database.postgres.client import StoreError


class TextAgent:
    def __init__(
        self,
        provider: EntitySearchProvider | None = None,
        intent_model: IntentModel | None = None,
    ) -> None:
        self.provider = provider
        self.intent_model = intent_model

    async def execute(
        self, request: TextAgentInput, callbacks: Any = None
    ) -> Observation | Failure:
        t_start = time.perf_counter()
        run_id = str(request.invocation.correlation.run_id)
        emit_agent_start(callbacks, "text_entity", request.text, run_id=run_id)
        query = normalize(request.text)
        intents, part, safety = interpret(query)
        topic_followup = bool(
            request.active_plant
            and request.recent_query_types
            and not intents
            and re.search(
                r"\b(?:tell me more|go on|elaborate(?: on (?:that|those|them|it))?|"
                r"explain (?:that|those|them|it|each|every one|all of (?:them|those))|"
                r"(?:break (?:them|those|each|all) down|"
                r"(?:walk|go) (?:them|those|each|all) through|"
                r"(?:walk|go) through (?:them|those|each|all))|"
                r"what (?:does|do) (?:that|those|it|they|each) mean|"
                r"what (?:does|do) (?:this|that|these|those|the) "
                r"(?:[a-z-]+ ){0,3}mean|"
                r"why (?:is|are) (?:that|those|it|they) relevant|"
                r"why (?:does|would) (?:that|it) matter)\b",
                query,
            )
        )
        if topic_followup:
            intents = request.recent_query_types[:2]
        part_followup = bool(
            request.active_plant
            and request.recent_query_types
            and part
            and (not intents or intents == [QueryType.GET_PLANT_PART_DETAILS])
            and re.match(r"^(?:and|what about|how about|for|in|on|the)\b", query)
        )
        if part_followup:
            intents = request.recent_query_types[:2]
            topic_followup = True
        new_plant_request = bool(
            re.search(
                r"\b(?:(?:another|different)\s+(?:\w+\s+){0,3}plant|"
                r"switch (?:to|plants?)|change plants?)\b",
                query,
            )
        )
        # A short bare name is an identity input, while ordinary questions and
        # elliptical follow-ups keep the session subject without another lookup.
        bare_name = bool(
            request.active_plant
            and not intents
            and not part
            and len(query.split()) <= 4
            and not re.search(
                r"\b(?:what|which|why|how|can|could|tell|explain|more|and|it|its|this|that|about)\b|[?]",
                query,
            )
        )
        model_stage = False
        if (
            not intents
            and not topic_followup
            and not safety
            and not new_plant_request
            and not bare_name
            and self.intent_model is not None
            and (request.active_plant is not None or len(query.split()) > 2)
        ):
            suggestion = await self.intent_model.suggest(
                request.text, request.recent_query_types, request.active_plant is not None
            )
            if suggestion is not None:
                if suggestion.query_types:
                    intents = suggestion.query_types
                elif suggestion.reuse_previous_topic and request.recent_query_types:
                    intents = request.recent_query_types[:2]
                    topic_followup = True
                model_stage = bool(intents)
        locked_followup = bool(
            request.active_plant
            and not request.reassessment
            and not new_plant_request
            and not bare_name
        )
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
        if request.active_plant and new_plant_request:
            return Observation(
                invocation=request.invocation,
                component=Capability.TEXT,
                payload=TextResult(placeholder=False, scope_rejected=True),
            )
        stages: list[str] = []
        if model_stage:
            stages.append("model_intent_suggestion")
        limitations: list[str] = []
        entities: list[ResolvedMention] = []
        try:
            if isinstance(self.provider, HybridNameSearch):
                candidates, lookup_stages = await self.provider.resolve(
                    request.text, exact_only=True
                )
                stages.extend(lookup_stages)
                if not candidates or not any(
                    query == normalize(c.matched_name or c.label) for c in candidates
                ):
                    entity_lookup = getattr(self.provider.repository, "entities", None)
                    if entity_lookup:
                        entities = await entity_lookup(request.text)
                # In conversation the session plant is the subject unless a different
                # name is explicit. Fuzzy matching a question can mistake ordinary
                # words for plant aliases and lose the session's locked identity.
                if not candidates and not locked_followup:
                    candidates, lookup_stages = await self.provider.resolve(
                        request.text, use_semantic=not entities
                    )
                    stages.extend(lookup_stages)
            else:
                candidates = await self.provider.search(query, limit=5) if self.provider else []
        except StoreError:
            return Failure(
                invocation=request.invocation,
                error_type=FailureType.DEPENDENCY_UNAVAILABLE,
                reason="Entity catalog unavailable",
                retryable=True,
            )
        if topic_followup:
            stages.append("topic_coreference")
        # Resolve a narrow elliptical follow-up only when the immediately active
        # conversational topic is a single compound. The plant lock remains intact.
        compound_followup = bool(
            request.active_compound_id
            and not entities
            and (
                re.search(r"\b(it|its|this compound|that compound)\b", query)
                or (
                    topic_followup
                    and any(
                        q
                        in {
                            QueryType.GET_PHYTOCHEMICAL_DETAILS,
                            QueryType.GET_BIOACTIVITY,
                            QueryType.GET_PROTEIN_TARGETS,
                        }
                        for q in request.recent_query_types
                    )
                )
            )
            and not re.search(r"\b(this plant|the plant|plant itself)\b", query)
        )
        if compound_followup:
            assert request.active_compound_id is not None
            entities = [
                ResolvedMention(
                    entity_id=request.active_compound_id,
                    kind="compound",
                    label="the previously discussed compound",
                    confidence=1,
                )
            ]
            stages.append("compound_coreference")
            if re.search(r"\b(?:tell|explain|more)\b", query) and not re.search(
                r"\b(?:evidence|sources?|targets?|proteins?|assays?|bioactivity)\b", query
            ):
                intents = [QueryType.GET_PHYTOCHEMICAL_DETAILS, QueryType.GET_BIOACTIVITY]
        exact = any(c.match_method == "exact_alias" for c in candidates)
        if locked_followup and not exact:
            assert request.active_plant is not None
            candidates = [request.active_plant.model_copy(update={"match_method": "coreference"})]
            stages.append("coreference")
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
            or bool(
                locked
                and bare_name
                and any(c.plant_id != locked and c.confidence >= 0.95 for c in candidates)
            )
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
            and not part
            and not named_only
            and not identification
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
        payload = TextResult(
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
        )
        elapsed_ms = (time.perf_counter() - t_start) * 1000
        context_snippets = [
            f"Candidate: {c.label} (confidence: {c.confidence:.2f})"
            for c in candidates[:3]
        ]
        emit_agent_end(
            callbacks,
            "text_entity",
            payload,
            run_id=run_id,
            latency_ms=elapsed_ms,
            context_snippets=context_snippets,
        )
        return Observation(
            invocation=request.invocation,
            component=Capability.TEXT,
            payload=payload,
            confidence=max((c.confidence for c in candidates), default=0),
        )
