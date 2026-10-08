from uuid import uuid4

import pytest

from backend.agents.graph.agent import GraphAgent
from backend.agents.image.agent import ImageAgent
from backend.agents.text.agent import TextAgent
from backend.config.settings import Settings
from backend.contracts.agents import CandidatePlant
from backend.database.memory import MemorySessionRepository
from backend.llm.provider import PlaceholderProvider
from backend.orchestrator.decision import DecisionEngine
from backend.orchestrator.execution import ExecutionManager
from backend.orchestrator.orchestrator import Harness
from backend.orchestrator.policy import EligibilityPolicy
from backend.services.conversations import ConversationService
from backend.state.models import ConversationState
from backend.trace.recorder import MemoryTraceSink, TraceRecorder


@pytest.fixture
def state():
    value = ConversationState.new()
    value.correlation.turn_id = uuid4()
    value.correlation.run_id = uuid4()
    return value


@pytest.fixture
def plant():
    # Synthetic fixture identifiers, never installed as a real plant knowledge base.
    return CandidatePlant(plant_id="fixture:A", label="Fixture plant A", confidence=0.98)


@pytest.fixture
def harness():
    return Harness(
        DecisionEngine(EligibilityPolicy()),
        ExecutionManager(TextAgent(), ImageAgent(), GraphAgent()),
        PlaceholderProvider(),
        TraceRecorder(MemoryTraceSink()),
    )


@pytest.fixture
def service(harness):
    return ConversationService(MemorySessionRepository(), harness, Settings(_env_file=None))
