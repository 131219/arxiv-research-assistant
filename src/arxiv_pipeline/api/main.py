import logging
import os
import time
from functools import lru_cache
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse

from arxiv_pipeline.api.auth import (
    AuthenticationError,
    verify_cognito_access_token,
)
from arxiv_pipeline.api.bedrock_service import (
    BedrockKnowledgeBaseService,
)
from arxiv_pipeline.api.conversation_store import (
    DynamoDBConversationStore,
)
from arxiv_pipeline.api.models import (
    AskRequest,
    AskResponse,
    ConversationCreateResponse,
    ConversationMessage,
    ConversationMessageRequest,
    ConversationMessageResponse,
    ConversationResponse,
    ErrorDetail,
    ErrorResponse,
    ResearchRequest,
    ResearchResponse,
    WebsiteCitation,
)
from arxiv_pipeline.api.rate_limit import (
    DynamoDBResearchRateLimiter,
    ResearchRateLimiter,
)
from arxiv_pipeline.retrieval.service import (
    MalformedRetrievalResultError,
    PaperRetrievalService,
    RetrievalUnavailableError,
)
from arxiv_pipeline.synthesis.bedrock_backend import (
    BedrockGenerationBackend,
)
from arxiv_pipeline.synthesis.service import (
    CitationValidationError,
    SynthesisService,
    SynthesisUnavailableError,
)


logger = logging.getLogger(__name__)


app = FastAPI(
    title="arXiv Research Paper Assistant",
    description=(
        "Retrieve and answer questions from arXiv papers indexed "
        "in Amazon Bedrock Knowledge Bases."
    ),
    version="0.1.0",
)


@lru_cache
def get_bedrock_service() -> BedrockKnowledgeBaseService:
    return BedrockKnowledgeBaseService()


@lru_cache
def get_retrieval_service() -> PaperRetrievalService:
    return PaperRetrievalService(
        backend=get_bedrock_service(),
    )


@lru_cache
def get_rate_limiter() -> ResearchRateLimiter:
    region = os.getenv("AWS_REGION", "us-east-1")
    table_name = os.getenv("RESEARCH_RATE_LIMIT_TABLE_NAME")
    try:
        max_requests = int(
            os.getenv("RESEARCH_RATE_LIMIT_MAX_REQUESTS", "10")
        )
        window_seconds = int(
            os.getenv("RESEARCH_RATE_LIMIT_WINDOW_SECONDS", "60")
        )
    except ValueError as exc:
        raise RuntimeError(
            "Research rate-limit configuration must be integers."
        ) from exc

    if not table_name:
        raise RuntimeError(
            "RESEARCH_RATE_LIMIT_TABLE_NAME is not configured."
        )

    if max_requests <= 0 or window_seconds <= 0:
        raise RuntimeError(
            "Research rate-limit configuration must be positive."
        )

    dynamodb = boto3.resource(
        "dynamodb",
        region_name=region,
    )

    return DynamoDBResearchRateLimiter(
        table=dynamodb.Table(table_name),
        max_requests=max_requests,
        window_seconds=window_seconds,
        clock=time.time,
    )


@lru_cache
def get_conversation_store() -> DynamoDBConversationStore:
    region = os.getenv("AWS_REGION", "us-east-1")
    table_name = os.getenv("CONVERSATION_TABLE_NAME")

    if not table_name:
        raise RuntimeError(
            "CONVERSATION_TABLE_NAME is not configured."
        )

    dynamodb = boto3.resource(
        "dynamodb",
        region_name=region,
    )

    return DynamoDBConversationStore(
        table=dynamodb.Table(table_name),
        id_factory=lambda: str(uuid4()),
        clock=lambda: int(time.time()),
    )


