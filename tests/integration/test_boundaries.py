import asyncio
import io

import pytest
from PIL import Image

from backend.agents.image.preprocessing import validate_image
from backend.trace.models import EventType, TraceEvent
from backend.trace.recorder import TraceRecorder


async def test_image_content_validation():
    content = io.BytesIO()
    Image.new("RGB", (10, 10)).save(content, format="PNG")
    raw = content.getvalue()
    assert (await validate_image(raw, "image/png")).width == 10
    for data, mime in [(b"garbage", "image/png"), (raw, "image/jpeg"), (raw, "text/plain")]:
        with pytest.raises(ValueError):
            await validate_image(data, mime)
    with pytest.raises(ValueError):
        await validate_image(raw, "image/png", max_bytes=1)
    with pytest.raises(ValueError):
        await validate_image(raw, "image/png", max_pixels=50)


async def test_trace_slow_sink_does_not_block(state):
    gate = asyncio.Event()

    class SlowSink:
        async def write(self, event):
            await gate.wait()

    recorder = TraceRecorder(SlowSink(), capacity=1)
    event = TraceEvent(correlation=state.correlation, event_type=EventType.TURN_STARTED)
    recorder.emit(event)
    recorder.emit(event)
    assert recorder.dropped == 1
    recorder.start()
    await asyncio.sleep(0)
    recorder.emit(event)
    assert recorder.queue.qsize() == 1
    gate.set()
    await recorder.close()


async def test_trace_failure_is_isolated(state):
    class BrokenSink:
        async def write(self, event):
            raise RuntimeError("sensitive dependency detail")

    recorder = TraceRecorder(BrokenSink())
    recorder.start()
    recorder.emit(TraceEvent(correlation=state.correlation, event_type=EventType.TURN_STARTED))
    await recorder.close()
    assert recorder.write_failures == 1


async def test_memory_repository_copies_state(service):
    from uuid import uuid4

    created = await service.create(uuid4())
    state = await service.load(created.correlation.session_id)
    state.user_message = "mutated"
    assert (await service.load(created.correlation.session_id)).user_message == ""
