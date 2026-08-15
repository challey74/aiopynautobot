"""A runnable FastAPI app sharing one aiopynautobot client.

The Api async context manager is one-shot: enter it for the application's
lifetime rather than per request, so the httpx connection pool is reused
and closed deterministically on shutdown. One Api instance is safe to
share across concurrent requests.

Run with:

    uv run --with fastapi --with uvicorn uvicorn examples.fastapi_app:app

Configure with NAUTOBOT_URL and NAUTOBOT_TOKEN.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException

import aiopynautobot

NAUTOBOT_URL = os.environ.get("NAUTOBOT_URL", "http://localhost:8080")
NAUTOBOT_TOKEN = os.environ.get("NAUTOBOT_TOKEN", "")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with aiopynautobot.api(NAUTOBOT_URL, token=NAUTOBOT_TOKEN) as nb:
        app.state.nb = nb
        yield  # handlers use app.state.nb; the pool closes on shutdown


app = FastAPI(lifespan=lifespan)


@app.get("/version")
async def version() -> dict[str, str]:
    return {"api_version": await app.state.nb.version()}


@app.get("/devices")
async def devices(location: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    nb = app.state.nb
    query = (
        nb.dcim.devices.filter(location=location, limit=limit)
        if location
        else nb.dcim.devices.all(limit=limit)
    )
    return [{"id": d.id, "name": d.name, "status": str(d.status)} async for d in query]


@app.get("/devices/{device_id}")
async def device(device_id: str) -> dict[str, Any]:
    found = await app.state.nb.dcim.devices.get(device_id)
    if found is None:
        raise HTTPException(status_code=404, detail="device not found")
    return dict(found)


@app.patch("/devices/{device_id}/serial")
async def set_serial(device_id: str, serial: str) -> dict[str, Any]:
    found = await app.state.nb.dcim.devices.get(device_id)
    if found is None:
        raise HTTPException(status_code=404, detail="device not found")
    found.serial = serial
    # Only the changed field is PATCHed.
    changed = await found.save()
    return {"changed": changed, "serial": found.serial}