@lru_cache
def get_synthesis_service() -> SynthesisService:
    region = os.getenv("AWS_REGION", "us-east-1")
    model_id = os.getenv(
        "BEDROCK_SYNTHESIS_MODEL_ID",
        "amazon.nova-lite-v1:0",
    )

    aws_config = Config(
        connect_timeout=3,
        read_timeout=10,
        retries={
            "max_attempts": 3,
            "mode": "standard",
        },
    )

    client = boto3.client(
        "bedrock-runtime",
        region_name=region,
        config=aws_config,
    )

    backend = BedrockGenerationBackend(
        client=client,
        model_id=model_id,
    )

    return SynthesisService(
        backend=backend,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "healthy",
        "service": "arxiv-research-paper-assistant",
    }


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    try:
        service = get_bedrock_service()

        answer, citations = service.ask(
            question=request.question,
            number_of_results=request.number_of_results,
        )

        return AskResponse(
            answer=answer,
            citations=citations,
        )

    except (ClientError, BotoCoreError) as error:
        raise HTTPException(
            status_code=502,
            detail=f"AWS Bedrock request failed: {error}",
        ) from error

    except ValueError as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        ) from error

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected API error: {error}",
        ) from error



@app.post(
    "/api/v1/conversations",
    response_model=ConversationCreateResponse,
)
def create_conversation(
    authorization: str | None = Header(default=None),
) -> ConversationCreateResponse:
    token = None

    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication is required.",
        )

    try:
        claims = verify_cognito_access_token(token)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            detail="Authentication is required.",
        ) from exc

    user_id = claims.get("sub")

    conversation_id = get_conversation_store().create_conversation(
        user_id=user_id,
    )

    return ConversationCreateResponse(
        conversation_id=conversation_id,
    )


@app.get(
    "/api/v1/conversations/{conversation_id}",
    response_model=ConversationResponse,
)
def get_conversation(
    conversation_id: str,
    authorization: str | None = Header(default=None),
) -> ConversationResponse:
    token = None

    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication is required.",
        )

    try:
        claims = verify_cognito_access_token(token)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            detail="Authentication is required.",
        ) from exc

    user_id = claims.get("sub")
    conversation_store = get_conversation_store()

    if not conversation_store.conversation_exists(
        user_id=user_id,
        conversation_id=conversation_id,
    ):
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    messages = conversation_store.get_messages(
        user_id=user_id,
        conversation_id=conversation_id,
        limit=100,
    )

    return ConversationResponse(
        conversation_id=conversation_id,
        messages=[
            ConversationMessage(
                role=message["role"],
                content=message["content"],
                citations=message.get("citations", []),
            )
            for message in messages
        ],
    )


