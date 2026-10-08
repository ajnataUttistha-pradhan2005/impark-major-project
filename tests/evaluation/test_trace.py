from backend.evaluation.models import iteration_snapshots
from backend.trace.instrumentation import emit_state
from backend.trace.models import EventType
from backend.trace.recorder import MemoryTraceSink, TraceRecorder


async def test_trace_snapshot_lineage_and_privacy(state):
    state.user_message = "sensitive-user-text"
    sink = MemoryTraceSink()
    recorder = TraceRecorder(sink)
    recorder.start()
    emit_state(recorder, state, EventType.TURN_STARTED)
    state.iteration = 1
    emit_state(recorder, state, EventType.STATE_SNAPSHOT)
    await recorder.close()
    reconstructed = iteration_snapshots(sink.events, state.correlation.run_id)
    assert [e.correlation.iteration for e in reconstructed] == [0, 1]
    assert all("sensitive-user-text" not in e.model_dump_json() for e in reconstructed)
