"""Turn allow-listed graph fields into bounded, citation-bearing answer sentences.

Neo4j property dictionaries remain in evidence APIs; they are never rendered as prose.
No sentence here interprets a catalog link as clinical efficacy.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from backend.contracts.evidence import Evidence, EvidenceClass
from backend.contracts.response import ResponseContext


@dataclass(frozen=True)
class AnswerFact:
    text: str
    evidence: Evidence
    kind: str
    part: str = ""
    term: str = ""
    category: str = ""

    @property
    def citation_id(self) -> UUID:
        return self.evidence.evidence_id


def _value(data: Mapping[str, object], key: str, limit: int = 100) -> str:
    raw = data.get(key)
    if not isinstance(raw, (str, int, float)) or isinstance(raw, bool):
        return ""
    value = re.sub(r"\s+", " ", str(raw)).strip()
    if value.casefold() in {"na", "n/a", "none", "null", "-"}:
        return ""
    return value[:limit].rstrip() if value else ""


def _node(evidence: Evidence, key: str) -> str:
    for node in evidence.graph_nodes:
        value = _value(node, key)
        if value:
            return value
    return ""


def _safe_claim(raw: str) -> dict[str, object]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _sentence(evidence: Evidence) -> str:
    try:
        fact = json.loads(evidence.claim)
    except (TypeError, ValueError):
        return "A related source record is available."
    if not isinstance(fact, dict):
        return "A related source record is available."
    kind = evidence.provenance.reference.partition(":")[0]
    part = _node(evidence, "plant_part")
    compound = _node(evidence, "phytochemical_name")
    qualifier = f" in {part}" if part else ""
    if kind == "GET_PLANT_DETAILS":
        names = fact.get("common_names")
        if isinstance(names, list):
            names = ", ".join(str(name) for name in names[:4])
        names = _value({"names": names}, "names", 160)
        status = _value(fact, "global_status")
        regional = _value(fact, "regional_status")
        details = []
        if names:
            details.append(f"common names include {names}")
        if status:
            details.append(f"the recorded global conservation status is {status}")
        if regional:
            details.append(f"the recorded regional conservation status is {regional}")
        if details:
            sentence = "; ".join(details)
            return sentence[0].upper() + sentence[1:] + "."
        return "A plant profile is available in the catalog."
    if kind == "GET_PLANT_ALIASES":
        alias = _value(fact, "alias")
        alias_type = _value(fact, "alias_type")
        language = _value(fact, "language")
        if alias:
            description = f" ({alias_type})" if alias_type else ""
            language_note = f" in {language}" if language else ""
            return f"{alias} is a recorded name{description}{language_note}."
        return "An alternative-name record is available."
    if kind in {"GET_PLANT_PARTS", "GET_PLANT_PART_DETAILS"}:
        name = _value(fact, "plant_part")
        return (
            f"The catalog records {name} as a plant part."
            if name
            else "A plant-part record is available in the catalog."
        )
    if kind in {
        "GET_PHYTOCHEMICALS",
        "GET_PHYTOCHEMICAL_DETAILS",
        "GET_COMPOUNDS_TARGETING_PROTEIN",
    }:
        name = _value(fact, "phytochemical_name")
        category = _value(fact, "classyfire_class")
        if name:
            suffix = f" It is classified as {category}." if category else ""
            return f"{name} is listed as a phytochemical{qualifier}.{suffix}"
    if kind == "GET_THERAPEUTIC_USES":
        term = _value(fact, "therapeutic_use") or _value(fact, "reported_use")
        category = _value(fact, "mesh_category_name")
        if term:
            if category.casefold() == "anatomy":
                return (
                    f"{term} appears as an anatomical reference for "
                    f"{part or 'this plant'}; it is not a treatment claim."
                )
            return f"{term} is listed among uses associated with {part or 'this plant'}."
    if kind in {"GET_BIOACTIVITY", "GET_EVIDENCE"}:
        assay = _value(fact, "standard_type")
        amount = _value(fact, "standard_value", 40)
        unit = _value(fact, "standard_units", 30)
        relation = _value(fact, "standard_relation", 10)
        subject = compound or "a listed phytochemical"
        target = _node(evidence, "target_name")
        if assay and amount:
            measurement = " ".join(part for part in (assay, relation, amount, unit) if part)
            target_phrase = f" against {target}" if target else ""
            return f"A laboratory assay of {subject}{target_phrase} reports {measurement}."
        return f"An activity measurement is recorded for {subject}."
    if kind == "GET_PROTEIN_TARGETS":
        target = _value(fact, "target_name")
        organism = _value(fact, "target_organism")
        if target:
            location = f" in {organism}" if organism else ""
            return (
                f"A record links {compound or 'a listed phytochemical'} "
                f"to the protein target {target}{location}."
            )
    if kind == "GET_DOCUMENTS":
        journal = _value(fact, "document_journal")
        year = _value(fact, "document_year", 8)
        if journal:
            date = f" ({year})" if year else ""
            return (
                f"A linked document record lists {journal}{date}; "
                "the link alone does not establish clinical efficacy."
            )
        source = _value(fact, "source")
        if source:
            return (
                f"A {source} document record is linked to a bioactivity entry. "
                "The record does not list a journal or year."
            )
        return (
            "A document record is linked to a bioactivity entry; "
            "publication details are unavailable."
        )
    if kind == "GET_PLANTS_CONTAINING_COMPOUND" or kind == "GET_PLANTS_FOR_THERAPEUTIC_USE":
        name = _value(fact, "plant_name")
        if name:
            return f"The available records include {name}."
    # A legacy/synthetic claim can carry a directly named use or compound.
    for key, label in (("reported_use", "recorded use"), ("compound", "phytochemical")):
        value = _value(fact, key)
        if value:
            return f"The catalog lists {value} as a {label}."
    return "A related source record is available."


def answer_facts(context: ResponseContext, limit: int = 8) -> list[AnswerFact]:
    evidence = context.graph_evidence
    # Anatomy terms in a source taxonomy are not medical uses. Show them only
    # when they are the sole available result, with the explicit warning above.
    if context.intent == "GET_THERAPEUTIC_USES":
        uses = []
        for item in evidence:
            try:
                claim = json.loads(item.claim)
            except (TypeError, ValueError):
                claim = {}
            if (
                not isinstance(claim, dict)
                or _value(claim, "mesh_category_name").casefold() != "anatomy"
            ):
                uses.append(item)
        if uses:
            evidence = uses
    facts: list[AnswerFact] = []
    activity_count = 0
    for item in evidence:
        kind = item.provenance.reference.partition(":")[0]
        if kind in {"GET_BIOACTIVITY", "GET_EVIDENCE"}:
            if activity_count >= 4:
                continue
            activity_count += 1
        if len(facts) >= limit:
            break
        try:
            claim = json.loads(item.claim)
        except (TypeError, ValueError):
            claim = {}
        if not isinstance(claim, dict):
            claim = {}
        facts.append(
            AnswerFact(
                text=_sentence(item),
                evidence=item,
                kind=item.provenance.reference.partition(":")[0],
                part=_node(item, "plant_part"),
                term=_value(claim, "therapeutic_use") or _value(claim, "reported_use"),
                category=_value(claim, "mesh_category_name"),
            )
        )
    return facts


def fact_lines(facts: list[AnswerFact]) -> list[tuple[str, list[UUID]]]:
    """Render cited, grouped reported-use terms without repeating a template per row."""
    kinds = {fact.kind for fact in facts}
    if "GET_PHYTOCHEMICAL_DETAILS" in kinds and kinds & {"GET_BIOACTIVITY", "GET_EVIDENCE"}:
        detail_facts = [fact for fact in facts if fact.kind == "GET_PHYTOCHEMICAL_DETAILS"]
        activity = [fact for fact in facts if fact.kind in {"GET_BIOACTIVITY", "GET_EVIDENCE"}]
        lines = fact_lines(detail_facts)
        lines.extend(
            (f"- {fact.text} [{index}]\n", [fact.citation_id])
            for index, fact in enumerate(activity, len(detail_facts) + 1)
        )
        return lines
    if facts and all(f.kind == "GET_PHYTOCHEMICAL_DETAILS" for f in facts):
        details = []
        for fact in facts:
            try:
                claim = json.loads(fact.evidence.claim)
            except (TypeError, ValueError):
                claim = {}
            if isinstance(claim, dict):
                name = _value(claim, "phytochemical_name")
                category = _value(claim, "classyfire_class")
                if name:
                    details.append((name, category, fact.part, fact.citation_id))
        if details and len({name.casefold() for name, _, _, _ in details}) == 1:
            name, category, _, _ = details[0]
            family = (
                " It belongs to the flavonoid family, a broad group of plant compounds."
                if category.casefold() == "flavonoids"
                else f" The catalog classifies it as {category}."
                if category
                else ""
            )
            locations = ", ".join(
                f"{part} [{index}]" if part else f"a plant-part record [{index}]"
                for index, (_, _, part, _) in enumerate(details, 1)
            )
            plant_link = f" It is recorded in the {locations}."
            return [
                (
                    f"**{name}** is a phytochemical, meaning a chemical found in plants."
                    + family
                    + plant_link
                    + "\n",
                    [entry[3] for entry in details],
                )
            ]
    if len(facts) > 1 and all(f.kind == "GET_PLANT_PARTS" and f.part for f in facts):
        return [
            (
                ", ".join(
                    f"{fact.part.capitalize()} [{index}]" for index, fact in enumerate(facts, 1)
                )
                + ".\n",
                [fact.citation_id for fact in facts],
            )
        ]
    if len(facts) > 1 and all(f.kind == "GET_PHYTOCHEMICALS" for f in facts):
        compounds: dict[str, list[tuple[str, UUID]]] = {}
        for index, fact in enumerate(facts, 1):
            try:
                claim = json.loads(fact.evidence.claim)
            except (TypeError, ValueError):
                claim = {}
            name = _value(claim, "phytochemical_name") if isinstance(claim, dict) else ""
            if not name:
                break
            compounds.setdefault(fact.part or "Unspecified part", []).append(
                (f"{name} [{index}]", fact.citation_id)
            )
        else:
            return [
                (
                    f"- **{part.capitalize()}:** " + ", ".join(name for name, _ in entries) + "\n",
                    [citation for _, citation in entries],
                )
                for part, entries in compounds.items()
            ]
    if facts and all(
        f.kind == "GET_THERAPEUTIC_USES" and f.term and "anatomical reference" not in f.text
        for f in facts
    ):
        groups: dict[tuple[str, str], list[tuple[str, UUID]]] = {}
        for index, fact in enumerate(facts, 1):
            evidence_label = (
                f" ({fact.evidence.evidence_type.value} evidence)"
                if fact.evidence.evidence_type != EvidenceClass.UNKNOWN
                else ""
            )
            group = (
                "reported condition"
                if fact.category.casefold() in {"", "diseases"}
                else "catalog topic"
            )
            groups.setdefault((fact.part or "This plant", group), []).append(
                (f"{fact.term}{evidence_label} [{index}]", fact.citation_id)
            )
        return [
            (
                f"- **{part.capitalize()}"
                + ("" if group == "reported condition" else " · related topics")
                + ":** "
                + ", ".join(term for term, _ in terms)
                + "\n",
                [citation for _, citation in terms],
            )
            for (part, group), terms in groups.items()
        ]
    return [
        (
            f"- {fact.text}"
            + (
                f" ({fact.evidence.evidence_type.value} evidence)"
                if fact.evidence.evidence_type != EvidenceClass.UNKNOWN
                else ""
            )
            + f" [{index}]\n",
            [fact.citation_id],
        )
        for index, fact in enumerate(facts, 1)
    ]


def intro(context: ResponseContext) -> str:
    plant = _value(
        {"plant": context.resolved_plant.label if context.resolved_plant else ""}, "plant"
    )
    subject = plant or "this plant"
    categories = {item.provenance.reference.partition(":")[0] for item in context.graph_evidence}
    if len(categories) > 1:
        compound = next(
            (
                _node(item, "phytochemical_name")
                for item in context.graph_evidence
                if _node(item, "phytochemical_name")
            ),
            "",
        )
        if compound:
            return f"Here is a little more about {compound} in {subject}:"
        return f"Here is what the available records say about {subject}:"
    introductions = {
        "GET_PLANT_DETAILS": f"Here is the available catalog profile for {subject}:",
        "GET_PLANT_PARTS": f"The catalog records these parts of {subject}:",
        "GET_PLANT_PART_DETAILS": f"The catalog records these part details for {subject}:",
        "GET_PHYTOCHEMICALS": f"These compounds are recorded for {subject}:",
        "GET_PHYTOCHEMICAL_DETAILS": f"About this compound in {subject}:",
        "GET_THERAPEUTIC_USES": (
            f"The records for {subject} connect different plant parts with these "
            "reported conditions and related topics:"
        ),
        "GET_BIOACTIVITY": (f"For {subject}, these are laboratory activity measurements:"),
        "GET_EVIDENCE": (
            f"These are recorded bioactivity and source links for {subject}, not clinical outcomes:"
        ),
        "GET_PROTEIN_TARGETS": f"Compounds in {subject} have these recorded protein-target links:",
        "GET_DOCUMENTS": f"These sources are associated with {subject}:",
    }
    return introductions.get(
        context.intent, f"Here is what the available records show for {subject}:"
    )


def _public_limitation(note: str) -> str:
    """Translate internal retrieval diagnostics into bounded reader-facing context."""
    if note in {"EVIDENCE_UNAVAILABLE", "MAX_ITERATIONS_REACHED"}:
        return "The available records could not fully answer this question."
    if note == "FAILED":
        return "The request could not be completed; please try again."
    if re.fullmatch(r"[A-Z][A-Z_]+", note):
        return "The available records could not fully answer this question."
    if note.startswith("No matching graph records"):
        return (
            "I could not find a matching record for this question; "
            "that does not rule out the claim."
        )
    if note.startswith("Showing at most "):
        return "More records may be available; ask a more specific question to narrow the results."
    if note.startswith("A graph record exceeded"):
        return "An unusually large source record could not be displayed."
    if note.startswith("A path node has no documented"):
        return "Some source details could not be verified."
    if note.startswith("Some bioactivity records have no linked document"):
        return "Some activity entries do not include a linked publication."
    if note.startswith("Conflicting properties for graph identifier"):
        return "Some source details conflict and need verification."
    if note.startswith("No matching") or note.startswith("Plant identity is absent"):
        return "The available records do not answer this question."
    # Unknown internal diagnostics must not be exposed verbatim to the user.
    internal_terms = ("graph", "node", "query", "cypher", "agent", "tool")
    if any(word in note.casefold() for word in internal_terms):
        return "Some source details could not be verified."
    return re.sub(r"\s+", " ", note).strip()[:240]


def limitations(context: ResponseContext, shown: int) -> str:
    notes = list(
        dict.fromkeys(_public_limitation(note) for note in context.uncertainties if note.strip())
    )
    if len(context.graph_evidence) > shown and (
        context.intent != "GET_THERAPEUTIC_USES" or len(context.graph_evidence) > 8
    ):
        notes = [note for note in notes if not note.startswith("More records may be available")]
        narrowing = {
            "GET_PHYTOCHEMICALS": "Ask about a specific compound to narrow the answer.",
            "GET_THERAPEUTIC_USES": (
                "Ask about a specific plant part or reported use to narrow the answer."
            ),
            "GET_PLANT_PARTS": "Ask about a particular part for more detail.",
        }.get(context.intent, "Ask a more specific question to narrow the answer.")
        notes.append("More related information is recorded than shown here. " + narrowing)
    # Routine retrieval diagnostics and ungraded entries do not belong in the
    # default explanation; keep only material incompleteness visible.
    notes = [
        note
        for note in notes
        if note.startswith("More related information")
        or note.startswith("Some source details conflict")
    ]
    if not notes:
        return ""
    return " ".join(notes[:2])


def interpretation(context: ResponseContext) -> str:
    kinds = {item.provenance.reference.partition(":")[0] for item in context.graph_evidence[:8]}
    if kinds <= {"GET_PLANT_PARTS", "GET_PLANT_PART_DETAILS"} and kinds:
        return (
            "These are names of plant parts. Each label tells you which part a related "
            "entry concerns; it does not itself describe a use or an effect."
        )
    if kinds == {"GET_PHYTOCHEMICAL_DETAILS"}:
        return (
            "That classification tells us what kind of compound it is; "
            "it does not tell us how much is present in the plant."
        )
    if kinds == {"GET_PHYTOCHEMICALS"}:
        return (
            "A phytochemical is a chemical found in plants. These entries show where compounds "
            "are recorded, but not how much is present."
        )
    if kinds == {"GET_THERAPEUTIC_USES"}:
        return (
            "These are reported associations, not evidence that the plant treats those conditions. "
            "Terms under ‘related topics’ describe catalog categories rather than illnesses."
            if any(
                isinstance(claim, dict)
                and _value(claim, "mesh_category_name").casefold()
                not in {"", "diseases", "anatomy"}
                for item in context.graph_evidence[:8]
                for claim in [_safe_claim(item.claim)]
            )
            else (
                "These are reported associations, not proof that the plant treats those conditions."
            )
        )
    if (
        kinds <= {"GET_BIOACTIVITY", "GET_EVIDENCE", "GET_PHYTOCHEMICAL_DETAILS"}
        and kinds
        and ("GET_BIOACTIVITY" in kinds or "GET_EVIDENCE" in kinds)
    ):
        metrics = {
            _value(_safe_claim(item.claim), "standard_type").upper()
            for item in context.graph_evidence[:8]
        }
        metric_help = []
        if "IC50" in metrics:
            metric_help.append("IC50 marks 50% inhibition in a particular test")
        if "KI" in metrics:
            metric_help.append("Ki is a binding or inhibition measure")
        if "POTENCY" in metrics:
            metric_help.append("Potency is another assay response measure")
        definitions = "; ".join(metric_help)
        has_target = any(_node(item, "target_name") for item in context.graph_evidence[:8])
        target_context = (
            "Each protein name is a laboratory target, not a condition the plant treats. "
            if has_target
            else "These are laboratory tests of compound activity. "
        )
        units_context = (
            "The nM values are concentrations measured in different tests. "
            if any(
                _value(_safe_claim(item.claim), "standard_units").casefold() == "nm"
                for item in context.graph_evidence[:8]
            )
            else "Measurements from different assays are not directly comparable. "
        )
        return (
            target_context
            + (definitions + ". " if definitions else "")
            + units_context
            + "They do not show whether the plant helps a person."
        )
    if kinds == {"GET_PROTEIN_TARGETS"}:
        return (
            "What this means: a target link is a recorded association, "
            "not proof of an effect in a person."
        )
    if kinds == {"GET_DOCUMENTS"}:
        return (
            "What this means: a document link provides provenance, "
            "but does not by itself establish study quality or clinical efficacy."
        )
    return ""
