"""FastAPI application for the AegisFlow RAG service."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from typing import Annotated, Any, cast

import chromadb
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from aegisflow.config import MAX_QUESTION_LENGTH, MAX_TOP_K
from aegisflow.rag.errors import (
    OllamaConfigurationError,
    OllamaResponseError,
    OllamaTimeoutError,
    OllamaUnavailableError,
    VectorStoreUnavailableError,
)
from aegisflow.rag.generation import generate_answer
from aegisflow.rag.ollama import check_ollama
from aegisflow.rag.retrieval import DEFAULT_STORE_PATH
from aegisflow.rag.vector_store import check_vector_store
from aegisflow.run_manager import RunManager
from aegisflow.run_store import RunStore
from aegisflow.workflow.runner import sqlite_saver_context

logger = logging.getLogger("aegisflow.api")

RUNTIME_DIR = Path(__file__).resolve().parents[2] / "runtime"


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    store = RunStore(Path(application.state.run_db_path))
    await store.open()
    async with sqlite_saver_context(Path(application.state.checkpoint_path)) as saver:
        manager = RunManager(store, saver)
        application.state.run_store = store
        application.state.run_manager = manager
        await manager.recover()
        try:
            yield
        finally:
            for flag in manager.cancel_flags.values():
                flag.set()
            if manager.tasks:
                await asyncio.gather(*manager.tasks.values(), return_exceptions=True)
            await store.close()


app = FastAPI(
    title="AegisFlow API",
    description="Local-first RAG question-answering service.",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.run_db_path = RUNTIME_DIR / "runs.sqlite3"
app.state.checkpoint_path = RUNTIME_DIR / "checkpoints.sqlite3"


class RunRequest(BaseModel):
    question: Annotated[str, Field(min_length=1, max_length=MAX_QUESTION_LENGTH)]
    top_k: Annotated[int, Field(ge=1, le=MAX_TOP_K)] = 3

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question must not be empty")
        return value


class RunResponse(BaseModel):
    id: str
    question: str
    top_k: int
    status: str
    result: dict[str, Any] | None = None


def _run_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "question": row["question"],
        "top_k": row["top_k"],
        "status": row["status"],
        "result": row.get("result"),
    }


@app.post("/v1/runs", response_model=RunResponse, status_code=202)
async def create_run(
    run: RunRequest,
    request: Request,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=200)
    ],
) -> dict[str, Any]:
    row = await request.app.state.run_manager.create(
        idempotency_key, run.question, run.top_k
    )
    return _run_response(row)


@app.get("/v1/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: str, request: Request) -> dict[str, Any]:
    row = await request.app.state.run_store.get(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_response(row)


@app.post("/v1/runs/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(run_id: str, request: Request) -> dict[str, Any]:
    row = await request.app.state.run_manager.cancel(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_response(row)


@app.post("/v1/runs/{run_id}/resume", response_model=RunResponse, status_code=202)
async def resume_run(run_id: str, request: Request) -> dict[str, Any]:
    row = await request.app.state.run_manager.resume(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_response(row)


@app.get("/v1/runs/{run_id}/events")
async def run_events(
    run_id: str,
    request: Request,
    last_event_id: Annotated[int, Header(alias="Last-Event-ID", ge=0)] = 0,
) -> StreamingResponse:
    if await request.app.state.run_store.get(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")

    async def stream() -> AsyncIterator[str]:
        cursor = last_event_id
        while True:
            events = await request.app.state.run_store.events(run_id, cursor)
            for event in events:
                cursor = event["id"]
                data = json.dumps(event["data"], separators=(",", ":"))
                yield f"id: {cursor}\nevent: {event['event']}\ndata: {data}\n\n"
            row = await request.app.state.run_store.get(run_id)
            if row is None or (
                row["status"] in {"completed", "abstained", "failed", "cancelled"}
                and not events
            ):
                break
            if await request.is_disconnected():
                break
            await asyncio.sleep(0.2)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class AskRequest(BaseModel):
    """Input schema for a question-answering request."""

    question: Annotated[str, Field(min_length=1, max_length=MAX_QUESTION_LENGTH)]
    top_k: Annotated[int, Field(ge=1, le=MAX_TOP_K)] = 3

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        """Reject whitespace-only questions and normalize surrounding spaces."""
        value = value.strip()
        if not value:
            raise ValueError("Question must not be empty")
        return value


class CitationResponse(BaseModel):
    """Map a short answer citation back to its retrieved evidence chunk."""

    evidence_id: str
    chunk_id: str
    source: str
    heading: str | None


class AskResponse(BaseModel):
    """Output schema for a question-answering request."""

    answer: str
    sources: list[str]
    citations: list[CitationResponse]
    abstained: bool = False
    missing: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """Output schema for the liveness endpoint."""

    status: str


class ReadinessResponse(BaseModel):
    """Output schema for local dependency readiness."""

    status: str
    dependencies: dict[str, str]


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Confirm that the API process is running, independent of dependencies."""
    return HealthResponse(status="ok")


