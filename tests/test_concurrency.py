"""Tests for bounded inference semaphore, priority queueing, and anti-starvation (E9)."""

import asyncio
import time

import pytest

from aegisflow.concurrency import InferenceLimiter, RequestPriority


@pytest.mark.anyio
async def test_inference_limiter_bounds_concurrency_k() -> None:
    # Limit K = 2
    limiter = InferenceLimiter(k=2)
    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def worker(worker_id: int) -> None:
        nonlocal active, max_active
        async with limiter.acquire(priority=RequestPriority.NORMAL, request_id=f"w{worker_id}"):
            async with lock:
                active += 1
                if active > max_active:
                    max_active = active
            await asyncio.sleep(0.05)
            async with lock:
                active -= 1

    tasks = [asyncio.create_task(worker(i)) for i in range(5)]
    await asyncio.gather(*tasks)

    # Max concurrently active workers must never exceed K=2
    assert max_active == 2


@pytest.mark.anyio
async def test_inference_limiter_priority_ordering() -> None:
    # Limit K = 1 so items must queue up
    limiter = InferenceLimiter(k=1)
    execution_order: list[str] = []

    # Block the single slot with a long-running task
    async def blocker() -> None:
        async with limiter.acquire(priority=RequestPriority.NORMAL, request_id="blocker"):
            await asyncio.sleep(0.1)

    async def worker(name: str, priority: RequestPriority) -> None:
        async with limiter.acquire(priority=priority, request_id=name):
            execution_order.append(name)

    blocker_task = asyncio.create_task(blocker())
    await asyncio.sleep(0.01)  # ensure blocker holds semaphore

    # Enqueue Batch task first, then Interactive task second
    batch_task = asyncio.create_task(worker("batch_1", RequestPriority.BATCH))
    await asyncio.sleep(0.01)
    interactive_task = asyncio.create_task(worker("interactive_1", RequestPriority.INTERACTIVE))

    await asyncio.gather(blocker_task, batch_task, interactive_task)

    # Interactive task MUST have jumped ahead of Batch task
    assert execution_order == ["interactive_1", "batch_1"]


def test_inference_limiter_anti_starvation_aging() -> None:
    limiter = InferenceLimiter(k=1, aging_interval_s=0.1)
    old_time = time.monotonic() - 0.35
    from unittest.mock import MagicMock
    from aegisflow.concurrency import QueuedItem

    old_item = QueuedItem(
        effective_priority=2.0,
        enqueued_at=old_time,
        request_id="old_batch",
        future=MagicMock(),
        base_priority=2,
    )
    limiter._waiters.append(old_item)
    limiter._recalculate_priorities(time.monotonic())

    # Effective priority should have aged from 2.0 down to near 0.0
    assert old_item.effective_priority < 0.5


def test_inference_limiter_sync_acquire() -> None:
    limiter = InferenceLimiter(k=2)

    with limiter.acquire_sync() as info:
        assert info["queue_wait_ms"] >= 0.0
        assert info["acquired_at"] > 0.0
