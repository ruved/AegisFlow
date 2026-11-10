"""Tests for bounded inference semaphore, priority queueing, and aging (E9)."""

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from aegisflow.concurrency import InferenceLimiter, QueuedItem, RequestPriority


@pytest.mark.anyio
async def test_inference_limiter_bounds_concurrency_k() -> None:
    # Limit K = 2
    limiter = InferenceLimiter(k=2)
    active = 0
    max_active = 0
    lock = asyncio.Lock()
    two_acquired = asyncio.Event()
    release_workers = asyncio.Event()
    acquired_count = 0

    async def worker(worker_id: int) -> None:
        nonlocal active, max_active, acquired_count
        async with limiter.acquire(
            priority=RequestPriority.NORMAL,
            request_id=f"w{worker_id}",
        ):
            async with lock:
                active += 1
                if active > max_active:
                    max_active = active
                acquired_count += 1
                if acquired_count == 2:
                    two_acquired.set()
            await release_workers.wait()
            async with lock:
                active -= 1

    tasks = [asyncio.create_task(worker(i)) for i in range(5)]
    # Wait until 2 slots are actively acquired
    await two_acquired.wait()
    await asyncio.sleep(0.01)

    # Max concurrently active workers must be exactly K=2
    assert max_active == 2
    assert active == 2

    # Release workers and wait for all to complete
    release_workers.set()
    await asyncio.gather(*tasks)
    assert max_active == 2


@pytest.mark.anyio
async def test_inference_limiter_priority_ordering() -> None:
    # Limit K = 1 so items must queue up
    limiter = InferenceLimiter(k=1)
    execution_order: list[str] = []
    blocker_acquired = asyncio.Event()
    release_blocker = asyncio.Event()

    # Block the single slot with a controlled task
    async def blocker() -> None:
        async with limiter.acquire(
            priority=RequestPriority.NORMAL,
            request_id="blocker",
        ):
            blocker_acquired.set()
            await release_blocker.wait()

    async def worker(name: str, priority: RequestPriority) -> None:
        async with limiter.acquire(priority=priority, request_id=name):
            execution_order.append(name)

    blocker_task = asyncio.create_task(blocker())
    await blocker_acquired.wait()  # Guaranteed: blocker holds the single slot

    # Enqueue Batch task first and verify it is waiting
    batch_task = asyncio.create_task(worker("batch_1", RequestPriority.BATCH))
    while len(limiter._waiters) < 1:
        await asyncio.sleep(0.001)

    # Enqueue Interactive task second and verify it is waiting
    interactive_task = asyncio.create_task(
        worker("interactive_1", RequestPriority.INTERACTIVE)
    )
    while len(limiter._waiters) < 2:
        await asyncio.sleep(0.001)

    # Both items are queued; release blocker to trigger priority scheduling
    release_blocker.set()
    await asyncio.gather(blocker_task, batch_task, interactive_task)

    # Interactive task MUST have jumped ahead of Batch task
    assert execution_order == ["interactive_1", "batch_1"]


def test_inference_limiter_anti_starvation_aging() -> None:
    limiter = InferenceLimiter(k=1, aging_interval_s=0.1)
    old_time = time.monotonic() - 0.35

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
