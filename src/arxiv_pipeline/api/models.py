from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(
        min_length=3,
        max_length=2000,
        description="Question to answer from the arXiv Knowledge Base.",
    )
    number_of_results: int = Field(
        default=5,
        ge=1,
        le=20,
    )


class ResearchCitation(BaseModel):
    paper_id: str
    archive_id: str | None = None
    year: int | None = None
    month: int | None = None
    source_uri: str | None = None
    passage: str
    score: float | None = None


class AskResponse(BaseModel):
    answer: str
    citations: list[ResearchCitation]


class ResearchRequest(BaseModel):
    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
    }

    question: str = Field(
        min_length=3,
        max_length=2000,
    )
    max_papers: int = Field(
        default=5,
        ge=1,
        le=10,
        strict=True,
    )


class ConversationMessageRequest(BaseModel):
    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
    }

    message: str = Field(
        min_length=3,
        max_length=2000,
    )
    max_papers: int = Field(
        default=5,
        ge=1,
        le=10,
        strict=True,
    )


class WebsiteCitation(BaseModel):
    paper_id: str
    arxiv_url: str
    passage: str


class ConversationMessage(BaseModel):
    role: str
    content: str
    citations: list[WebsiteCitation] = []


class ConversationCreateResponse(BaseModel):
    conversation_id: str


class ConversationResponse(BaseModel):
    conversation_id: str
    messages: list[ConversationMessage]


class ConversationMessageResponse(BaseModel):
    request_id: str
    conversation_id: str
    message: ConversationMessage


class ResearchResponse(BaseModel):
    request_id: str
    question: str
    answer: str
    citations: list[WebsiteCitation]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    request_id: str
    error: ErrorDetail
