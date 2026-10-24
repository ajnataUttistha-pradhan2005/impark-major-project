"""Standalone FastAPI application and router for evaluation service."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from evaluation.config import EvaluationConfig
from evaluation.loader import InMemoryEvaluationLoader, PostgresEvaluationLoader
from evaluation.models import EvaluationResult, GroundTruthTestCase
from evaluation.service import EvaluationService

router = APIRouter(prefix="/api/v1/evaluation", tags=["evaluation"])


class RunEvaluationRequest(BaseModel):
    """Payload to trigger evaluation with optional inline fixtures or DB query."""

    ground_truth: list[GroundTruthTestCase]
    session_id: UUID | None = None
    run_id: UUID | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    fixture_turns: list[dict[str, Any]] | None = None


@router.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "evaluation"}


@router.post("/run", response_model=EvaluationResult)
async def run_evaluation(request: RunEvaluationRequest) -> EvaluationResult:
    """Execute evaluation for the provided ground-truth cases."""
    if not request.ground_truth:
        raise HTTPException(status_code=400, detail="ground_truth list cannot be empty")

    turns = []
    if request.fixture_turns is not None:
        loader = InMemoryEvaluationLoader(app_turns=request.fixture_turns)
        turns = loader.load_turns(session_id=request.session_id, run_id=request.run_id)
    else:
        config = EvaluationConfig()
        if not config.database_url:
            raise HTTPException(
                status_code=400,
                detail="No database URL configured. Provide fixture_turns or set DATABASE_URL.",
            )
        db_loader = PostgresEvaluationLoader(config)
        try:
            await db_loader.open()
            turns = await db_loader.load_turns(
                session_id=request.session_id,
                run_id=request.run_id,
                limit=request.limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc
        finally:
            await db_loader.close()

    service = EvaluationService()
    return await service.evaluate_batch(turns=turns, ground_truth=request.ground_truth)


def create_app() -> FastAPI:
    """Factory to create a standalone FastAPI instance for evaluation."""
    app = FastAPI(
        title="IMPARK Standalone Evaluation Service",
        version="0.1.0",
        description="Standalone evaluation service for routing, graph precision, and claims.",
    )
    app.include_router(router)
    return app


app = create_app()
