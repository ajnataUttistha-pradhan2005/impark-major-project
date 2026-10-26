"""Four-agent Deep Agents runtime behind the existing conversation contract."""

import asyncio
import json
import logging
import re
import time
from typing import Any

try:
    from evaluator.local_tracer import LocalRedisTracer
except ImportError:
    LocalRedisTracer = None  # type: ignore

from deepagents import (
    CompiledSubAgent,
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from langchain.agents import create_agent
from langchain.tools import tool

from backend.agents.text.interpretation import interpret
from backend.agents.text.resolver import normalize
from backend.agents.text.search import HybridNameSearch
from backend.config.settings import Settings
from backend.contracts.actions import Action, ActionName, AgentInvocation, Capability
from backend.contracts.agents import (
    CandidatePlant,
    Failure,
    GraphAgentInput,
    GraphAgentOutput,
    GraphParameters,
    GraphQuery,
    ImageAgentInput,
    ImageAgentResult,
    Observation,
    QueryType,
    TextResult,
)
from backend.contracts.evidence import Evidence
from backend.contracts.response import (
    ClarificationRequest,
    FinalResponse,
    FinalResponseRequest,
    ResponseContext,
)
from backend.llm.grounded import GroundedResponseProvider
from backend.orchestrator.deepagents.context import (
    build_turn_prompt,
    effective_question,
    named_fact,
)
from backend.orchestrator.deepagents.host import AgentHost
from backend.orchestrator.deepagents.models import AgentModelFactory
from backend.orchestrator.deepagents.prompts import (
    GRAPH_AGENT_PROMPT,
    MAIN_AGENT_PROMPT,
    REPAIR_AGENT_PROMPT,
)
from backend.orchestrator.deepagents.response_quality import (
    attach_record_citations,
    clean_plaintext_math,
    contradicts_retrieved_facts,
    is_unfinished_plan,
    needs_scientific_repair,
)
from backend.services.live import publish
from backend.state.models import ConversationState, DialogueTurn, SessionMode, TaskStatus
from backend.trace.models import EventType

logger = logging.getLogger(__name__)


class DeepAgentRuntime:
    def __init__(self, harness: AgentHost, models: AgentModelFactory, settings: Settings) -> None:
        self.harness, self.models, self.settings = harness, models, settings

    @staticmethod
    def _invocation(
        state: ConversationState, name: ActionName, capability: Capability
    ) -> AgentInvocation:
        return AgentInvocation(
            correlation=state.correlation.model_copy(deep=True),
            action=Action(name=name),
            capability=capability,
        )

    async def run(self, state: ConversationState) -> ConversationState:
        tracer = LocalRedisTracer() if LocalRedisTracer is not None else None
        state = state.model_copy(deep=True)
        state.termination.status = TaskStatus.RUNNING
        self.harness.emit(state, EventType.TURN_STARTED)
        if state.context.active_plant is None and state.belief.hypotheses:
            selected = max(state.belief.hypotheses, key=lambda item: item.confidence).candidate
            if selected.confidence >= self.settings.entity_auto_resolve_threshold:
                state.context.active_plant = selected
        active = state.context.active_plant
        if (
            state.session.mode == SessionMode.DISCOVERY
            and active is not None
            and state.user_message.strip().casefold() == active.label.casefold()
        ):
            state.session.locked_plant_id = active.plant_id
            state.session.mode = SessionMode.CONVERSATION
            state.termination.status = TaskStatus.COMPLETE
            text = (
                f"You're exploring {active.label}. What would you like to know about it?"
            )
            state.response = FinalResponse(text=text, provider="deepagents", placeholder=False)
            state.context.recent_dialogue = [
                *state.context.recent_dialogue,
                DialogueTurn(question=state.user_message, answer=text),
            ][-4:]
            publish("response_started", {"run_id": str(state.correlation.run_id)})
            publish("response_delta", {"text": text})
            publish("response_completed", state.response.model_dump(mode="json"))
            self.harness.emit(state, EventType.RESPONSE_STREAM_COMPLETED)
            if tracer is not None:
                tracer.record_node("text_entity", 1.0)
                tracer.publish_run(
                    user_input=state.user_message,
                    agent_output=text,
                    expected_agent="text_entity",
                    ground_truth=active.label,
                    manual_context=f"Selected plant: {active.label} ({active.plant_id})",
                    extra_metadata={
                        "session_id": str(state.correlation.session_id),
                        "run_id": str(state.correlation.run_id),
                        "plant_label": active.label,
                        "mode": "DISCOVERY_LOCK",
                    },
                )
            return state
        candidates: dict[str, CandidatePlant] = {}
        scope_rejected = False
        citation_map: dict[str, Evidence] = {
            str(item.evidence_id): item for item in state.context.citation_history
        }
        fallback_citation_ids: list[str] = []
        graph_calls = 0
        graph_cache: dict[str, str] = {}
        retrieved_types: list[QueryType] = []

        @tool
        async def resolve_plant_names(text: str) -> str:
            """Resolve a plant name, alias, description or typo using the existing catalog."""
            nonlocal active, scope_rejected
            t_start = time.perf_counter()
            provider = getattr(self.harness.execution.text, "provider", None)
            if not isinstance(provider, HybridNameSearch):
                return json.dumps({"error": "Plant search unavailable"})
            matches, stages = await provider.resolve(text, limit=5)
            for match in matches:
                candidates[match.plant_id] = match
            if active and any(
                c.plant_id != active.plant_id and c.confidence >= 0.95 for c in matches
            ):
                scope_rejected = True
            if active is None and len({c.plant_id for c in matches if c.confidence >= 0.95}) == 1:
                active = next(c for c in matches if c.confidence >= 0.95)
            payload = TextResult(
                candidates=matches,
                placeholder=False,
                intent="DISCOVER_PLANT",
                stages=stages,
                needs_clarification=active is None,
            )
            state.execution.observations.append(
                Observation(
                    invocation=self._invocation(
                        state, ActionName.RESOLVE_TEXT_ENTITY, Capability.TEXT
                    ),
                    component=Capability.TEXT,
                    payload=payload,
                )
            )
            self.harness.emit(state, EventType.OBSERVATION_CREATED)
            response = json.dumps(
                {
                    "candidates": [c.model_dump(mode="json") for c in matches],
                    "established_plant_id": active.plant_id if active else None,
                    "stages": stages,
                }
            )
            if tracer is not None:
                elapsed_ms = (time.perf_counter() - t_start) * 1000
                tracer.record_node("text_entity", elapsed_ms)
                tracer.add_context(response)
            return response

        @tool
        async def inspect_uploaded_image() -> str:
            """Classify the uploaded image with the existing CNN and image-vector search."""
            nonlocal active
            if state.image is None:
                return json.dumps({"error": "No image uploaded in this turn"})
            t_start = time.perf_counter()
            result = await self.harness.execution.image.execute(
                ImageAgentInput(
                    invocation=self._invocation(state, ActionName.ANALYZE_IMAGE, Capability.IMAGE),
                    image=state.image,
                ),
                callbacks=[tracer] if tracer else None,
            )
            state.execution.observations.append(result)
            payload = result.payload
            if isinstance(payload, ImageAgentResult):
                state.evidence.image.extend(payload.evidence)
                for candidate in payload.candidates:
                    candidates[candidate.plant_id] = candidate
                if active is None and not payload.needs_clarification and payload.candidates:
                    active = payload.candidates[0]
                self.harness.emit(state, EventType.OBSERVATION_CREATED)
                response = json.dumps(payload.model_dump(mode="json"))
                if tracer is not None:
                    elapsed_ms = (time.perf_counter() - t_start) * 1000
                    tracer.record_node("image_understanding", elapsed_ms)
                    tracer.add_context(response)
                return response
            return json.dumps({"error": "Image understanding unavailable"})

        @tool
        async def retrieve_plant_graph(
            query_type: str,
            part_id: str | None = None,
            compound_id: str | None = None,
            activity_id: str | None = None,
            target_id: str | None = None,
            therapeutic_use_id: str | None = None,
            document_id: str | None = None,
        ) -> str:
            """Read plant-scoped graph facts by typed query.

            Supported: GET_PLANT_DETAILS, GET_PLANT_ALIASES, GET_PLANT_PARTS, GET_PHYTOCHEMICALS,
            GET_THERAPEUTIC_USES, GET_BIOACTIVITY, GET_PROTEIN_TARGETS,
            GET_DOCUMENTS, GET_EVIDENCE, and matching DETAILS queries.
            """
            if active is None:
                return json.dumps({"error": "Establish one plant before graph retrieval"})
            nonlocal graph_calls
            cache_key = json.dumps(
                [
                    query_type,
                    part_id,
                    compound_id,
                    activity_id,
                    target_id,
                    therapeutic_use_id,
                    document_id,
                ]
            )
            if cache_key in graph_cache:
                return graph_cache[cache_key]
            if graph_calls >= 3:
                return json.dumps(
                    {"error": "Graph query budget reached; answer from retrieved facts"}
                )
            graph_calls += 1
            try:
                kind = QueryType(query_type)
                if kind in {
                    QueryType.COMPARE_PLANTS,
                    QueryType.TRACE_EVIDENCE,
                    QueryType.GET_PLANTS_CONTAINING_COMPOUND,
                    QueryType.GET_PLANTS_FOR_THERAPEUTIC_USE,
                    QueryType.GET_COMPOUNDS_TARGETING_PROTEIN,
                }:
                    return json.dumps({"error": "Query type unavailable in a one-plant chat"})
                query = GraphQuery(
                    query_type=kind,
                    parameters=GraphParameters(
                        plant_id=active.plant_id,
                        part_id=part_id,
                        compound_id=compound_id,
                        activity_id=activity_id,
                        target_id=target_id,
                        therapeutic_use_id=therapeutic_use_id,
                        document_id=document_id,
                    ),
                    limit=20,
                )
            except ValueError:
                return json.dumps({"error": "Invalid typed graph query or missing filter"})
            retrieved_types.append(kind)
            t_graph_start = time.perf_counter()
            graph_input = GraphAgentInput(
                invocation=self._invocation(state, ActionName.RETRIEVE_GRAPH, Capability.GRAPH),
                query=query,
            )
            try:
                result = await self.harness.execution.graph.execute(
                    graph_input,
                    callbacks=[tracer] if tracer else None,
                )
            except TypeError:
                result = await self.harness.execution.graph.execute(graph_input)
            state.execution.observations.append(result)
            if isinstance(result, Failure):
                return json.dumps({"error": result.reason})
            payload = result.payload
            if not isinstance(payload, GraphAgentOutput):
                return json.dumps({"error": "Graph retrieval unavailable"})
            state.evidence.graph.extend(payload.evidence)
            state.evidence.gaps.extend(payload.gaps)
            state.evidence.contradictions.extend(payload.contradictions)
            state.context.recent_query_types = [*state.context.recent_query_types, kind][-4:]
            for evidence in payload.evidence:
                citation_map[str(evidence.evidence_id)] = evidence
            self.harness.emit(state, EventType.OBSERVATION_CREATED)
            if tracer is not None:
                elapsed_ms = (time.perf_counter() - t_graph_start) * 1000
                tracer.record_node("knowledge_graph", elapsed_ms)
                tracer.node_latencies_ms[tracer.retrieval_node_name] = round(elapsed_ms, 2)
                for evidence in payload.evidence:
                    tracer.add_context(evidence.claim)
            response = json.dumps(
                {
                    "plant": active.label,
                    "facts": [
                        {
                            "citation_id": str(e.evidence_id),
                            "record": json.loads(e.claim),
                            "evidence_class": e.evidence_type.value,
                        }
                        for e in payload.evidence[:8]
                    ],
                    "more_available": payload.truncated or len(payload.evidence) > 8,
                },
                default=str,
            )
            graph_cache[cache_key] = response
            return response

        subagents = [
            CompiledSubAgent(
                name="text_entity",
                description="Resolve plant names and aliases from PostgreSQL and Qdrant.",
                runnable=create_agent(
                    model=self.models.get("text"),
                    tools=[resolve_plant_names],
                    system_prompt=(
                        "Resolve botanical identity using your tool. Return candidates "
                        "and uncertainty; do not invent plants."
                    ),
                ),
            ),
            CompiledSubAgent(
                name="image_understanding",
                description="Analyze an uploaded plant image with CNN and vector retrieval.",
                runnable=create_agent(
                    model=self.models.get("image"),
                    tools=[inspect_uploaded_image],
                    system_prompt=(
                        "Use the supplied image tool. Return ranked evidence and uncertainty."
                    ),
                ),
            ),
            CompiledSubAgent(
                name="knowledge_graph",
                description="Retrieve plant-scoped medicinal-plant facts and evidence.",
                runnable=create_agent(
                    model=self.models.get("graph"),
                    tools=[retrieve_plant_graph],
                    system_prompt=GRAPH_AGENT_PROMPT,
                ),
            ),
        ]
        main_provider = self.settings.agent_main_model_provider.strip().lower()
        register_harness_profile(
            main_provider,
            HarnessProfile(
                base_system_prompt=(
                    "Use the task tool to delegate to named specialists. "
                    "After receiving enough facts, answer directly."
                ),
                general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
                excluded_tools=frozenset(
                    {"ls", "read_file", "write_file", "edit_file", "glob", "grep"}
                ),
            ),
        )
        orchestrator = create_deep_agent(
            model=self.models.get("main"),
            subagents=subagents,
            system_prompt=MAIN_AGENT_PROMPT,
        )
        prompt = build_turn_prompt(state)
        self.harness.emit(state, EventType.ACTION_CANDIDATE_GENERATED)
        fallback_used = False
        try:
            async with asyncio.timeout(max(45, self.settings.action_timeout_seconds * 3)):
                result = await orchestrator.ainvoke(
                    {"messages": [{"role": "user", "content": prompt}]},
                    config={"recursion_limit": 16},
                )
            last_message = result["messages"][-1]
            logger.info(
                "deep_orchestrator_result messages=%s last_type=%s content_length=%s "
                "tool_calls=%s done_reason=%s",
                len(result["messages"]),
                type(last_message).__name__,
                len(str(last_message.content)),
                len(getattr(last_message, "tool_calls", []) or []),
                getattr(last_message, "response_metadata", {}).get("done_reason"),
            )
            answer = str(last_message.content).strip()
            stopped_for_length = (
                getattr(last_message, "response_metadata", {}).get("done_reason") == "length"
            )
            if not answer and not stopped_for_length:
                raise ValueError("Deep agent returned an empty answer")
            if stopped_for_length or is_unfinished_plan(answer) or needs_scientific_repair(answer):
                current_facts = [
                    {
                        "citation_id": str(item.evidence_id),
                        "record": item.claim[:450],
                        "evidence_class": item.evidence_type.value,
                    }
                    for item in state.evidence.graph[:4]
                ]
                async with asyncio.timeout(self.settings.action_timeout_seconds):
                    completed = await self.models.get("main").ainvoke(
                        [
                            ("system", REPAIR_AGENT_PROMPT),
                            (
                                "user",
                                prompt
                                + "\nCurrent retrieved facts: "
                                + json.dumps(current_facts)
                                + "\nAnswer now using these facts and only relevant general "
                                "knowledge. Keep it brief and complete.",
                            ),
                        ]
                    )
                answer = str(completed.content).strip()
                if (
                    not answer
                    or getattr(completed, "response_metadata", {}).get("done_reason") == "length"
                    or is_unfinished_plan(answer)
                    or needs_scientific_repair(answer)
                ):
                    raise ValueError("Deep agent did not complete its answer")
        except (TimeoutError, ValueError, RuntimeError, OSError) as error:
            logger.warning("deep_orchestrator_failed error_type=%s", type(error).__name__)
            fallback_used = True
            if active is not None and not state.evidence.graph and state.user_message:
                intents, _, _ = interpret(normalize(state.user_message))
                kind = intents[0] if intents else QueryType.GET_PLANT_DETAILS
                await retrieve_plant_graph.ainvoke({"query_type": kind.value})
            if state.evidence.graph and active is not None:
                fallback_context = ResponseContext(
                    intent=state.context.recent_query_types[-1].value
                    if state.context.recent_query_types
                    else "GET_PLANT_DETAILS",
                    user_question=state.user_message,
                    resolved_plant=active,
                    graph_evidence=state.evidence.graph[:20],
                    outcome="Objectives satisfied",
                )
                fallback = await GroundedResponseProvider().generate(
                    FinalResponseRequest(response_context=fallback_context)
                )
                answer = fallback.text
                fallback_citation_ids = [str(identifier) for identifier in fallback.citation_ids]
            else:
                answer = "I couldn't complete that answer. Please try again."

        # The model plans first; a bounded coverage check closes missed retrievals.
        # It applies to every supported graph topic, not to a list of question phrases.
        if active is not None and not scope_rejected and not fallback_used:
            requested, _, _ = interpret(normalize(effective_question(state)))
            new_facts = False
            for kind in requested:
                if kind in retrieved_types or graph_calls >= 3:
                    continue
                before = len(state.evidence.graph)
                await retrieve_plant_graph.ainvoke({"query_type": kind.value})
                new_facts = new_facts or len(state.evidence.graph) > before
            if new_facts or contradicts_retrieved_facts(answer, state.evidence.graph):
                facts = [
                    {
                        "citation_id": str(item.evidence_id),
                        "record": item.claim[:700],
                        "evidence_class": item.evidence_type.value,
                    }
                    for item in state.evidence.graph[-12:]
                ]
                try:
                    async with asyncio.timeout(self.settings.action_timeout_seconds):
                        completed = await self.models.get("main").ainvoke(
                            [
                                ("system", REPAIR_AGENT_PROMPT),
                                (
                                    "user",
                                    prompt
                                    + "\nAnswer the resolved current question from these freshly "
                                    "retrieved plant records. Replace any earlier claim that "
                                    "records were unavailable. Verified facts: "
                                    + json.dumps(facts, ensure_ascii=False),
                                ),
                            ]
                        )
                    revised = str(completed.content).strip()
                    if (
                        not revised
                        or is_unfinished_plan(revised)
                        or contradicts_retrieved_facts(revised, state.evidence.graph)
                        or needs_scientific_repair(revised)
                    ):
                        raise ValueError("Grounded revision was incomplete")
                    answer = revised
                except (TimeoutError, ValueError, RuntimeError, OSError):
                    fallback_used = True
                    fallback_context = ResponseContext(
                        intent=(
                            retrieved_types[-1].value if retrieved_types else "GET_PLANT_DETAILS"
                        ),
                        user_question=effective_question(state),
                        resolved_plant=active,
                        graph_evidence=state.evidence.graph[:20],
                        outcome="Objectives satisfied",
                    )
                    fallback = await GroundedResponseProvider().generate(
                        FinalResponseRequest(response_context=fallback_context)
                    )
                    answer = fallback.text
                    fallback_citation_ids = [
                        str(identifier) for identifier in fallback.citation_ids
                    ]

        if active is None and not candidates and state.user_message:
            await resolve_plant_names.ainvoke({"text": state.user_message})
        if active is None and not candidates and state.image is not None:
            await inspect_uploaded_image.ainvoke({})
        if (
            active is not None
            and not state.evidence.graph
            and state.session.mode == SessionMode.DISCOVERY
        ):
            answer = (
                f"Identified plant: {active.label}. This chat now focuses on this plant. "
                "What would you like to know about it?"
            )

        if scope_rejected:
            answer = (
                "This chat focuses on one plant. Start a new chat to discuss a different plant."
            )
            state.termination.status = TaskStatus.SCOPE_REJECTED
        elif active is None:
            offered = sorted(candidates.values(), key=lambda c: c.confidence, reverse=True)[:5]
            state.clarification = ClarificationRequest(
                question="Which plant do you mean? Choose a suggestion or provide its name.",
                candidates=offered,
            )
            state.termination.status = TaskStatus.WAITING_USER
            self.harness.emit(state, EventType.CLARIFICATION_REQUESTED)
            answer = state.clarification.question
        else:
            if state.session.locked_plant_id not in {None, active.plant_id}:
                raise ValueError("Deep agent attempted to change the locked plant")
            state.context.active_plant = active
            state.session.locked_plant_id = active.plant_id
            state.session.mode = SessionMode.CONVERSATION
            state.clarification = None
            state.termination.status = TaskStatus.COMPLETE
        answer = clean_plaintext_math(answer)
        if not fallback_used:
            answer = re.sub(r"\[\d+(?:\.\.\.)?\]", "", answer)
        answer = re.sub(
            r"\[([0-9a-fA-F-]{36})\]",
            lambda match: match.group() if match.group(1) in citation_map else "",
            answer,
        )
        if not fallback_used:
            available = [*state.context.citation_history, *state.evidence.graph]
            recorded_names = [name for item in available if (name := named_fact(item))]
            answer = attach_record_citations(
                answer,
                list(dict.fromkeys(recorded_names)),
                available,
            )
        cited: list[Evidence] = [
            citation_map[identifier]
            for identifier in fallback_citation_ids
            if identifier in citation_map
        ]
        for label in re.findall(r"\[([0-9a-f-]{36})\]", answer):
            if label in citation_map and citation_map[label] not in cited:
                cited.append(citation_map[label])
        for index, evidence in enumerate(cited, 1):
            answer = answer.replace(f"[{evidence.evidence_id}]", f"[{index}]")
        names = [name for item in cited if (name := named_fact(item))]
        state.context.focus_entities = list(dict.fromkeys(names))[:30]
        state.response = FinalResponse(
            text=answer,
            citation_ids=[e.evidence_id for e in cited],
            placeholder=False,
            provider="grounded" if fallback_used else "deepagents",
            model=getattr(self.models.get("main"), "model", None),
            fallback_used=fallback_used,
        )
        state.context.citation_history = (state.context.citation_history + state.evidence.graph)[
            -100:
        ]
        state.context.recent_dialogue = [
            *state.context.recent_dialogue,
            DialogueTurn(
                question=state.user_message,
                answer=answer[:4000],
                query_types=list(dict.fromkeys(retrieved_types)),
                citation_ids=[item.evidence_id for item in cited],
            ),
        ][-4:]
        publish("response_started", {"run_id": str(state.correlation.run_id)})
        for index in range(0, len(answer), 128):
            publish("response_delta", {"text": answer[index : index + 128]})
        publish("response_completed", state.response.model_dump(mode="json"))
        self.harness.emit(state, EventType.RESPONSE_STREAM_COMPLETED)

        # Single end-of-turn evaluation publish: Streamed to Redis for LLM-as-a-Judge pipeline
        # Emitted when an action/tool was performed or a final answer was generated
        if tracer is not None and (tracer.actions_performed > 0 or bool(answer)):
            evidence_claims = [e.claim for e in state.evidence.graph]
            manual_ctx = "\n".join(evidence_claims) if evidence_claims else None
            tracer.publish_run(
                user_input=state.user_message,
                agent_output=answer,
                expected_agent="knowledge_graph" if state.evidence.graph else None,
                ground_truth=None,
                manual_context=manual_ctx,
                extra_metadata={
                    "session_id": str(state.correlation.session_id),
                    "run_id": str(state.correlation.run_id),
                    "plant_label": active.label if active else None,
                    "fallback_used": fallback_used,
                },
            )

        return state
