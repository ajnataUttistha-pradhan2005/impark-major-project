from typing import Protocol, TypeVar

from backend.contracts.agents import Failure, Observation

InputT = TypeVar("InputT", contravariant=True)


class Agent(Protocol[InputT]):
    async def execute(self, request: InputT) -> Observation | Failure: ...
