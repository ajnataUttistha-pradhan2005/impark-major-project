"""Optional routing of otherwise unknown locked-plant questions to the response layer."""

from backend.agents.text.agent import TextAgent
from backend.agents.text.providers import EntitySearchProvider
from backend.contracts.agents import (
    Failure,
    GraphParameters,
    GraphQuery,
    Observation,
    QueryType,
    TextAgentInput,
    TextResult,
)


class OpenPlantQuestionTextAgent:
    def __init__(self, delegate: TextAgent) -> None:
        self.delegate = delegate

    @property
    def provider(self) -> EntitySearchProvider | None:
        """Expose the unchanged search provider to discovery/autocomplete callers."""
        return self.delegate.provider

    async def execute(self, request: TextAgentInput) -> Observation | Failure:
        result = await self.delegate.execute(request)
        if not isinstance(result, Observation) or not isinstance(result.payload, TextResult):
            return result
        payload = result.payload
        if (
            request.active_plant is not None
            and payload.intent_uncertain
            and not payload.scope_rejected
            and not payload.safety_abstention
            and not payload.queries
        ):
            plant_id = request.active_plant.plant_id
            result.payload = payload.model_copy(
                update={
                    "intent": QueryType.GET_PLANT_DETAILS.value,
                    "query_types": [QueryType.GET_PLANT_DETAILS],
                    "queries": [GraphQuery(
                        query_type=QueryType.GET_PLANT_DETAILS,
                        parameters=GraphParameters(plant_id=plant_id),
                    )],
                    "needs_clarification": False,
                    "intent_uncertain": False,
                    "clarification_question": None,
                    "stages": [*payload.stages, "open_plant_question"],
                }
            )
        return result
