# API contract

The supported browser contract is `/api/v1`, implemented in `backend/api/routes/platform.py` and `backend/api/schemas/{chat,platform}.py`. It is an asynchronous, durable-operation API with replayable SSE. Read the [complete API and frontend contract](docs/api-and-frontend/README.md) for routes, payloads, stream events, errors, authentication and UI recovery. The running backend's `/openapi.json` is definitive; `frontend/contracts/openapi.json` is a generated snapshot. The `/dev` routes are for development and are not the frontend contract.
