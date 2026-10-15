from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from backend.api.routes.platform import events
from backend.api.schemas.platform import StreamEvent


async def test_completion_committing_between_batch_and_status_is_not_lost():
    oid = uuid4()
    final = StreamEvent(operation_id=oid, sequence=1, type="run_completed", payload={})
    store = SimpleNamespace(
        operation=AsyncMock(return_value={"status": "complete"}),
        events=AsyncMock(side_effect=[[], [final], [], []]),
        client=SimpleNamespace(scalar=AsyncMock(return_value=1)),
    )
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))
    response = await events(oid, request, SimpleNamespace(store=store), 0, None)
    frames = [frame async for frame in response.body_iterator]
    assert len(frames) == 1
    assert "run_completed" in frames[0]
