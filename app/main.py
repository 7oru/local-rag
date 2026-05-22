from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import ConfigError, load_settings
from app.db import inspect_database
from app.retrieval import RetrievalError, RetrievalNotReady, search, to_search_result
from app.schemas import (
    ErrorBody,
    ErrorResponse,
    HealthChecks,
    HealthDetails,
    HealthResponse,
    SearchRequest,
    SearchResponse,
)


app = FastAPI(title="local-rag", version="0.1.0")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return api_error(
        status_code=422,
        code="invalid_request",
        message="Request validation failed.",
        details={"errors": exc.errors()},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return _http_error_response(exc)


@app.exception_handler(StarletteHTTPException)
async def starlette_http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    return _http_error_response(exc)


def _http_error_response(exc: HTTPException | StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    return api_error(
        status_code=exc.status_code,
        code=str(detail.get("code") or "http_error"),
        message=str(detail.get("message") or exc.detail),
        details=dict(detail.get("details") or {}),
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse | JSONResponse:
    try:
        settings = load_settings()
    except ConfigError as exc:
        return api_error(
            status_code=503,
            code="configuration_error",
            message="Application configuration is invalid.",
            details={"reason": str(exc)},
        )

    status = inspect_database(settings)
    if not status.database:
        return api_error(
            status_code=503,
            code="database_unavailable",
            message="Database is not reachable.",
            details={"reason": status.error or "connection failed"},
        )
    if not status.schema:
        return api_error(
            status_code=503,
            code="schema_not_initialized",
            message="Database schema is not initialized.",
        )
    if not status.pgvector:
        return api_error(
            status_code=503,
            code="pgvector_unavailable",
            message="pgvector extension is not available.",
        )

    retrieval_ready = "ok" if status.embeddings_current_config > 0 else "not_ready"
    return HealthResponse(
        status="ok",
        checks=HealthChecks(
            app="ok",
            database="ok",
            schema="ok",
            pgvector="ok",
            embedding_config="ok",
            retrieval_ready=retrieval_ready,
        ),
        details=HealthDetails(
            embedding_provider=settings.embedding_provider,
            embedding_model=settings.embedding_model,
            documents=status.documents,
            chunks=status.chunks,
            embeddings_current_config=status.embeddings_current_config,
        ),
    )


@app.post("/search", response_model=SearchResponse)
def search_route(request: SearchRequest) -> SearchResponse | JSONResponse:
    try:
        result = search(request.query, top_k=request.top_k)
    except RetrievalNotReady as exc:
        return api_error(
            status_code=503,
            code="retrieval_not_ready",
            message="Retrieval is not ready for the current embedding config.",
            details={"reason": str(exc)},
        )
    except RetrievalError as exc:
        return api_error(
            status_code=503,
            code="retrieval_error",
            message="Retrieval failed.",
            details={"reason": str(exc)},
        )

    return SearchResponse(
        query=result.query,
        top_k=result.top_k,
        results=[to_search_result(chunk) for chunk in result.chunks],
        confidence=result.confidence,
    )


def api_error(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    response = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            details=details or {},
        )
    )
    return JSONResponse(status_code=status_code, content=response.model_dump())
