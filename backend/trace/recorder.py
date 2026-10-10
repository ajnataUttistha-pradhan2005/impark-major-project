import asyncio
import logging
from contextlib import suppress
from typing import Protocol

from backend.trace.models import TraceEvent


class TraceSink(Protocol):
    async def write(self, event: TraceEvent) -> None: ...


class MemoryTraceSink:
    """Bounded development sink; not durable PostgreSQL storage."""

    def __init__(self, capacity: int = 10000) -> None:
        self.events: list[TraceEvent] = []
        self.capacity = capacity

    async def write(self, event: TraceEvent) -> None:
        if len(self.events) >= self.capacity:
            del self.events[0]
        self.events.append(event)


class TraceRecorder:
    """Provisional drop-newest overflow; failures affect counters, never domain state."""

    def __init__(self, sink: TraceSink, capacity: int = 1024) -> None:
        self.sink = sink
        self.queue: asyncio.Queue[TraceEvent] = asyncio.Queue(maxsize=capacity)
        self.dropped = 0
        self.write_failures = 0
        self.worker: asyncio.Task[None] | None = None
        self.in_flight = False

    def emit(self, event: TraceEvent) -> None:
        try:
            self.queue.put_nowait(event.model_copy(deep=True))
        except asyncio.QueueFull:
            self.dropped += 1

    def start(self) -> None:
        if self.worker is None:
            self.worker = asyncio.create_task(self._write_loop())

    async def _write_loop(self) -> None:
        while True:
            event = await self.queue.get()
            self.in_flight = True
            try:
                await self.sink.write(event)
            except Exception:
                # Intentional isolation boundary; never log exception text/credentials.
                self.write_failures += 1
                logging.getLogger(__name__).warning("trace_write_failed")
            finally:
                self.in_flight = False
                self.queue.task_done()

    async def close(self, grace_seconds: float = 1) -> None:
        if self.worker is None:
            return
        try:
            async with asyncio.timeout(grace_seconds):
                await self.queue.join()
        except TimeoutError:
            self.dropped += self.queue.qsize() + int(self.in_flight)
        self.worker.cancel()
        with suppress(asyncio.CancelledError):
            await self.worker
        self.worker = None
