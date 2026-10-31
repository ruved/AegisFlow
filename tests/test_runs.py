"""Persistent run lifecycle API and event replay tests."""

import asyncio
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from aegisflow import api
from aegisflow.run_store import RunStore


def test_run_store_idempotency_and_event_replay(tmp_path: Path) -> None:
    async def exercise() -> None:
        store = RunStore(tmp_path / "runs.sqlite3")
        await store.open()
        original, created = await store.create("run-1", "same-key", "question", 3)
        duplicate, created_again = await store.create(
            "run-2", "same-key", "question", 3
        )
        await store.event("run-1", "node", {"node": "planner"})
        events = await store.events("run-1", 1)
        assert created is True
        assert created_again is False
        assert duplicate["id"] == original["id"] == "run-1"
        assert events[0]["id"] == 2
        assert events[0]["data"] == {"node": "planner"}
        await store.close()

    asyncio.run(exercise())


def test_run_api_idempotency_completion_and_sse_reconnect(
    tmp_path: Path, monkeypatch: Any
) -> None:
    async def fake_run(state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        await kwargs["on_update"](
            {
                "steps": 1,
                "next_node": "finish",
                "telemetry": [
                    {
                        "event_id": f"{state['run_id']}:planner:1",
                        "run_id": state["run_id"],
                        "node": "planner",
                        "duration_ms": 1.0,
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "cache_hit": False,
                        "tokens_estimated": False,
                        "status": "ok",
                    }
                ],
            }
        )
        return {"abstained": False, "report": {"diagnosis": "done"}}

    monkeypatch.setattr("aegisflow.run_manager.run_workflow_async", fake_run)
    api.app.state.run_db_path = tmp_path / "runs.sqlite3"
    api.app.state.checkpoint_path = tmp_path / "checkpoints.sqlite3"
    with TestClient(api.app) as client:
        created = client.post(
            "/v1/runs",
            headers={"Idempotency-Key": "same"},
            json={"question": "question"},
        )
        assert created.status_code == 202
        run_id = created.json()["id"]
        duplicate = client.post(
            "/v1/runs",
            headers={"Idempotency-Key": "same"},
            json={"question": "question"},
        )
        assert duplicate.json()["id"] == run_id
        client.portal.call(client.app.state.run_manager.wait, run_id)
        response = client.get(f"/v1/runs/{run_id}")
        assert response.json()["status"] == "completed"
        assert response.json()["result"] == {"diagnosis": "done"}
        replay = client.get(f"/v1/runs/{run_id}/events", headers={"Last-Event-ID": "1"})
        assert replay.status_code == 200
        assert "event: node" in replay.text
        assert "event: completed" in replay.text


def test_run_api_validates_idempotency_key(tmp_path: Path) -> None:
    api.app.state.run_db_path = tmp_path / "runs.sqlite3"
    api.app.state.checkpoint_path = tmp_path / "checkpoints.sqlite3"
    with TestClient(api.app) as client:
        response = client.post("/v1/runs", json={"question": "question"})
        assert response.status_code == 422
