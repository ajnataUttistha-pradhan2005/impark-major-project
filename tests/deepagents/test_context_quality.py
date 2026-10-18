import json
from uuid import uuid4

from backend.contracts.evidence import Evidence, Modality, Provenance
from backend.orchestrator.deepagents.context import (
    build_turn_prompt,
    effective_question,
    named_fact,
)
from backend.orchestrator.deepagents.response_quality import (
    attach_record_citations,
    clean_plaintext_math,
    is_unfinished_plan,
    needs_scientific_repair,
)
from backend.state.models import ConversationState, DialogueTurn


def test_follow_up_acknowledgment_keeps_last_substantive_request():
    state = ConversationState.new()
    item = Evidence(
        modality=Modality.GRAPH,
        claim=json.dumps({"phytochemical_name": "Trigonelline"}),
        confidence=1,
        provenance=Provenance(
            source_id=str(uuid4()), source_type="neo4j", reference="GET_PHYTOCHEMICALS"
        ),
    )
    state.context.recent_dialogue = [
        DialogueTurn(question="List the compounds", answer="The records name A and B."),
        DialogueTurn(
            question="Explain each of them",
            answer="I will look up details for A and B.",
            citation_ids=[item.evidence_id],
        ),
    ]
    state.user_message = "sure go on"
    state.context.citation_history = [item]
    state.context.focus_entities = ["Trigonelline"]
    payload = build_turn_prompt(state).splitlines()[1]
    context = json.loads(payload)
    assert context["follow_up_anchor"] == "Explain each of them"
    assert context["recent_dialogue"][0]["answer"] == "The records name A and B."
    assert context["previous_named_items"] == ["Trigonelline"]


def test_retry_anchors_only_immediately_previous_topic_without_stale_facts():
    state = ConversationState.new()
    old = Evidence(
        modality=Modality.GRAPH,
        claim=json.dumps({"phytochemical_name": "Old compound"}),
        confidence=1,
        provenance=Provenance(source_id="old", source_type="neo4j", reference="GET_PHYTOCHEMICALS"),
    )
    state.context.citation_history = [old]
    state.context.recent_dialogue = [
        DialogueTurn(
            question="List compounds", answer="Old compound", citation_ids=[old.evidence_id]
        ),
        DialogueTurn(question="What are its other names?", answer="No names found"),
    ]
    state.user_message = "try again"
    payload = json.loads(build_turn_prompt(state).splitlines()[1])
    assert effective_question(state) == "What are its other names?"
    assert payload["previous_verified_facts"] == []
    assert payload["previous_named_items"] == []


def test_math_cleanup_and_unfinished_plan_detection():
    assert clean_plaintext_math(r"A $\text{Ki}$ of 0.8 nM") == "A Ki of 0.8 nM"
    assert clean_plaintext_math(r"$\mathrm{IC50}$") == "IC50"
    assert clean_plaintext_math(
        "The question asks about the locked plant.\n\nIn plants generally, light affects leaves."
    ) == "In plants generally, light affects leaves."
    assert is_unfinished_plan("I will use the knowledge graph to look this up.")
    assert not is_unfinished_plan("In plants generally, leaf shape reflects growth conditions.")
    assert needs_scientific_repair("Treating diabetes [1].")
    assert needs_scientific_repair("A HIGH confidence tier measurement was recorded.")
    assert needs_scientific_repair(
        "This suggests the plant may possess compounds that interfere with viruses."
    )
    assert needs_scientific_repair("The plant has been studied for this disease.")
    assert not needs_scientific_repair("This is not proof that the plant treats diabetes.")


def test_follow_up_cites_recorded_name_without_inventing_a_source():
    item = Evidence(
        modality=Modality.GRAPH,
        claim=json.dumps({"phytochemical_name": "Trigonelline"}),
        confidence=1,
        provenance=Provenance(
            source_id=str(uuid4()), source_type="neo4j", reference="GET_PHYTOCHEMICALS"
        ),
    )
    answer = attach_record_citations(
        "**Trigonelline**: In general, alkaloids contain nitrogen.",
        ["Trigonelline"],
        [item],
    )
    assert answer.startswith(f"**Trigonelline** [{item.evidence_id}]:")
    assert attach_record_citations(answer, ["Trigonelline"], [item]) == answer
    use = item.model_copy(
        update={
            "evidence_id": uuid4(),
            "claim": json.dumps(
                {"mesh_category_name": "Diseases", "therapeutic_use": "Common cold"}
            ),
        }
    )
    assert named_fact(use) == "Common cold"
    linked = attach_record_citations("**common cold** is listed.", ["Common cold"], [use])
    assert f"**common cold** [{use.evidence_id}]" in linked
