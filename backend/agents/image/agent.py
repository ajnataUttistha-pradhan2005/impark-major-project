from backend.contracts.actions import Capability
from backend.contracts.agents import ImageAgentInput, ImageAgentResult, Observation


class ImageAgent:
    """TODO: quality/gate -> pretrained custom CNN -> ranking/calibration/part.

    No synthetic candidates are presented as real predictions.
    """

    async def execute(self, request: ImageAgentInput) -> Observation:
        return Observation(
            invocation=request.invocation,
            component=Capability.IMAGE,
            payload=ImageAgentResult(),
        )
