"""Mutable specialist bindings installed at application startup."""

from dataclasses import dataclass

from backend.agents.common.contracts import Agent
from backend.contracts.agents import GraphAgentInput, ImageAgentInput, TextAgentInput


@dataclass
class SpecialistServices:
    text: Agent[TextAgentInput]
    image: Agent[ImageAgentInput]
    graph: Agent[GraphAgentInput]
