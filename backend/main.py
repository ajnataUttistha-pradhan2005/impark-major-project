from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from backend.agents.graph.agent import GraphAgent
from backend.agents.image.agent import ImageAgent
from backend.agents.text.agent import TextAgent
from backend.api.middleware import CorrelationMiddleware, configure_logging
from backend.api.routes import conversations, images
from backend.api.schemas.chat import ErrorResponse
from backend.config.settings import Settings
from backend.database.memory import MemorySessionRepository
from backend.llm.provider import PlaceholderProvider
from backend.orchestrator.decision import DecisionEngine
from backend.orchestrator.execution import ExecutionManager
from backend.orchestrator.orchestrator import Harness
from backend.orchestrator.policy import EligibilityPolicy
from backend.services.conversations import ConversationService
from backend.services.errors import ServiceError
from backend.trace.recorder import MemoryTraceSink, TraceRecorder


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    recorder = TraceRecorder(MemoryTraceSink(), config.trace_buffer_size)
    harness = Harness(
        DecisionEngine(EligibilityPolicy(config.entity_auto_resolve_threshold)),
        ExecutionManager(TextAgent(), ImageAgent(), GraphAgent()),
        PlaceholderProvider(),
        recorder,
    )
    service = ConversationService(MemorySessionRepository(), harness, config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        recorder.start()
        yield
        await recorder.close(config.trace_shutdown_seconds)

    app = FastAPI(title="IMPARK foundation", version="0.1.0", lifespan=lifespan)
    app.state.settings = config
    app.state.conversations = service
    app.state.trace_recorder = recorder
    app.add_middleware(CorrelationMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Correlation-ID"],
    )

    def error(request: Request, code: str, message: str, status: int) -> JSONResponse:
        body = ErrorResponse(
            code=code, message=message, correlation_id=request.state.correlation_id
        )
        return JSONResponse(
            body.model_dump(mode="json"),
            status_code=status,
            headers={"X-Correlation-ID": str(request.state.correlation_id)},
        )

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return error(request, exc.code, exc.message, exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic errors can contain submitted values; do not echo them.
        return error(request, "VALIDATION_ERROR", "Request validation failed", 422)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        return error(request, "INTERNAL_ERROR", "Request could not be completed", 500)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "storage": "development-memory", "agents": "placeholders"}

    app.include_router(conversations.router)
    app.include_router(images.router)
    return app


app = create_app()