@app.post(
    "/api/v1/conversations/{conversation_id}/messages",
    response_model=ConversationMessageResponse,
)
def send_conversation_message(
    conversation_id: str,
    request: ConversationMessageRequest,
    authorization: str | None = Header(default=None),
) -> ConversationMessageResponse:
    request_id = str(uuid4())

    token = None

    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication is required.",
        )

    try:
        claims = verify_cognito_access_token(token)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            detail="Authentication is required.",
        ) from exc

    user_id = claims.get("sub")
    conversation_store = get_conversation_store()

    if not conversation_store.conversation_exists(
        user_id=user_id,
        conversation_id=conversation_id,
    ):
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    rate_limiter = get_rate_limiter()

    try:
        allowed = rate_limiter.allow(user_id=user_id)
    except Exception:
        error_response = ErrorResponse(
            request_id=request_id,
            error=ErrorDetail(
                code="INTERNAL_ERROR",
                message="An unexpected internal error occurred.",
            ),
        )

        return JSONResponse(
            status_code=500,
            content=error_response.model_dump(),
            headers={
                "X-Request-ID": request_id,
                "Cache-Control": "no-store",
            },
        )

    if not allowed:
        error_response = ErrorResponse(
            request_id=request_id,
            error=ErrorDetail(
                code="RATE_LIMIT_EXCEEDED",
                message="Too many research requests. Please try again later.",
            ),
        )

        return JSONResponse(
            status_code=429,
            content=error_response.model_dump(),
            headers={
                "X-Request-ID": request_id,
                "Cache-Control": "no-store",
            },
        )

    history = conversation_store.get_messages(
        user_id=user_id,
        conversation_id=conversation_id,
        limit=20,
    )

    user_history = [
        message
        for message in history
        if message.get("role") == "user"
    ]

    retrieval_service = get_retrieval_service()

    papers = retrieval_service.search(
        query=request.message,
        max_papers=request.max_papers,
        conversation_history=user_history,
    )

    conversation_store.add_message(
        user_id=user_id,
        conversation_id=conversation_id,
        role="user",
        content=request.message,
        citations=[],
    )

    if not papers:
        answer = (
            "I could not find enough relevant research evidence "
            "to answer this question."
        )
        citations = []
    else:
        try:
            synthesis_result = get_synthesis_service().synthesize(
                question=request.message,
                papers=papers,
                conversation_history=user_history,
            )
        except (
            SynthesisUnavailableError,
            CitationValidationError,
        ) as exc:
            logger.warning(
                "Conversation synthesis unavailable "
                "request_id=%s conversation_id=%s error_type=%s error=%s",
                request_id,
                conversation_id,
                type(exc).__name__,
                str(exc),
            )

            error_response = ErrorResponse(
                request_id=request_id,
                error=ErrorDetail(
                    code="RESEARCH_UNAVAILABLE",
                    message="Research service is temporarily unavailable.",
                ),
            )

            return JSONResponse(
                status_code=503,
                content=error_response.model_dump(),
                headers={
                    "X-Request-ID": request_id,
                    "Cache-Control": "no-store",
                },
            )

        except Exception:
            logger.exception(
                "Unexpected conversation synthesis failure "
                "request_id=%s conversation_id=%s",
                request_id,
                conversation_id,
            )

            error_response = ErrorResponse(
                request_id=request_id,
                error=ErrorDetail(
                    code="INTERNAL_ERROR",
                    message="An internal error occurred.",
                ),
            )

            return JSONResponse(
                status_code=500,
                content=error_response.model_dump(),
                headers={
                    "X-Request-ID": request_id,
                    "Cache-Control": "no-store",
                },
            )

        citations = [
            WebsiteCitation(
                paper_id=paper.paper_id,
                arxiv_url=paper.arxiv_url,
                passage=paper.passage,
            )
            for paper in synthesis_result.cited_papers
        ]

        answer = synthesis_result.answer

    citation_items = [
        citation.model_dump()
        for citation in citations
    ]

    conversation_store.add_message(
        user_id=user_id,
        conversation_id=conversation_id,
        role="assistant",
        content=answer,
        citations=citation_items,
    )

    return ConversationMessageResponse(
        request_id=request_id,
        conversation_id=conversation_id,
        message=ConversationMessage(
            role="assistant",
            content=answer,
            citations=citations,
        ),
    )


