"""FastAPI application for the AegisFlow RAG service."""

import logging
from time import perf_counter
from typing import Annotated

import chromadb
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
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

logger = logging.getLogger("aegisflow.api")

app = FastAPI(
    title="AegisFlow API",
    description="Local-first RAG question-answering service.",
    version="0.1.0",
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


class AskResponse(BaseModel):
    """Output schema for a question-answering request."""

    answer: str
    sources: list[str]


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
    return AskResponse(answer=result["answer"], sources=result["sources"])
