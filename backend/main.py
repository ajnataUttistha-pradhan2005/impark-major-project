from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from backend.agents.common.bundle import AgentOverrides
from backend.agents.graph.agent import GraphAgent
from backend.agents.graph.retrieval import PlantGraphRetrieval
from backend.agents.image.agent import ImageAgent
from backend.agents.text.agent import TextAgent
from backend.agents.text.embeddings import FastEmbedProvider
from backend.agents.text.search import HybridNameSearch
from backend.api.middleware import CorrelationMiddleware, configure_logging
from backend.api.routes import conversations, images
from backend.api.schemas.chat import ErrorResponse
from backend.config.settings import Settings
from backend.database.memory import MemorySessionRepository
from backend.database.neo4j.client import Neo4jClient
from backend.database.neo4j.driver import Neo4jConnection
from backend.database.neo4j.errors import GraphDatabaseError
from backend.database.neo4j.medicinal import MedicinalPlantRepository
from backend.database.postgres.checkpoints import checkpoints
from backend.database.postgres.client import PostgresClient, StoreError
from backend.database.postgres.persistence import PostgresSessionRepository, PostgresTraceSink
from backend.database.postgres.search import PostgresNameRepository
from backend.database.qdrant.client import QdrantStore
from backend.llm.grounded import GroundedResponseProvider
from backend.llm.provider import PlaceholderProvider
from backend.orchestrator.decision import DecisionEngine
from backend.orchestrator.execution import ExecutionManager
from backend.orchestrator.graph import build_graph
from backend.orchestrator.orchestrator import Harness
from backend.orchestrator.policy import EligibilityPolicy
from backend.services.conversations import ConversationService
from backend.services.errors import ServiceError
from backend.trace.recorder import MemoryTraceSink, TraceRecorder


def create_app(settings: Settings | None = None, agents: AgentOverrides | None = None) -> FastAPI:
    # Pydantic Settings uses python-dotenv for .env without mutating process environment.
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
        connection: Neo4jConnection | None = None
        postgres: PostgresClient | None = None
        vectors: QdrantStore | None = None
        stack = AsyncExitStack()
        try:
            if config.neo4j_enabled:
                connection = Neo4jConnection(config.connection_config())
                await connection.open()
                client = Neo4jClient(connection)
                app.state.neo4j = client
                app.state.plant_repository = MedicinalPlantRepository(
                    client, min(5, connection.config.transaction_timeout_seconds)
                )
            if config.text_search_enabled:
                postgres = PostgresClient(config)
                await postgres.open()
                saver = await stack.enter_async_context(checkpoints(config))
                # Read-only readiness check: run search_admin migrate explicitly first.
                await postgres.scalar("SELECT count(*) FROM checkpoint_migrations")
                service.graph = build_graph(harness, saver)
                names = PostgresNameRepository(postgres)
                await names.generation()  # Fail early if the explicit migration/import was omitted.
                embeddings = None
                if config.text_semantic_enabled:
                    vectors = QdrantStore(config)
                    import logging

                    import httpx
                    from qdrant_client.http.exceptions import (
                        ResponseHandlingException,
                        UnexpectedResponse,
                    )

                    try:
                        await vectors.validate()
                    except (httpx.HTTPError, ResponseHandlingException, UnexpectedResponse):
                        logging.getLogger(__name__).warning("semantic_store_unavailable")
                    embeddings = FastEmbedProvider(config)
                search = HybridNameSearch(names, vectors, embeddings)
                await search.catalog()
                harness.execution.text = TextAgent(search)
                if app.state.neo4j:
                    harness.execution.graph = GraphAgent(
                        PlantGraphRetrieval(app.state.neo4j, postgres)
                    )
                harness.llm = GroundedResponseProvider()
                service.repository = PostgresSessionRepository(postgres)
                recorder.sink = PostgresTraceSink(postgres)
                app.state.postgres = postgres
                app.state.qdrant = vectors
            recorder.start()
            if agents is not None:
                agents.install(harness.execution)
            yield
        finally:
            await recorder.close(config.trace_shutdown_seconds)
            await stack.aclose()
            if vectors is not None:
                await vectors.close()
            if postgres is not None:
                await postgres.close()
            if connection is not None:
                await connection.close()

    app = FastAPI(title="IMPARK foundation", version="0.1.0", lifespan=lifespan)
    app.state.settings = config
    app.state.conversations = service
    app.state.trace_recorder = recorder
    app.state.neo4j = None
    app.state.plant_repository = None
    app.state.postgres = None
    app.state.qdrant = None
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
        if config.text_search_enabled:
            return {
                "status": "ok",
                "storage": "postgres",
                "agents": "text-and-graph; image-placeholder",
            }
        return {"status": "ok", "storage": "development-memory", "agents": "placeholders"}

    @app.get("/health/postgres")
    async def postgres_health() -> JSONResponse:
        try:
            healthy = app.state.postgres is not None and await app.state.postgres.health()
        except StoreError:
            healthy = False
        return JSONResponse(
            {"status": "ok" if healthy else "unavailable"}, status_code=200 if healthy else 503
        )

    @app.get("/health/qdrant")
    async def qdrant_health() -> JSONResponse:
        import httpx
        from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

        try:
            healthy = app.state.qdrant is not None and await app.state.qdrant.health()
        except (httpx.HTTPError, ResponseHandlingException, UnexpectedResponse):
            healthy = False
        return JSONResponse(
            {"status": "ok" if healthy else "unavailable"}, status_code=200 if healthy else 503
        )

    @app.get("/health/neo4j")
    async def neo4j_health() -> JSONResponse:
        if app.state.neo4j is None:
            return JSONResponse({"status": "disabled"}, status_code=503)
        try:
            healthy = await app.state.neo4j.health()
            return JSONResponse(
                {"status": "ok" if healthy else "unavailable"}, status_code=200 if healthy else 503
            )
        except GraphDatabaseError:
            return JSONResponse({"status": "unavailable"}, status_code=503)

    app.include_router(conversations.router)
    app.include_router(images.router)
    return app


app = create_app()
