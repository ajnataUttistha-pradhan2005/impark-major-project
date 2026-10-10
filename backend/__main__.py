"""Run the single-process demo using python -m backend."""

import asyncio
from contextlib import suppress

import uvicorn

from backend.runtime import loop_factory

if __name__ == "__main__":
    server = uvicorn.Server(uvicorn.Config("backend.main:app", host="127.0.0.1", port=8000))
    with suppress(KeyboardInterrupt):
        asyncio.run(server.serve(), loop_factory=loop_factory)
