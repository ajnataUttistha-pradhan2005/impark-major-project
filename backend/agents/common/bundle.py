"""Optional typed capability injection at the application composition boundary."""

from dataclasses import dataclass

from backend.agents.common.contracts import Agent
from backend.agents.common.services import SpecialistServices
from backend.contracts.agents import GraphAgentInput, ImageAgentInput, TextAgentInput


@dataclass(frozen=True)
class AgentOverrides:
    text: Agent[TextAgentInput] | None = None
    image: Agent[ImageAgentInput] | None = None
    graph: Agent[GraphAgentInput] | None = None

    def install(self, execution: SpecialistServices) -> None:
        if self.text is not None:
            execution.text = self.text
        if self.image is not None:
            execution.image = self.image
        if self.graph is not None:
            execution.graph = self.graph
