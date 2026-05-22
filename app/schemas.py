from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HealthChecks(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    app: Literal["ok"]
    database: Literal["ok"]
    schema_: Literal["ok"] = Field(alias="schema")
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


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def query_must_not_be_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be empty")
        return stripped


class SearchResult(BaseModel):
    source: str
    relative_path: str
    heading_path: list[str]
    heading: str
    content: str
    score: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def source_and_heading_fields_match(self) -> "SearchResult":
        if self.source != self.relative_path:
            raise ValueError("source must equal relative_path")
        expected_heading = self.heading_path[-1] if self.heading_path else ""
        if self.heading != expected_heading:
            raise ValueError("heading must match the final heading_path item")
        return self


class SearchResponse(BaseModel):
    query: str
    top_k: int = Field(ge=1, le=20)
    results: list[SearchResult]
    confidence: float = Field(ge=0.0, le=1.0)


class Citation(BaseModel):
    source: str
    heading: str
    score: float = Field(ge=0.0, le=1.0)


class AskRequest(BaseModel):
    question: str
    top_k: int = Field(default=5, ge=1, le=20)
    fallback: bool = False

    @field_validator("question")
    @classmethod
    def question_must_not_be_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("question must not be empty")
        return stripped


class AskResponse(BaseModel):
    mode: Literal["rag", "no_answer", "fallback"]
    confidence: float = Field(ge=0.0, le=1.0)
    answer: str
    citations: list[Citation]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
