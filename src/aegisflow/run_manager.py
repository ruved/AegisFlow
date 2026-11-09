"""Managed asyncio execution for persistent workflow runs."""

import asyncio
import logging
from typing import Any
from uuid import uuid4

from aegisflow.config import CHAT_MODEL
from aegisflow.metrics import ACTIVE_RUNS, QUEUE_DEPTH, record_error
from aegisflow.rag.retrieval import DEFAULT_STORE_PATH
from aegisflow.run_store import RunStore
from aegisflow.tracing import trace_workflow_run
from aegisflow.workflow.nodes import WorkflowServices
from aegisflow.workflow.runner import run_workflow_async
from aegisflow.workflow.state import RunState

logger = logging.getLogger("aegisflow.runs")


class RunManager:
    def __init__(self, store: RunStore, saver: Any) -> None:
        self.store = store
        self.saver = saver
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.cancel_flags: dict[str, asyncio.Event] = {}

    async def recover(self) -> None:
        for row in await self.store.resumable():
            run_id = row["id"]
            if row["cancel_requested"]:
                await self.store.status(run_id, "cancelled")
            else:
                self.start(run_id, row["question"], row["top_k"])

    def start(self, run_id: str, question: str, top_k: int) -> None:
        if run_id in self.tasks and not self.tasks[run_id].done():
            return
        QUEUE_DEPTH.inc()
        flag = self.cancel_flags.setdefault(run_id, asyncio.Event())
        services = WorkflowServices(
            is_cancelled=lambda candidate: candidate == run_id and flag.is_set()
        )
        self.tasks[run_id] = asyncio.create_task(
            self._execute(run_id, question, top_k, services),
            name=f"aegisflow-run-{run_id}",
        )

    async def create(self, key: str, question: str, top_k: int) -> dict[str, Any]:
        run_id = uuid4().hex
        row, created = await self.store.create(run_id, key, question, top_k)
        if created:
            self.start(run_id, question, top_k)
        return row

    async def cancel(self, run_id: str) -> dict[str, Any] | None:
        row = await self.store.get(run_id)
        if row is None:
            return None
        if row["status"] in {"completed", "abstained", "failed", "cancelled"}:
            return row
        await self.store.request_cancel(run_id)
        self.cancel_flags.setdefault(run_id, asyncio.Event()).set()
        if run_id not in self.tasks:
            await self.store.status(run_id, "cancelled")
        return await self.store.get(run_id)

    async def resume(self, run_id: str) -> dict[str, Any] | None:
        row = await self.store.get(run_id)
        if row is None:
            return None
        if row["status"] not in {"failed", "cancelled"}:
            return row
        if row["status"] == "cancelled":
            await self.saver.adelete_thread(run_id)
        await self.store.requeue(run_id)
        self.cancel_flags[run_id] = asyncio.Event()
        self.start(run_id, row["question"], row["top_k"])
        await self.store.event(run_id, "queued", {"status": "queued", "resumed": True})
        return await self.store.get(run_id)

    async def _execute(
        self,
        run_id: str,
        question: str,
        top_k: int,
        services: WorkflowServices,
    ) -> None:
        state = {
            "run_id": run_id,
            "question": question,
            "top_k": top_k,
            "model": CHAT_MODEL,
            "planner_model": CHAT_MODEL,
            "store_path": str(DEFAULT_STORE_PATH),
        }
        QUEUE_DEPTH.dec()
        ACTIVE_RUNS.inc()
        try:
            with trace_workflow_run(run_id, question, top_k) as root_span:
                await self.store.status(run_id, "running")
                checkpoint = await self.saver.aget_tuple(
                    {"configurable": {"thread_id": run_id}}
                )

                async def publish(current: RunState) -> None:
                    for event in current.get("telemetry", []):
                        event_id = event.get("event_id")
                        if event_id and event_id not in published:
                            published.add(event_id)
                            await self.store.event(run_id, "node", dict(event))
                    await self.store.event(
                        run_id,
                        "checkpoint",
                        {
                            "steps": current.get("steps", 0),
                            "next_node": current.get("next_node"),
                        },
                    )

                published: set[str] = set()
                result = await run_workflow_async(
                    state,
                    checkpointer=self.saver,
                    services=services,
                    on_update=publish,
                    resume=checkpoint is not None,
                )
                if result.get("cancelled") or await self.store.cancelled(run_id):
                    root_span.set_attribute("workflow.status", "cancelled")
                    await self.store.status(run_id, "cancelled", result=dict(result))
                elif result.get("abstained"):
                    root_span.set_attribute("workflow.status", "abstained")
                    await self.store.status(
                        run_id, "abstained", result=result.get("report")
                    )
                else:
                    root_span.set_attribute("workflow.status", "completed")
                    await self.store.status(
                        run_id, "completed", result=result.get("report")
                    )
        except Exception as exc:
            record_error("workflow_run", type(exc).__name__)
            logger.exception("managed workflow failed", extra={"run_id": run_id})
            await self.store.status(run_id, "failed", error=type(exc).__name__)
        finally:
            ACTIVE_RUNS.dec()
            self.tasks.pop(run_id, None)

    async def wait(self, run_id: str, timeout: float = 10.0) -> None:
        task = self.tasks.get(run_id)
        if task:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
