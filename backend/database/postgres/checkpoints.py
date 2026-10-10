"""Official LangGraph checkpoint lifecycle; schema setup is an explicit admin action."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import Enum

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.conninfo import make_conninfo
from pydantic import BaseModel

from backend.contracts import actions, agents, base, evidence, response
from backend.database.postgres.client import StoreError
from backend.database.search_config import SearchSettings
from backend.state import goals, models


def checkpoint_serializer() -> JsonPlusSerializer:
    # Only application contracts may be reconstructed; never enable pickle fallback.
    allowed = [
        (value.__module__, value.__name__)
        for module in (actions, agents, base, evidence, response, goals, models)
        for value in vars(module).values()
        if isinstance(value, type)
        and issubclass(value, (BaseModel, Enum))
        and value.__module__ == module.__name__
    ]
    return JsonPlusSerializer(allowed_msgpack_modules=allowed, pickle_fallback=False)


@asynccontextmanager
async def checkpoints(config: SearchSettings) -> AsyncIterator[AsyncPostgresSaver]:
    if config.database_url is None:
        raise StoreError("CONFIGURATION")
    # A reusable dedicated checkpoint connection, owned by this lifespan.
    async with AsyncPostgresSaver.from_conn_string(
        make_conninfo(
            config.database_url.get_secret_value(),
            connect_timeout=max(1, int(config.store_timeout_seconds)),
            options=f"-c statement_timeout={int(config.store_timeout_seconds * 1000)}",
        ),
        serde=checkpoint_serializer(),
    ) as saver:
        yield saver
