from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.agents.graph.agent import GraphAgent
from backend.agents.image.agent import ImageAgent
from backend.contracts.actions import Action, ActionName, Capability
from backend.contracts.agents import (
    GraphAgentInput,
    GraphParameters,
    GraphQuery,
    ImageAgentInput,
    ImageMetadata,
    ImageReference,
    Observation,
    QueryType,
    TextResult,
)


async def test_graph_placeholder_has_no_fake_evidence(state, harness):
    invocation = harness.execution.invocation(state, Action(name=ActionName.RETRIEVE_GRAPH))
    request = GraphAgentInput(
        invocation=invocation,
        query=GraphQuery(
            query_type=QueryType.GET_PLANT_DETAILS,
            parameters=GraphParameters(plant_id="fixture:A"),
        ),
    )
    before = request.model_dump_json()
    output = await GraphAgent().execute(request)
    assert isinstance(output, Observation)
    assert output.payload.placeholder
    assert output.payload.evidence == []
    assert request.model_dump_json() == before
    assert output.invocation.correlation.agent_invocation_id is not None


async def test_image_placeholder_has_no_fake_classification(state, harness):
    invocation = harness.execution.invocation(state, Action(name=ActionName.ANALYZE_IMAGE))
    reference = ImageReference(
        image_id=uuid4(),
        metadata=ImageMetadata(
            mime_type="image/png",
            width=10,
            height=10,
            size_bytes=100,
        ),
    )
    output = await ImageAgent().execute(ImageAgentInput(invocation=invocation, image=reference))
    assert output.payload.placeholder
    assert output.payload.candidates == []
    assert not output.payload.quality.checked


def test_placeholder_predictions_rejected(state, plant, harness):
    invocation = harness.execution.invocation(state, Action(name=ActionName.RESOLVE_TEXT_ENTITY))
    with pytest.raises(ValidationError):
        Observation(
            invocation=invocation,
            component=Capability.TEXT,
            payload=TextResult(candidates=[plant], placeholder=True),
        )
