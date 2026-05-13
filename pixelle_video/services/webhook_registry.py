# Copyright (C) 2025 AIDC-AI
"""
In-process registry mapping RunningHub task IDs -> asyncio.Future.

Used to wait for openapi/v2 webhook callbacks instead of polling /query.

Lifecycle:
  - caller `register(task_id)` -> gets an `asyncio.Future`
  - webhook handler (api/routers/webhooks.py) calls `resolve(task_id, payload)`
  - caller `await future` (with a timeout); on timeout caller should `unregister(task_id)` and fall back to polling
"""

from __future__ import annotations

import asyncio
from typing import Any

_futures: dict[str, asyncio.Future] = {}
_lock = asyncio.Lock()


async def register(task_id: str) -> asyncio.Future:
    async with _lock:
        # If already registered (shouldn't happen normally), return the existing one
        existing = _futures.get(task_id)
        if existing is not None and not existing.done():
            return existing
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        _futures[task_id] = fut
        return fut


async def resolve(task_id: str, payload: dict[str, Any]) -> bool:
    """Resolve the registered future. Returns True if a waiter was found."""
    async with _lock:
        fut = _futures.pop(task_id, None)
    if fut is None or fut.done():
        return False
    fut.set_result(payload)
    return True


async def unregister(task_id: str) -> None:
    async with _lock:
        _futures.pop(task_id, None)
