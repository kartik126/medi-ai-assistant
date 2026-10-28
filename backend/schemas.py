from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class SessionResponse(BaseModel):
    session_id: UUID


class DocumentResponse(BaseModel):
    document_id: UUID
    session_id: UUID
    filename: str
    status: Literal["ready"] = "ready"
    byte_count: int
    page_count: int
    indexed_page_count: int
    warning_pages: list[dict] = Field(default_factory=list)
    duplicate: bool = False


class FileResult(BaseModel):
    filename: str
    status: Literal["ready", "error"]
    document: DocumentResponse | None = None
    error_code: str | None = None
    message: str | None = None


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    document_ids: list[UUID] = Field(max_length=50)

    @field_validator("question")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Question cannot be blank")
        return value.strip()


class Citation(BaseModel):
    source_id: str
    document_id: UUID
    filename: str
    page_number: int
    chunk_id: UUID
    quote: str
    file_url: str
    page_text_url: str


class ChatResponse(BaseModel):
    searched_document_ids: list[UUID]
    status: Literal["answered", "insufficient_evidence"]
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)
    reason: Literal['insufficient_evidence', 'no_sources', 'no_documents',
                    'ambiguous_question', 'citation_validation_failed', 'unfilled_form'] | None = None
