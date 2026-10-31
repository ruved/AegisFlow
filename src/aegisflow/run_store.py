"""SQLite-backed run records and replayable event history."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class RunStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                question TEXT NOT NULL,
                top_k INTEGER NOT NULL,
                status TEXT NOT NULL,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                result_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS run_events (
                run_id TEXT NOT NULL REFERENCES runs(id),
                seq INTEGER NOT NULL,
                event TEXT NOT NULL,
                data_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (run_id, seq)
            );
            """
        )
        await self.db.commit()

    async def close(self) -> None:
        if self.db is not None:
            await self.db.close()
            self.db = None

    def _db(self) -> aiosqlite.Connection:
        if self.db is None:
            raise RuntimeError("Run store is not open")
        return self.db

    async def create(
        self, run_id: str, key: str, question: str, top_k: int
    ) -> tuple[dict[str, Any], bool]:
        db = self._db()
        now = utc_now()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(
                    "INSERT INTO runs(id,idempotency_key,question,top_k,status,"
                    "created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (run_id, key, question, top_k, "queued", now, now),
                )
                await self._insert_event(db, run_id, "queued", {"status": "queued"})
                await db.commit()
                created = True
            except aiosqlite.IntegrityError:
                await db.rollback()
                row = await (
                    await db.execute(
                        "SELECT * FROM runs WHERE idempotency_key=?", (key,)
                    )
                ).fetchone()
                if row is None:
                    raise
                return dict(row), False
        created_row = await self.get(run_id)
        assert created_row is not None
        return created_row, created

    async def _insert_event(
        self, db: aiosqlite.Connection, run_id: str, event: str, data: dict[str, Any]
    ) -> None:
        row = await (
            await db.execute(
                "SELECT COALESCE(MAX(seq),0)+1 AS next_seq "
                "FROM run_events WHERE run_id=?",
                (run_id,),
            )
        ).fetchone()
        assert row is not None
        await db.execute(
            "INSERT INTO run_events(run_id,seq,event,data_json,created_at) "
            "VALUES(?,?,?,?,?)",
            (run_id, row["next_seq"], event, json.dumps(data), utc_now()),
        )

    async def event(self, run_id: str, event: str, data: dict[str, Any]) -> None:
        db = self._db()
        async with self._lock:
            await db.execute("BEGIN IMMEDIATE")
            await self._insert_event(db, run_id, event, data)
            await db.execute(
                "UPDATE runs SET updated_at=? WHERE id=?", (utc_now(), run_id)
            )
            await db.commit()

    async def status(
        self,
        run_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        db = self._db()
        async with self._lock:
            await db.execute(
                "UPDATE runs SET status=?,result_json=?,error=?,updated_at=? "
                "WHERE id=?",
                (
                    status,
                    json.dumps(result) if result is not None else None,
                    error,
                    utc_now(),
                    run_id,
                ),
            )
            await self._insert_event(
                db,
                run_id,
                status,
                {"status": status, "result": result, "error": error},
            )
            await db.commit()

    async def get(self, run_id: str) -> dict[str, Any] | None:
        async with self._lock:
            row = await (
                await self._db().execute("SELECT * FROM runs WHERE id=?", (run_id,))
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        if result["result_json"]:
            result["result"] = json.loads(result.pop("result_json"))
        else:
            result.pop("result_json")
        return result

    async def events(self, run_id: str, after: int) -> list[dict[str, Any]]:
        async with self._lock:
            rows = await (
                await self._db().execute(
                    "SELECT seq,event,data_json,created_at FROM run_events "
                    "WHERE run_id=? AND seq>? ORDER BY seq",
                    (run_id, after),
                )
            ).fetchall()
        return [
            {
                "id": row["seq"],
                "event": row["event"],
                "data": json.loads(row["data_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def request_cancel(self, run_id: str) -> None:
        db = self._db()
        async with self._lock:
            await db.execute(
                "UPDATE runs SET cancel_requested=1,status='cancelling',updated_at=? "
                "WHERE id=?",
                (utc_now(), run_id),
            )
            await self._insert_event(
                db, run_id, "cancel_requested", {"status": "cancelling"}
            )
            await db.commit()

    async def requeue(self, run_id: str) -> None:
        db = self._db()
        async with self._lock:
            await db.execute(
                "UPDATE runs SET status='queued',cancel_requested=0,"
                "updated_at=? WHERE id=?",
                (utc_now(), run_id),
            )
            await db.commit()

    async def cancelled(self, run_id: str) -> bool:
        async with self._lock:
            row = await (
                await self._db().execute(
                    "SELECT cancel_requested FROM runs WHERE id=?", (run_id,)
                )
            ).fetchone()
        return bool(row and row["cancel_requested"])

    async def resumable(self) -> list[dict[str, Any]]:
        async with self._lock:
            rows = await (
                await self._db().execute(
                    "SELECT * FROM runs "
                    "WHERE status IN ('queued','running','cancelling')"
                )
            ).fetchall()
        return [dict(row) for row in rows]
