import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from langgraph.checkpoint.memory import InMemorySaver
from starlette.middleware.cors import CORSMiddleware

from backend.agents.common.bundle import AgentOverrides
from backend.agents.common.services import SpecialistServices
from backend.agents.graph.agent import GraphAgent
from backend.agents.graph.retrieval import PlantGraphRetrieval
from backend.agents.image.agent import ImageAgent
from backend.agents.image.inference import ImageInference
from backend.agents.image.model import XceptionModel
from backend.agents.image.retrieval import ImageVectorStore
from backend.agents.text.agent import TextAgent
from backend.agents.text.embeddings import FastEmbedProvider
from backend.agents.text.search import HybridNameSearch
from backend.api.middleware import CorrelationMiddleware, configure_logging
from backend.api.routes import conversations, images, platform
from backend.api.schemas.chat import ErrorResponse
from backend.config.settings import Settings
from backend.database.memory import MemorySessionRepository
from backend.database.neo4j.client import Neo4jClient
from backend.database.neo4j.driver import Neo4jConnection
from backend.database.neo4j.errors import GraphDatabaseError
from backend.database.neo4j.medicinal import MedicinalPlantRepository
from backend.database.postgres.chat import ChatStore
from backend.database.postgres.checkpoints import checkpoints
from backend.database.postgres.client import PostgresClient, StoreError
from backend.database.postgres.persistence import PostgresSessionRepository, PostgresTraceSink
from backend.database.postgres.search import PostgresNameRepository
from backend.database.qdrant.client import QdrantStore
from backend.orchestrator.deepagents.graph import build_deep_graph
from backend.orchestrator.deepagents.host import AgentHost
from backend.orchestrator.deepagents.models import AgentModelFactory
from backend.orchestrator.deepagents.runtime import DeepAgentRuntime
from backend.services.conversations import ConversationService
from backend.services.errors import ServiceError
from backend.services.runs import RunManager
from backend.trace.recorder import MemoryTraceSink, TraceRecorder


def create_app(settings: Settings | None = None, agents: AgentOverrides | None = None) -> FastAPI:
    # Pydantic Settings uses python-dotenv for .env without mutating process environment.
    config = settings or Settings()
    recorder = TraceRecorder(MemoryTraceSink(), config.trace_buffer_size)
    execution = SpecialistServices(TextAgent(), ImageAgent(), GraphAgent())
    harness = AgentHost(execution, recorder)
    service = ConversationService(MemorySessionRepository(), harness, config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        connection: Neo4jConnection | None = None
        postgres: PostgresClient | None = None
        vectors: QdrantStore | None = None
        image_vectors: ImageVectorStore | None = None
        runs: RunManager | None = None
        lease = None
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
                lease = await postgres.pool.acquire()
                if not await lease.fetchval("SELECT pg_try_advisory_lock(72421003)"):
                    raise RuntimeError("Use one backend process for this demo database")
                await postgres.scalar("SELECT count(*) FROM api_operation")
                saver = await stack.enter_async_context(checkpoints(config))
                # Read-only readiness check: run search_admin migrate explicitly first.
                await postgres.scalar("SELECT count(*) FROM checkpoint_migrations")
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
                if config.image_enabled:
                    image_model = XceptionModel(
                        config.image_model_path or "",
                        config.image_classes_path or "",
                        config.image_threads,
                    )
                    await asyncio.to_thread(image_model.load)
                    image_vectors = ImageVectorStore(config)
                    image_provider = ImageInference(
                        config, image_model, image_vectors, postgres, search
                    )
                    await image_provider.open()
                    harness.execution.image = ImageAgent(image_provider)
                    app.state.image_provider = image_provider
                if app.state.neo4j:
                    harness.execution.graph = GraphAgent(
                        PlantGraphRetrieval(app.state.neo4j, postgres)
                    )
                service.repository = PostgresSessionRepository(postgres)
                recorder.sink = PostgresTraceSink(postgres)
                app.state.postgres = postgres
                app.state.qdrant = vectors
                runs = RunManager(service, ChatStore(postgres))
                await runs.store.interrupt_stale()
                app.state.runs = runs
            recorder.start()
            if agents is not None:
                agents.install(harness.execution)
            runtime = DeepAgentRuntime(harness, AgentModelFactory(config), config)
            checkpoint = saver if config.text_search_enabled else InMemorySaver()
            service.graph = build_deep_graph(runtime, checkpoint)
            yield
        finally:
            if runs is not None:
                await runs.close()
            await recorder.close(config.trace_shutdown_seconds)
            await stack.aclose()
            if vectors is not None:
                await vectors.close()
            if image_vectors is not None:
                await image_vectors.close()
            if postgres is not None:
                if lease is not None:
                    await lease.execute("SELECT pg_advisory_unlock(72421003)")
                    await postgres.pool.release(lease)
                await postgres.close()
            if connection is not None:
                await connection.close()

    app = FastAPI(title="IMPARK medicinal plant chat API", version="0.1.0", lifespan=lifespan)
    app.state.settings = config
    app.state.conversations = service
    app.state.trace_recorder = recorder
    app.state.neo4j = None
    app.state.plant_repository = None
    app.state.postgres = None
    app.state.qdrant = None
    app.state.runs = None
    app.state.response_model = None
    app.state.image_provider = None
    app.add_middleware(CorrelationMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Correlation-ID", "Authorization", "Last-Event-ID"],
        expose_headers=["X-Correlation-ID"],
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
                "agents": "text-image-graph"
                if app.state.image_provider
                else "text-and-graph; image-placeholder",
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
    app.include_router(platform.router)

    @app.get("/health/llm")
    async def llm_health() -> JSONResponse:
        healthy = bool(config.agent_main_model or config.llm_model)
        return JSONResponse(
            {
                "status": "configured" if healthy else "unavailable",
                "provider": config.agent_main_model_provider,
                "model": config.agent_main_model or config.llm_model,
            },
            status_code=200 if healthy else 503,
        )

    return app


app = create_app()