@app.get("/ready", response_model=ReadinessResponse)
def readiness_check() -> ReadinessResponse | JSONResponse:
    """Check local Ollama and Chroma availability without model inference."""
    started = perf_counter()
    dependencies = {"ollama": "ok", "vector_store": "ok"}

    try:
        check_ollama()
    except (OllamaTimeoutError, OllamaUnavailableError, OllamaResponseError):
        logger.warning(
            "api_dependency_check_failed endpoint=/ready dependency=ollama "
            "elapsed_ms=%.1f",
            (perf_counter() - started) * 1000,
            exc_info=True,
        )
        dependencies["ollama"] = "unavailable"
    except OllamaConfigurationError as exc:
        logger.error(
            "api_dependency_check_failed endpoint=/ready dependency=ollama "
            "category=configuration elapsed_ms=%.1f",
            (perf_counter() - started) * 1000,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Service configuration error."
        ) from exc

    try:
        check_vector_store(DEFAULT_STORE_PATH)
    except VectorStoreUnavailableError:
        logger.warning(
            "api_dependency_check_failed endpoint=/ready dependency=vector_store "
            "elapsed_ms=%.1f",
            (perf_counter() - started) * 1000,
            exc_info=True,
        )
        dependencies["vector_store"] = "unavailable"

    if "unavailable" in dependencies.values():
        body = ReadinessResponse(
            status="not_ready", dependencies=dependencies
        ).model_dump()
        return JSONResponse(status_code=503, content=body)

    logger.info(
        "api_request_completed endpoint=/ready elapsed_ms=%.1f",
        (perf_counter() - started) * 1000,
    )
    return ReadinessResponse(status="ready", dependencies=dependencies)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return safe validation errors without echoing submitted values."""
    categories = [str(error.get("type", "invalid")) for error in exc.errors()]
    logger.warning(
        "api_request_failed endpoint=%s category=validation error_types=%s",
        request.url.path,
        ",".join(categories),
    )
    return JSONResponse(status_code=422, content={"detail": "Invalid request."})


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log unexpected failures and keep internal details out of responses."""
    logger.exception(
        "api_request_failed endpoint=%s category=internal_error", request.url.path
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


@app.post("/ask", response_model=AskResponse)
def ask_question(request: AskRequest) -> AskResponse:
    """Answer a question using the existing RAG pipeline."""
    started = perf_counter()
    try:
        result = generate_answer(query=request.question, k=request.top_k)
    except OllamaTimeoutError as exc:
        logger.warning(
            "api_request_failed endpoint=/ask category=dependency_timeout "
            "elapsed_ms=%.1f",
            (perf_counter() - started) * 1000,
            exc_info=True,
        )
        raise HTTPException(
            status_code=504, detail="Local inference timed out."
        ) from exc
    except (OllamaUnavailableError, VectorStoreUnavailableError) as exc:
        logger.warning(
            "api_request_failed endpoint=/ask category=dependency_unavailable "
            "elapsed_ms=%.1f",
            (perf_counter() - started) * 1000,
            exc_info=True,
        )
        raise HTTPException(
            status_code=503, detail="A required local dependency is unavailable."
        ) from exc
    except OllamaConfigurationError as exc:
        logger.error(
            "api_request_failed endpoint=/ask category=configuration_error "
            "elapsed_ms=%.1f",
            (perf_counter() - started) * 1000,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail="Service configuration error."
        ) from exc
    except OllamaResponseError as exc:
        logger.error(
            "api_request_failed endpoint=/ask category=dependency_response_error "
            "elapsed_ms=%.1f",
            (perf_counter() - started) * 1000,
            exc_info=True,
        )
        raise HTTPException(
            status_code=502, detail="A local dependency returned an invalid response."
        ) from exc
    except (chromadb.errors.ChromaError, OSError) as exc:
        logger.warning(
            "api_request_failed endpoint=/ask category=vector_store_unavailable "
            "elapsed_ms=%.1f",
            (perf_counter() - started) * 1000,
            exc_info=True,
        )
        raise HTTPException(
            status_code=503, detail="The local vector store is unavailable."
        ) from exc
    except Exception as exc:
        logger.exception(
            "api_request_failed endpoint=/ask category=internal_error elapsed_ms=%.1f",
            (perf_counter() - started) * 1000,
        )
        raise HTTPException(status_code=500, detail="Internal server error.") from exc

    logger.info(
        "api_request_completed endpoint=/ask elapsed_ms=%.1f",
        (perf_counter() - started) * 1000,
    )
    return AskResponse(
        answer=result["answer"],
        sources=result["sources"],
        citations=[CitationResponse(**citation) for citation in result["citations"]],
        abstained=bool(result.get("abstained", False)),
        missing=(
            cast(list[str], result.get("missing"))
            if isinstance(result.get("missing"), list)
            else []
        ),
    )
