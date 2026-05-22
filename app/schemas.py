from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthChecks(BaseModel):
    app: Literal["ok"]
    database: Literal["ok"]
    schema: Literal["ok"]
    pgvector: Literal["ok"]
    embedding_config: Literal["ok"]
    retrieval_ready: Literal["ok", "not_ready"]


class HealthDetails(BaseModel):
    embedding_provider: str
    embedding_model: str
    documents: int
    chunks: int
    embeddings_current_config: int


class HealthResponse(BaseModel):
    status: Literal["ok"]
    checks: HealthChecks
    details: HealthDetails


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
