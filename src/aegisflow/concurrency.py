"""Bounded inference concurrency, priority scheduling, and anti-starvation (E9).

Provides:
- Strict concurrency limit (K) guarding local model inference.
- Three-tier priority queue: INTERACTIVE (0) > NORMAL (1) > BATCH (2).
- Anti-starvation aging: escalates request priority as wait time elapses.
- Independent instrumentation of queue wait duration vs inference execution time.
- Deterministic event-driven slot grant without polling loops.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from enum import IntEnum

from aegisflow.metrics import QUEUE_DEPTH

logger = logging.getLogger("aegisflow.concurrency")

DEFAULT_SEMAPHORE_K = int(os.getenv("AEGISFLOW_INFERENCE_SEMAPHORE_K", "2"))
AGING_INTERVAL_SECONDS = float(os.getenv("AEGISFLOW_AGING_INTERVAL_SECONDS", "5.0"))


class RequestPriority(IntEnum):
    """Priority levels for model inference scheduling."""

    INTERACTIVE = 0  # Real-time user queries via UI/API
    NORMAL = 1  # Standard API requests
    BATCH = 2  # Background evaluation and benchmark runs


@dataclass(order=True)
class QueuedItem:
    """Prioritized queue entry with anti-starvation aging support."""

    effective_priority: float
    enqueued_at: float = field(compare=False)
    request_id: str = field(compare=False)
    future: asyncio.Future[None] = field(compare=False)
    base_priority: int = field(compare=False, default=1)


class InferenceLimiter:
    """Bounded concurrency controller with priority scheduling and metrics."""

    def __init__(
        self,
        k: int = DEFAULT_SEMAPHORE_K,
        aging_interval_s: float = AGING_INTERVAL_SECONDS,
    ) -> None:
        self.k = max(1, k)
        self.aging_interval_s = max(0.01, aging_interval_s)
        self._available_slots = self.k
        self._waiters: list[QueuedItem] = []
        self._lock = threading.Lock()
        self._thread_semaphore = threading.BoundedSemaphore(self.k)

    @property
    def queue_depth(self) -> int:
        with self._lock:
            return len(self._waiters)

    def _recalculate_priorities(self, now: float) -> None:
        """Update effective priority based on wait duration (anti-starvation aging)."""
        for item in self._waiters:
            waited_s = now - item.enqueued_at
            age_boost = waited_s / self.aging_interval_s
            item.effective_priority = max(0.0, float(item.base_priority) - age_boost)
        self._waiters.sort()

    @asynccontextmanager
    async def acquire(
        self,
        priority: RequestPriority = RequestPriority.NORMAL,
        request_id: str = "anon",
        timeout: float = 180.0,
    ) -> AsyncIterator[dict[str, float]]:
        """Acquire an inference slot with priority queueing and timing telemetry.

        Yields:
            telemetry: dict with 'queue_wait_ms' and 'acquired_at'.
        """
        enqueued_at = time.monotonic()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()

        item = QueuedItem(
            effective_priority=float(priority),
            enqueued_at=enqueued_at,
            request_id=request_id,
            future=future,
            base_priority=int(priority),
        )

        with self._lock:
            if self._available_slots > 0 and not self._waiters:
                self._available_slots -= 1
                slot_granted = True
            else:
                self._waiters.append(item)
                self._recalculate_priorities(enqueued_at)
                QUEUE_DEPTH.set(len(self._waiters))
                slot_granted = False

        if not slot_granted:
            try:
                await asyncio.wait_for(future, timeout=timeout)
            except TimeoutError as exc:
                with self._lock:
                    if item in self._waiters:
                        self._waiters.remove(item)
                        QUEUE_DEPTH.set(len(self._waiters))
                raise TimeoutError(
                    f"Timed out in priority queue after {timeout:.1f}s"
                ) from exc

        acquired_at = time.monotonic()
        queue_wait_ms = (acquired_at - enqueued_at) * 1000.0

        try:
            yield {
                "queue_wait_ms": round(queue_wait_ms, 2),
                "acquired_at": acquired_at,
            }
        finally:
            with self._lock:
                now = time.monotonic()
                self._recalculate_priorities(now)
                granted_next = False
                while self._waiters:
                    next_waiter = self._waiters.pop(0)
                    QUEUE_DEPTH.set(len(self._waiters))
                    if not next_waiter.future.done():
                        next_waiter.future.get_loop().call_soon_threadsafe(
                            next_waiter.future.set_result, None
                        )
                        granted_next = True
                        break
                if not granted_next:
                    self._available_slots = min(self.k, self._available_slots + 1)

    @contextmanager
    def acquire_sync(self, timeout: float = 180.0) -> Iterator[dict[str, float]]:
        """Synchronous context manager for thread-based inference calls."""
        enqueued_at = time.monotonic()
        acquired = self._thread_semaphore.acquire(timeout=timeout)
        if not acquired:
            raise TimeoutError(
                f"Timed out waiting for inference slot after {timeout:.1f}s"
            )
        try:
            acquired_at = time.monotonic()
            queue_wait_ms = (acquired_at - enqueued_at) * 1000.0
            yield {
                "queue_wait_ms": round(queue_wait_ms, 2),
                "acquired_at": acquired_at,
            }
        finally:
            self._thread_semaphore.release()


# Global inference limiter singleton
_GLOBAL_LIMITER: InferenceLimiter | None = None


def get_inference_limiter(k: int | None = None) -> InferenceLimiter:
    """Return or initialize global inference limiter."""
    global _GLOBAL_LIMITER
    if _GLOBAL_LIMITER is None or (k is not None and _GLOBAL_LIMITER.k != k):
        _GLOBAL_LIMITER = InferenceLimiter(k=k or DEFAULT_SEMAPHORE_K)
    return _GLOBAL_LIMITER


def set_inference_semaphore_k(k: int) -> None:
    """Reconfigure global inference semaphore concurrency bound."""
    global _GLOBAL_LIMITER
    _GLOBAL_LIMITER = InferenceLimiter(k=k)
