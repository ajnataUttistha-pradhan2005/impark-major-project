from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.api.schemas.chat import ChatRequest
from backend.contracts.agents import GraphParameters, GraphQuery, QueryType
from backend.contracts.response import FinalResponseRequest, ResponseContext
from backend.state.models import ConversationState, SessionMode


def test_state_defaults_and_independent_collections():
    a, b = ConversationState.new(), ConversationState.new()
    assert a.session.mode == SessionMode.DISCOVERY
    assert a.session.session_id == a.correlation.session_id
    a.context.active_compounds.append("fixture:compound")
    assert b.context.active_compounds == []
    assert ConversationState.model_validate_json(a.model_dump_json()) == a


@pytest.mark.parametrize("payload", [{}, {"text": "  "}, {"text": "a", "action": "RETRIEVE_GRAPH"}])
def test_invalid_chat(payload):
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(payload)


def test_image_only_and_trimmed_text():
    assert ChatRequest(image_id=uuid4()).text is None
    assert ChatRequest(text=" a ").text == "a"


@pytest.mark.parametrize(
    "change",
    [
        {"cypher": "MATCH (n) DELETE n"},
        {"query_type": "RAW_CYPHER"},
        {"limit": 101},
        {"timeout_seconds": 31},
        {"read_only": False},
        {"parameters": {"plant_id": "x' MATCH (n) DELETE n"}},
    ],
)
def test_graph_rejects_unsafe_queries(change):
    data = {"query_type": "GET_PLANT_DETAILS", "parameters": {"plant_id": "fixture:A"}}
    data.update(change)
    with pytest.raises(ValidationError):
        GraphQuery.model_validate(data)


def test_graph_required_scope():
    with pytest.raises(ValidationError):
        GraphQuery(query_type=QueryType.COMPARE_PLANTS, parameters=GraphParameters(plant_id="A"))


def test_final_request_has_context_only():
    assert set(FinalResponseRequest.model_fields) == {"response_context"}
    with pytest.raises(ValidationError):
        FinalResponseRequest.model_validate(
            {
                "response_context": ResponseContext(intent="test", outcome="test").model_dump(),
                "database": "not permitted",
            }
        )
