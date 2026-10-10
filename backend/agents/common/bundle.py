"""Optional typed capability injection at the application composition boundary."""

from dataclasses import dataclass

from backend.agents.common.contracts import Agent
from backend.contracts.agents import GraphAgentInput, ImageAgentInput, TextAgentInput
from backend.orchestrator.execution import ExecutionManager


@dataclass(frozen=True)
class AgentOverrides:
    text: Agent[TextAgentInput] | None = None
    image: Agent[ImageAgentInput] | None = None
    graph: Agent[GraphAgentInput] | None = None

    def install(self, execution: ExecutionManager) -> None:
        if self.text is not None:
            execution.text = self.text
        if self.image is not None:
            execution.image = self.image
        if self.graph is not None:
            execution.graph = self.graph
