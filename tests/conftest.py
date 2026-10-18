import asyncio
from uuid import uuid4

import pytest

from backend.agents.common.services import SpecialistServices
from backend.agents.graph.agent import GraphAgent
from backend.agents.image.agent import ImageAgent
from backend.agents.text.agent import TextAgent
from backend.config.settings import Settings
from backend.contracts.agents import CandidatePlant
from backend.database.memory import MemorySessionRepository
from backend.orchestrator.deepagents.host import AgentHost
from backend.services.conversations import ConversationService
from backend.state.models import ConversationState
from backend.trace.recorder import MemoryTraceSink, TraceRecorder


def pytest_asyncio_loop_factories(config, item):
    return {"selector": asyncio.SelectorEventLoop}


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
    return AgentHost(
        SpecialistServices(TextAgent(), ImageAgent(), GraphAgent()),
        TraceRecorder(MemoryTraceSink()),
    )


@pytest.fixture
def service(harness):
    return ConversationService(MemorySessionRepository(), harness, Settings(_env_file=None))
