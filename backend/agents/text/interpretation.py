import re

from backend.agents.common.parts import PART_NAMES
from backend.agents.text.resolver import normalize
from backend.contracts.agents import (
    CandidatePlant,
    GraphParameters,
    GraphQuery,
    QueryType,
    ResolvedMention,
)


def scoped_queries(
    text: str,
    candidates: list[CandidatePlant],
    entities: list[ResolvedMention],
    intents: list[QueryType],
    part: str | None,
) -> list[GraphQuery]:
    query = normalize(text)
    # A single plant must be established before these objectives can execute.
    plant_ids = {c.plant_id for c in candidates if c.confidence >= 0.95}
    plant_id = next(iter(plant_ids)) if len(plant_ids) == 1 else None
    citation = re.search(
        r"\b(?:trace|citation|evidence)\s*:?\s*([0-9a-f]{8}-[0-9a-f-]{27,})\b", text.casefold()
    )
    if citation:
        return [
            GraphQuery(
                query_type=QueryType.TRACE_EVIDENCE,
                parameters=GraphParameters(plant_id=plant_id, evidence_id=citation.group(1)),
            )
        ]
    unique = {(e.kind, e.entity_id): e for e in entities}
    if len(unique) != 1:
        return []
    entity = next(iter(unique.values()))
    if entity.kind == "compound":
        qtype = (
            QueryType.GET_PLANTS_CONTAINING_COMPOUND
            if re.search(r"\bplants?\b", query)
            else QueryType.GET_PHYTOCHEMICAL_DETAILS
        )
        parameters = GraphParameters(plant_id=plant_id, part_id=part, compound_id=entity.entity_id)
    elif entity.kind == "therapeutic_use":
        qtype = (
            QueryType.GET_THERAPEUTIC_USES
            if plant_id and re.search(r"\b(?:what is|define|means?|explain|about)\b", query)
            else QueryType.GET_PLANTS_FOR_THERAPEUTIC_USE
        )
        parameters = GraphParameters(
            plant_id=plant_id, part_id=part, therapeutic_use_id=entity.entity_id
        )
    else:
        qtype = (
            QueryType.GET_EVIDENCE
            if plant_id
            and any(
                intent in {QueryType.GET_BIOACTIVITY, QueryType.GET_EVIDENCE} for intent in intents
            )
            else QueryType.GET_COMPOUNDS_TARGETING_PROTEIN
        )
        parameters = GraphParameters(plant_id=plant_id, part_id=part, target_id=entity.entity_id)
    if entity.kind == "compound" and plant_id and intents:
        supported = [
            q
            for q in intents
            if q
            in {
                QueryType.GET_PHYTOCHEMICALS,
                QueryType.GET_PHYTOCHEMICAL_DETAILS,
                QueryType.GET_BIOACTIVITY,
                QueryType.GET_PROTEIN_TARGETS,
                QueryType.GET_DOCUMENTS,
                QueryType.GET_EVIDENCE,
            }
        ]
        if supported:
            return [GraphQuery(query_type=q, parameters=parameters) for q in supported]
    return [GraphQuery(query_type=qtype, parameters=parameters)]


def interpret(text: str) -> tuple[list[QueryType], str | None, bool]:
    query = normalize(text)
    safety = bool(
        re.search(
            r"\b(dosage|dose|how (?:much|many).*(?:take|eat|drink)|cure my|treat my|"
            r"pregnant|replace.*medicine|safe|safety|side effects?|"
            r"toxicity|toxic|contraindications?|drug interactions?|adverse effects?)\b",
            query,
        )
    )
    rules = [
        (r"\b(evidence|supporting data)\b", QueryType.GET_EVIDENCE),
        (
            r"\b(aliases?|other names?|alternative names?|synonyms?|"
            r"vernacular names?|common names?|local names?)\b",
            QueryType.GET_PLANT_ALIASES,
        ),
        (
            r"\b(compounds?|phytochemicals?|chemicals?|constituents?|"
            r"contains?|chemical composition|what is in it|what's in it)\b",
            QueryType.GET_PHYTOCHEMICALS,
        ),
        (
            r"\b(uses?|benefits?|benifits?|benfits?|used for|therapeutic|"
            r"good for|associated with which conditions|health applications?)\b",
            QueryType.GET_THERAPEUTIC_USES,
        ),
        (r"\b(parts?)\b", QueryType.GET_PLANT_PARTS),
        (r"\b(targets?|proteins?)\b", QueryType.GET_PROTEIN_TARGETS),
        (
            r"\b(bioactivity|activities|assays?|measurements?|numbers?|values?|"
            r"ic50|ki|kd|potency|concentrations?|lab(?:oratory)? results?|"
            r"experimental results?|test results?)\b",
            QueryType.GET_BIOACTIVITY,
        ),
        (
            r"\b(sources?|references?|papers?|studies|documents?)\b",
            QueryType.GET_DOCUMENTS,
        ),
        (
            r"\b(details|about|information|what is|scientific name|common name)\b",
            QueryType.GET_PLANT_DETAILS,
        ),
    ]
    intents = [
        intent
        for pattern, intent in rules
        if re.search(pattern, query)
        and not re.search(r"\b(?:not|without)\s+(?:the\s+)?" + pattern, query)
    ]
    if len(intents) > 1 and QueryType.GET_PLANT_DETAILS in intents:
        intents.remove(QueryType.GET_PLANT_DETAILS)
    # A question about assay numbers and their named targets needs the assay
    # records, which already include those targets. A target-only query does not.
    if (
        QueryType.GET_BIOACTIVITY in intents
        and QueryType.GET_PROTEIN_TARGETS in intents
        and re.search(r"\b(measurements?|numbers?|values?|ic50|ki|kd|potency)\b", query)
    ):
        intents.remove(QueryType.GET_PROTEIN_TARGETS)
    parts = mentioned_parts(query)
    if parts and len(intents) > 1 and QueryType.GET_PLANT_PARTS in intents:
        intents.remove(QueryType.GET_PLANT_PARTS)
    if len(parts) == 1 and QueryType.GET_PLANT_DETAILS in intents:
        intents = [
            QueryType.GET_PLANT_PART_DETAILS if q == QueryType.GET_PLANT_DETAILS else q
            for q in intents
        ]
    return intents, parts[0] if len(parts) == 1 else None, safety


def mentioned_parts(text: str) -> list[str]:
    """Return explicit part scopes; multiple scopes require clarification in this demo."""
    query = normalize(text)
    parts = []
    for value, names in PART_NAMES.items():
        if any(re.search(r"\b" + re.escape(name) + r"\b", query) for name in names):
            parts.append(value)
    return parts
