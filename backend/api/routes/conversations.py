from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from backend.api.dependencies.services import authorize_development, get_service
from backend.api.schemas.chat import AutocompleteResponse, ChatRequest, ChatResponse
from backend.contracts.response import ClarificationResponse
from backend.services.conversations import ConversationService

router = APIRouter(prefix="/dev", dependencies=[Depends(authorize_development)])
Service = Annotated[ConversationService, Depends(get_service)]


@router.post("/conversations", response_model=ChatResponse, status_code=201)
async def create(request: Request, service: Service) -> ChatResponse:
    return await service.create(request.state.correlation_id)


@router.get("/conversations/{session_id}", response_model=ChatResponse)
async def retrieve(session_id: UUID, service: Service) -> ChatResponse:
    return await service.get(session_id)


@router.get("/conversations/{session_id}/state", response_model=ChatResponse)
async def state(session_id: UUID, service: Service) -> ChatResponse:
    return await service.get(session_id)


@router.get("/conversations/{session_id}/history", response_model=list[ChatResponse])
async def history(session_id: UUID, service: Service) -> list[ChatResponse]:
    return await service.history(session_id)


@router.post("/conversations/{session_id}/turns", response_model=ChatResponse)
async def submit(
    session_id: UUID,
    body: ChatRequest,
    request: Request,
    service: Service,
) -> ChatResponse:
    return await service.submit(session_id, body, request.state.correlation_id)


@router.post("/conversations/{session_id}/clarifications", response_model=ChatResponse)
async def resume(
    session_id: UUID,
    body: ClarificationResponse,
    request: Request,
    service: Service,
) -> ChatResponse:
    return await service.submit(
        session_id,
        ChatRequest(text=body.text),
        request.state.correlation_id,
        body,
    )


@router.get("/discovery/autocomplete", response_model=AutocompleteResponse)
async def autocomplete(
    service: Service,
    q: Annotated[str, Query(min_length=1, max_length=200)],
) -> AutocompleteResponse:
    return await service.autocomplete(q)