@app.post("/api/v1/research", response_model=ResearchResponse)
def research(
    request: ResearchRequest,
    response: Response,
    authorization: str | None = Header(default=None),
) -> ResearchResponse:
    request_id = str(uuid4())

    response.headers["X-Request-ID"] = request_id
    response.headers["Cache-Control"] = "no-store"

    token = None

    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()

    if not token:
        error_response = ErrorResponse(
            request_id=request_id,
            error=ErrorDetail(
                code="AUTHENTICATION_REQUIRED",
                message="Authentication is required.",
            ),
        )

        return JSONResponse(
            status_code=401,
            content=error_response.model_dump(),
            headers={
                "X-Request-ID": request_id,
                "Cache-Control": "no-store",
            },
        )

    try:
        claims = verify_cognito_access_token(token)
    except AuthenticationError:
        error_response = ErrorResponse(
            request_id=request_id,
            error=ErrorDetail(
                code="AUTHENTICATION_REQUIRED",
                message="Authentication is required.",
            ),
        )

        return JSONResponse(
            status_code=401,
            content=error_response.model_dump(),
            headers={
                "X-Request-ID": request_id,
                "Cache-Control": "no-store",
            },
        )

    user_id = claims.get("sub")
    rate_limiter = get_rate_limiter()

    try:
        allowed = rate_limiter.allow(user_id=user_id)
    except Exception:
        error_response = ErrorResponse(
            request_id=request_id,
            error=ErrorDetail(
                code="INTERNAL_ERROR",
                message="An unexpected internal error occurred.",
            ),
        )
        return JSONResponse(
            status_code=500,
            content=error_response.model_dump(),
            headers={
                "X-Request-ID": request_id,
                "Cache-Control": "no-store",
            },
        )

    if not allowed:
        error_response = ErrorResponse(
            request_id=request_id,
            error=ErrorDetail(
                code="RATE_LIMIT_EXCEEDED",
                message="Too many research requests. Please try again later.",
            ),
        )

        return JSONResponse(
            status_code=429,
            content=error_response.model_dump(),
            headers={
                "X-Request-ID": request_id,
                "Cache-Control": "no-store",
            },
        )

    retrieval_service = get_retrieval_service()

    try:
        papers = retrieval_service.search(
            query=request.question,
            max_papers=request.max_papers,
        )
    except (
        RetrievalUnavailableError,
        MalformedRetrievalResultError,
    ):
        error_response = ErrorResponse(
            request_id=request_id,
            error=ErrorDetail(
                code="RESEARCH_UNAVAILABLE",
                message="Research service is temporarily unavailable.",
            ),
        )

        return JSONResponse(
            status_code=503,
            content=error_response.model_dump(),
            headers={
                "X-Request-ID": request_id,
                "Cache-Control": "no-store",
            },
        )

    except Exception:
        error_response = ErrorResponse(
            request_id=request_id,
            error=ErrorDetail(
                code="INTERNAL_ERROR",
                message="An internal error occurred.",
            ),
        )

        return JSONResponse(
            status_code=500,
            content=error_response.model_dump(),
            headers={
                "X-Request-ID": request_id,
                "Cache-Control": "no-store",
            },
        )

    if not papers:
        return ResearchResponse(
            request_id=request_id,
            question=request.question,
            answer=(
                "I could not find enough relevant research evidence "
                "to answer this question."
            ),
            citations=[],
        )

    synthesis_service = get_synthesis_service()

    try:
        synthesis_result = synthesis_service.synthesize(
            question=request.question,
            papers=papers,
        )
    except (
        SynthesisUnavailableError,
        CitationValidationError,
    ):
        error_response = ErrorResponse(
            request_id=request_id,
            error=ErrorDetail(
                code="RESEARCH_UNAVAILABLE",
                message="Research service is temporarily unavailable.",
            ),
        )

        return JSONResponse(
            status_code=503,
            content=error_response.model_dump(),
            headers={
                "X-Request-ID": request_id,
                "Cache-Control": "no-store",
            },
        )

    except Exception:
        error_response = ErrorResponse(
            request_id=request_id,
            error=ErrorDetail(
                code="INTERNAL_ERROR",
                message="An internal error occurred.",
            ),
        )

        return JSONResponse(
            status_code=500,
            content=error_response.model_dump(),
            headers={
                "X-Request-ID": request_id,
                "Cache-Control": "no-store",
            },
        )

    citations = [
        WebsiteCitation(
            paper_id=paper.paper_id,
            arxiv_url=paper.arxiv_url,
            passage=paper.passage,
        )
        for paper in synthesis_result.cited_papers
    ]

    return ResearchResponse(
        request_id=request_id,
        question=request.question,
        answer=synthesis_result.answer,
        citations=citations,
    )
