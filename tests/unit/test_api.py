from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from arxiv_pipeline.api.main import app, get_bedrock_service
from arxiv_pipeline.api.models import (
    ResearchCitation,
    ResearchRequest,
)
from arxiv_pipeline.api.auth import AuthenticationError
from arxiv_pipeline.retrieval.models import RetrievedPaper
from arxiv_pipeline.retrieval.service import RetrievalUnavailableError


client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_cached_service(monkeypatch):
    get_bedrock_service.cache_clear()

    from arxiv_pipeline.api.main import get_rate_limiter

    get_rate_limiter.cache_clear()

    monkeypatch.setenv(
        "RESEARCH_RATE_LIMIT_TABLE_NAME",
        "research-rate-limit-test",
    )

    with (
        patch(
            "arxiv_pipeline.api.main.verify_cognito_access_token",
            return_value={
                "sub": "test-user",
                "token_use": "access",
            },
        ),
        patch(
            "arxiv_pipeline.api.main.boto3.resource",
        ) as dynamodb_resource,
    ):
        table = MagicMock()
        dynamodb_resource.return_value.Table.return_value = table

        yield

    get_bedrock_service.cache_clear()
    get_rate_limiter.cache_clear()


def test_ask_returns_answer_and_citations():
    service = MagicMock()

    service.ask.return_value = (
        "Transformers use self-attention [Source 1].",
        [
            ResearchCitation(
                paper_id="2606.12345",
                archive_id="arXiv_pdf_2606_001",
                year=2026,
                month=6,
                source_uri="s3://bucket/2606.12345.md",
                passage="Relevant transformer passage.",
                score=0.91,
            )
        ],
    )

    with patch(
        "arxiv_pipeline.api.main.get_bedrock_service",
        return_value=service,
    ):
        response = client.post(
            "/ask",
            json={
                "question": "How does transformer attention work?",
                "number_of_results": 5,
            },
        )

    assert response.status_code == 200

    body = response.json()

    assert body["answer"] == (
        "Transformers use self-attention [Source 1]."
    )
    assert len(body["citations"]) == 1
    citation = body["citations"][0]

    assert citation["paper_id"] == "2606.12345"
    assert citation["archive_id"] == "arXiv_pdf_2606_001"
    assert citation["year"] == 2026
    assert citation["month"] == 6
    assert citation["source_uri"] == "s3://bucket/2606.12345.md"
    assert citation["passage"] == "Relevant transformer passage."
    assert citation["score"] == 0.91
    assert "metadata" not in citation

    service.ask.assert_called_once_with(
        question="How does transformer attention work?",
        number_of_results=5,
    )


def test_ask_rejects_too_short_question():
    response = client.post(
        "/ask",
        json={
            "question": "a",
            "number_of_results": 5,
        },
    )

    assert response.status_code == 422


def test_ask_returns_502_for_bedrock_client_error():
    service = MagicMock()

    service.ask.side_effect = ClientError(
        error_response={
            "Error": {
                "Code": "ThrottlingException",
                "Message": "Rate exceeded",
            }
        },
        operation_name="Retrieve",
    )

    with patch(
        "arxiv_pipeline.api.main.get_bedrock_service",
        return_value=service,
    ):
        response = client.post(
            "/ask",
            json={
                "question": "Explain transformer attention",
                "number_of_results": 5,
            },
        )

    assert response.status_code == 502
    assert "AWS Bedrock request failed" in response.json()["detail"]


def test_ask_returns_500_for_missing_model_configuration():
    service = MagicMock()

    service.ask.side_effect = ValueError(
        "BEDROCK_MODEL_ID is required for answer generation."
    )

    with patch(
        "arxiv_pipeline.api.main.get_bedrock_service",
        return_value=service,
    ):
        response = client.post(
            "/ask",
            json={
                "question": "Explain transformer attention",
                "number_of_results": 5,
            },
        )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "BEDROCK_MODEL_ID is required for answer generation."
    )


def test_research_request_trims_question_and_defaults_max_papers():
    request = ResearchRequest(
        question="   How does transformer attention work?   "
    )

    assert request.question == "How does transformer attention work?"
    assert request.max_papers == 5


def test_research_request_rejects_unknown_fields():
    with pytest.raises(ValueError):
        ResearchRequest(
            question="How does transformer attention work?",
            max_papers=5,
            unexpected="not-allowed",
        )


@pytest.mark.parametrize(
    "invalid_max_papers",
    [
        0,
        11,
        5.0,
        "5",
        True,
        None,
    ],
)
def test_research_request_rejects_invalid_max_papers(invalid_max_papers):
    with pytest.raises(ValueError):
        ResearchRequest(
            question="How does transformer attention work?",
            max_papers=invalid_max_papers,
        )


def test_research_endpoint_uses_shared_retrieval_service():
    from arxiv_pipeline.synthesis.models import SynthesisResult

    retrieval_service = MagicMock()
    synthesis_service = MagicMock()

    paper = RetrievedPaper(
        paper_id="2606.12345",
        archive_id="arXiv_pdf_2606_001",
        year=2026,
        month=6,
        passage="Relevant transformer passage.",
        arxiv_url="https://arxiv.org/abs/2606.12345",
        source_uri="s3://bucket/2606.12345.md",
        score=0.91,
    )

    retrieval_service.search.return_value = [
        paper,
    ]

    synthesis_service.synthesize.return_value = SynthesisResult(
        answer="Transformer attention uses relevant evidence [2606.12345].",
        cited_papers=[paper],
    )

    with (
        patch(
            "arxiv_pipeline.api.main.get_retrieval_service",
            return_value=retrieval_service,
        ),
        patch(
            "arxiv_pipeline.api.main.get_synthesis_service",
            return_value=synthesis_service,
        ),
    ):
        response = client.post(
            "/api/v1/research",
            headers={
                "Authorization": "Bearer test-token",
            },
            json={
                "question": "How does transformer attention work?",
                "max_papers": 5,
            },
        )

    assert response.status_code == 200

    body = response.json()

    assert body["request_id"]
    assert response.headers["X-Request-ID"] == body["request_id"]
    assert response.headers["Cache-Control"] == "no-store"

    assert body["question"] == "How does transformer attention work?"
    assert body["citations"] == [
        {
            "paper_id": "2606.12345",
            "arxiv_url": "https://arxiv.org/abs/2606.12345",
            "passage": "Relevant transformer passage.",
        }
    ]

    assert "source_uri" not in body["citations"][0]
    assert "score" not in body["citations"][0]

    retrieval_service.search.assert_called_once_with(
        query="How does transformer attention work?",
        max_papers=5,
    )


def test_research_returns_503_when_retrieval_is_unavailable():
    retrieval_service = MagicMock()

    retrieval_service.search.side_effect = RetrievalUnavailableError(
        "Bedrock retrieval is temporarily unavailable"
    )

    with patch(
        "arxiv_pipeline.api.main.get_retrieval_service",
        return_value=retrieval_service,
    ):
        response = client.post(
            "/api/v1/research",
            headers={
                "Authorization": "Bearer test-token",
            },
            json={
                "question": "How does transformer attention work?",
                "max_papers": 5,
            },
        )

    assert response.status_code == 503

    body = response.json()

    assert body["request_id"]
    assert response.headers["X-Request-ID"] == body["request_id"]
    assert body["error"] == {
        "code": "RESEARCH_UNAVAILABLE",
        "message": "Research service is temporarily unavailable.",
    }

    assert "Bedrock" not in response.text


def test_research_returns_503_for_malformed_retrieval_result():
    retrieval_service = MagicMock()

    from arxiv_pipeline.retrieval.service import (
        MalformedRetrievalResultError,
    )

    retrieval_service.search.side_effect = MalformedRetrievalResultError(
        "retrieval result metadata must be a dictionary"
    )

    with patch(
        "arxiv_pipeline.api.main.get_retrieval_service",
        return_value=retrieval_service,
    ):
        response = client.post(
            "/api/v1/research",
            headers={
                "Authorization": "Bearer test-token",
            },
            json={
                "question": "How does transformer attention work?",
                "max_papers": 5,
            },
        )

    assert response.status_code == 503

    body = response.json()

    assert body["error"] == {
        "code": "RESEARCH_UNAVAILABLE",
        "message": "Research service is temporarily unavailable.",
    }

    assert "metadata" not in response.text


def test_research_returns_500_for_unexpected_internal_error():
    retrieval_service = MagicMock()

    retrieval_service.search.side_effect = RuntimeError(
        "sensitive internal failure"
    )

    with patch(
        "arxiv_pipeline.api.main.get_retrieval_service",
        return_value=retrieval_service,
    ):
        response = client.post(
            "/api/v1/research",
            headers={
                "Authorization": "Bearer test-token",
            },
            json={
                "question": "How does transformer attention work?",
                "max_papers": 5,
            },
        )

    assert response.status_code == 500

    body = response.json()

    assert body["request_id"]
    assert response.headers["X-Request-ID"] == body["request_id"]

    assert body["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "An internal error occurred.",
    }

    assert "sensitive internal failure" not in response.text


def test_research_returns_200_with_empty_citations_when_no_evidence_found():
    retrieval_service = MagicMock()

    retrieval_service.search.return_value = []

    with patch(
        "arxiv_pipeline.api.main.get_retrieval_service",
        return_value=retrieval_service,
    ):
        response = client.post(
            "/api/v1/research",
            headers={
                "Authorization": "Bearer test-token",
            },
            json={
                "question": "How does transformer attention work?",
                "max_papers": 5,
            },
        )

    assert response.status_code == 200

    body = response.json()

    assert body["request_id"]
    assert body["question"] == "How does transformer attention work?"
    assert body["citations"] == []
    assert body["answer"] == (
        "I could not find enough relevant research evidence "
        "to answer this question."
    )


def test_research_requires_bearer_token_before_retrieval():
    retrieval_service = MagicMock()

    with patch(
        "arxiv_pipeline.api.main.get_retrieval_service",
        return_value=retrieval_service,
    ):
        response = client.post(
            "/api/v1/research",
            json={
                "question": "How does transformer attention work?",
                "max_papers": 5,
            },
        )

    assert response.status_code == 401

    body = response.json()

    assert body["request_id"]
    assert response.headers["X-Request-ID"] == body["request_id"]

    assert body["error"] == {
        "code": "AUTHENTICATION_REQUIRED",
        "message": "Authentication is required.",
    }

    retrieval_service.search.assert_not_called()


@pytest.mark.parametrize(
    "authorization",
    [
        "Basic abc123",
        "Bearer",
        "Bearer ",
    ],
)
def test_research_rejects_malformed_authorization_header(authorization):
    retrieval_service = MagicMock()

    with patch(
        "arxiv_pipeline.api.main.get_retrieval_service",
        return_value=retrieval_service,
    ):
        response = client.post(
            "/api/v1/research",
            headers={
                "Authorization": authorization,
            },
            json={
                "question": "How does transformer attention work?",
                "max_papers": 5,
            },
        )

    assert response.status_code == 401

    body = response.json()

    assert body["error"] == {
        "code": "AUTHENTICATION_REQUIRED",
        "message": "Authentication is required.",
    }

    retrieval_service.search.assert_not_called()


def test_research_returns_401_for_invalid_access_token():
    retrieval_service = MagicMock()

    with patch(
        "arxiv_pipeline.api.main.get_retrieval_service",
        return_value=retrieval_service,
    ), patch(
        "arxiv_pipeline.api.main.verify_cognito_access_token",
        side_effect=AuthenticationError("Invalid access token."),
        create=True,
    ):
        response = client.post(
            "/api/v1/research",
            headers={
                "Authorization": "Bearer invalid-token",
            },
            json={
                "question": "How does transformer attention work?",
                "max_papers": 5,
            },
        )

    assert response.status_code == 401

    body = response.json()

    assert body["error"] == {
        "code": "AUTHENTICATION_REQUIRED",
        "message": "Authentication is required.",
    }

    assert response.headers["X-Request-ID"] == body["request_id"]
    assert "Invalid access token" not in response.text

    retrieval_service.search.assert_not_called()


def test_get_synthesis_service_builds_bedrock_generation_backend(monkeypatch):
    monkeypatch.setenv(
        "BEDROCK_SYNTHESIS_MODEL_ID",
        "amazon.nova-lite-v1:0",
    )
    monkeypatch.setenv(
        "AWS_REGION",
        "us-east-1",
    )

    with patch("arxiv_pipeline.api.main.boto3.client") as boto3_client:
        from arxiv_pipeline.api.main import get_synthesis_service

        get_synthesis_service.cache_clear()

        service = get_synthesis_service()

        boto3_client.assert_called_once()

        _, kwargs = boto3_client.call_args

        assert boto3_client.call_args.args[0] == "bedrock-runtime"
        assert kwargs["region_name"] == "us-east-1"

        assert service._backend._model_id == "amazon.nova-lite-v1:0"

        get_synthesis_service.cache_clear()


def test_research_endpoint_synthesizes_answer_and_returns_only_cited_papers():
    from arxiv_pipeline.synthesis.models import SynthesisResult

    retrieval_service = MagicMock()
    synthesis_service = MagicMock()

    paper_one = RetrievedPaper(
        paper_id="2606.11111",
        passage="Sparse attention reduces computation.",
        arxiv_url="https://arxiv.org/abs/2606.11111",
    )

    paper_two = RetrievedPaper(
        paper_id="2606.22222",
        passage="Another method reduces memory use.",
        arxiv_url="https://arxiv.org/abs/2606.22222",
    )

    retrieval_service.search.return_value = [
        paper_one,
        paper_two,
    ]

    synthesis_service.synthesize.return_value = SynthesisResult(
        answer=(
            "Sparse attention can reduce computation "
            "[2606.11111]."
        ),
        cited_papers=[
            paper_one,
        ],
    )

    with (
        patch(
            "arxiv_pipeline.api.main.get_retrieval_service",
            return_value=retrieval_service,
        ),
        patch(
            "arxiv_pipeline.api.main.get_synthesis_service",
            return_value=synthesis_service,
        ),
    ):
        response = client.post(
            "/api/v1/research",
            headers={
                "Authorization": "Bearer test-token",
            },
            json={
                "question": "How can attention be more efficient?",
                "max_papers": 5,
            },
        )

    assert response.status_code == 200

    body = response.json()

    assert body["answer"] == (
        "Sparse attention can reduce computation "
        "[2606.11111]."
    )

    assert body["citations"] == [
        {
            "paper_id": "2606.11111",
            "arxiv_url": "https://arxiv.org/abs/2606.11111",
            "passage": "Sparse attention reduces computation.",
        }
    ]

    synthesis_service.synthesize.assert_called_once_with(
        question="How can attention be more efficient?",
        papers=[
            paper_one,
            paper_two,
        ],
    )


def test_research_returns_503_when_synthesis_is_unavailable():
    from arxiv_pipeline.synthesis.service import SynthesisUnavailableError

    retrieval_service = MagicMock()
    synthesis_service = MagicMock()

    paper = RetrievedPaper(
        paper_id="2606.11111",
        passage="Relevant evidence.",
        arxiv_url="https://arxiv.org/abs/2606.11111",
    )

    retrieval_service.search.return_value = [paper]

    synthesis_service.synthesize.side_effect = SynthesisUnavailableError(
        "generation is temporarily unavailable"
    )

    with (
        patch(
            "arxiv_pipeline.api.main.get_retrieval_service",
            return_value=retrieval_service,
        ),
        patch(
            "arxiv_pipeline.api.main.get_synthesis_service",
            return_value=synthesis_service,
        ),
    ):
        response = client.post(
            "/api/v1/research",
            headers={
                "Authorization": "Bearer test-token",
            },
            json={
                "question": "How can attention be more efficient?",
                "max_papers": 5,
            },
        )

    assert response.status_code == 503

    body = response.json()

    assert body["error"] == {
        "code": "RESEARCH_UNAVAILABLE",
        "message": "Research service is temporarily unavailable.",
    }

    assert "generation is temporarily unavailable" not in response.text


def test_research_returns_503_when_generated_citations_are_invalid():
    from arxiv_pipeline.synthesis.service import CitationValidationError

    retrieval_service = MagicMock()
    synthesis_service = MagicMock()

    paper = RetrievedPaper(
        paper_id="2606.11111",
        passage="Relevant evidence.",
        arxiv_url="https://arxiv.org/abs/2606.11111",
    )

    retrieval_service.search.return_value = [paper]

    synthesis_service.synthesize.side_effect = CitationValidationError(
        "unsupported citation: 9999.99999"
    )

    with (
        patch(
            "arxiv_pipeline.api.main.get_retrieval_service",
            return_value=retrieval_service,
        ),
        patch(
            "arxiv_pipeline.api.main.get_synthesis_service",
            return_value=synthesis_service,
        ),
    ):
        response = client.post(
            "/api/v1/research",
            headers={
                "Authorization": "Bearer test-token",
            },
            json={
                "question": "How can attention be more efficient?",
                "max_papers": 5,
            },
        )

    assert response.status_code == 503

    body = response.json()

    assert body["error"] == {
        "code": "RESEARCH_UNAVAILABLE",
        "message": "Research service is temporarily unavailable.",
    }

    assert "unsupported citation" not in response.text


def test_research_returns_500_for_unexpected_synthesis_error():
    retrieval_service = MagicMock()
    synthesis_service = MagicMock()

    paper = RetrievedPaper(
        paper_id="2606.12345",
        archive_id="arXiv_pdf_2606_001",
        year=2026,
        month=6,
        passage="Relevant transformer passage.",
        arxiv_url="https://arxiv.org/abs/2606.12345",
        source_uri="s3://bucket/2606.12345.md",
        score=0.91,
    )

    retrieval_service.search.return_value = [paper]

    synthesis_service.synthesize.side_effect = RuntimeError(
        "sensitive synthesis failure"
    )

    with (
        patch(
            "arxiv_pipeline.api.main.get_retrieval_service",
            return_value=retrieval_service,
        ),
        patch(
            "arxiv_pipeline.api.main.get_synthesis_service",
            return_value=synthesis_service,
        ),
    ):
        response = client.post(
            "/api/v1/research",
            headers={
                "Authorization": "Bearer test-token",
            },
            json={
                "question": "How does transformer attention work?",
                "max_papers": 5,
            },
        )

    assert response.status_code == 500

    body = response.json()

    assert body["request_id"]
    assert response.headers["X-Request-ID"] == body["request_id"]
    assert response.headers["Cache-Control"] == "no-store"

    assert body["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "An internal error occurred.",
    }

    assert "sensitive synthesis failure" not in response.text


def test_research_synthesis_receives_original_user_question():
    from arxiv_pipeline.synthesis.models import SynthesisResult

    retrieval_service = MagicMock()
    retrieval_service.search.return_value = [
        RetrievedPaper(
            paper_id="2606.00001",
            archive_id="arxiv",
            year=2026,
            month=6,
            passage="Relevant evidence.",
            arxiv_url="https://arxiv.org/abs/2606.00001",
            source_uri="s3://bucket/paper.md",
            score=0.9,
        )
    ]

    synthesis_service = MagicMock()
    synthesis_service.synthesize.return_value = SynthesisResult(
        answer="Synthesized answer [2606.00001]",
        cited_papers=retrieval_service.search.return_value,
    )

    original_question = (
        "What approaches improve transformer attention efficiency?"
    )

    with (
        patch(
            "arxiv_pipeline.api.main.get_retrieval_service",
            return_value=retrieval_service,
        ),
        patch(
            "arxiv_pipeline.api.main.get_synthesis_service",
            return_value=synthesis_service,
        ),
    ):
        response = client.post(
            "/api/v1/research",
            json={
                "question": original_question,
                "max_papers": 5,
            },
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200

    synthesis_service.synthesize.assert_called_once()

    _, kwargs = synthesis_service.synthesize.call_args
    assert kwargs["question"] == original_question


def test_research_returns_429_when_user_rate_limit_is_exceeded():
    rate_limiter = MagicMock()
    rate_limiter.allow.return_value = False

    retrieval_service = MagicMock()
    synthesis_service = MagicMock()

    with (
        patch(
            "arxiv_pipeline.api.main.verify_cognito_access_token",
            return_value={
                "sub": "rate-limited-user",
                "token_use": "access",
            },
        ),
        patch(
            "arxiv_pipeline.api.main.get_rate_limiter",
            return_value=rate_limiter,
        ),
        patch(
            "arxiv_pipeline.api.main.get_retrieval_service",
            return_value=retrieval_service,
        ),
        patch(
            "arxiv_pipeline.api.main.get_synthesis_service",
            return_value=synthesis_service,
        ),
    ):
        response = client.post(
            "/api/v1/research",
            json={
                "question": "How does transformer attention work?",
                "max_papers": 5,
            },
            headers={
                "Authorization": "Bearer test-token",
            },
        )

    assert response.status_code == 429

    body = response.json()

    assert body["error"] == {
        "code": "RATE_LIMIT_EXCEEDED",
        "message": "Too many research requests. Please try again later.",
    }

    assert body["request_id"]
    assert response.headers["X-Request-ID"] == body["request_id"]
    assert response.headers["Cache-Control"] == "no-store"

    rate_limiter.allow.assert_called_once_with(
        user_id="rate-limited-user",
    )

    retrieval_service.search.assert_not_called()
    synthesis_service.synthesize.assert_not_called()


def test_research_returns_500_when_rate_limiter_fails():
    rate_limiter = MagicMock()
    retrieval_service = MagicMock()

    rate_limiter.allow.side_effect = RuntimeError(
        "sensitive rate limiter failure"
    )

    with (
        patch(
            "arxiv_pipeline.api.main.get_rate_limiter",
            return_value=rate_limiter,
        ),
        patch(
            "arxiv_pipeline.api.main.get_retrieval_service",
            return_value=retrieval_service,
        ),
    ):
        response = client.post(
            "/api/v1/research",
            headers={
                "Authorization": "Bearer test-token",
            },
            json={
                "question": "How does transformer attention work?",
                "max_papers": 5,
            },
        )

    assert response.status_code == 500

    body = response.json()

    assert body["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "An unexpected internal error occurred.",
    }
    assert body["request_id"]
    assert response.headers["X-Request-ID"] == body["request_id"]
    assert response.headers["Cache-Control"] == "no-store"

    rate_limiter.allow.assert_called_once_with(
        user_id="test-user",
    )
    retrieval_service.search.assert_not_called()


def test_research_allows_authenticated_user_within_rate_limit():
    from arxiv_pipeline.synthesis.models import SynthesisResult

    rate_limiter = MagicMock()
    rate_limiter.allow.return_value = True

    paper = RetrievedPaper(
        paper_id="2606.12345",
        archive_id="arXiv_pdf_2606_001",
        year=2026,
        month=6,
        passage="Relevant transformer passage.",
        arxiv_url="https://arxiv.org/abs/2606.12345",
        source_uri="s3://bucket/2606.12345.md",
        score=0.91,
    )

    retrieval_service = MagicMock()
    retrieval_service.search.return_value = [paper]

    synthesis_service = MagicMock()
    synthesis_service.synthesize.return_value = SynthesisResult(
        answer="Transformer attention uses relevant evidence [2606.12345].",
        cited_papers=[paper],
    )

    with (
        patch(
            "arxiv_pipeline.api.main.verify_cognito_access_token",
            return_value={
                "sub": "allowed-user",
                "token_use": "access",
            },
        ),
        patch(
            "arxiv_pipeline.api.main.get_rate_limiter",
            return_value=rate_limiter,
        ),
        patch(
            "arxiv_pipeline.api.main.get_retrieval_service",
            return_value=retrieval_service,
        ),
        patch(
            "arxiv_pipeline.api.main.get_synthesis_service",
            return_value=synthesis_service,
        ),
    ):
        response = client.post(
            "/api/v1/research",
            json={
                "question": "How does transformer attention work?",
                "max_papers": 5,
            },
            headers={
                "Authorization": "Bearer test-token",
            },
        )

    assert response.status_code == 200

    rate_limiter.allow.assert_called_once_with(
        user_id="allowed-user",
    )

    retrieval_service.search.assert_called_once_with(
        query="How does transformer attention work?",
        max_papers=5,
    )

    synthesis_service.synthesize.assert_called_once_with(
        question="How does transformer attention work?",
        papers=[paper],
    )


def test_get_rate_limiter_builds_dynamodb_limiter_from_environment(monkeypatch):
    from arxiv_pipeline.api.main import get_rate_limiter
    from arxiv_pipeline.api.rate_limit import DynamoDBResearchRateLimiter

    monkeypatch.setenv(
        "RESEARCH_RATE_LIMIT_TABLE_NAME",
        "research-rate-limit-test",
    )
    monkeypatch.setenv(
        "RESEARCH_RATE_LIMIT_MAX_REQUESTS",
        "10",
    )
    monkeypatch.setenv(
        "RESEARCH_RATE_LIMIT_WINDOW_SECONDS",
        "60",
    )

    get_rate_limiter.cache_clear()

    with patch("arxiv_pipeline.api.main.boto3.resource") as resource:
        table = MagicMock()
        resource.return_value.Table.return_value = table

        limiter = get_rate_limiter()

    assert isinstance(limiter, DynamoDBResearchRateLimiter)

    resource.assert_called_once_with(
        "dynamodb",
        region_name="us-east-1",
    )
    resource.return_value.Table.assert_called_once_with(
        "research-rate-limit-test"
    )

    get_rate_limiter.cache_clear()


def test_get_rate_limiter_requires_table_name(monkeypatch):
    from arxiv_pipeline.api.main import get_rate_limiter

    monkeypatch.delenv(
        "RESEARCH_RATE_LIMIT_TABLE_NAME",
        raising=False,
    )

    get_rate_limiter.cache_clear()

    with pytest.raises(
        RuntimeError,
        match="RESEARCH_RATE_LIMIT_TABLE_NAME is not configured",
    ):
        get_rate_limiter()

    get_rate_limiter.cache_clear()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RESEARCH_RATE_LIMIT_MAX_REQUESTS", "0"),
        ("RESEARCH_RATE_LIMIT_MAX_REQUESTS", "-1"),
        ("RESEARCH_RATE_LIMIT_WINDOW_SECONDS", "0"),
        ("RESEARCH_RATE_LIMIT_WINDOW_SECONDS", "-60"),
    ],
)
def test_get_rate_limiter_rejects_non_positive_numeric_config(
    monkeypatch,
    name,
    value,
):
    from arxiv_pipeline.api.main import get_rate_limiter

    monkeypatch.setenv(
        "RESEARCH_RATE_LIMIT_TABLE_NAME",
        "research-rate-limit-test",
    )
    monkeypatch.setenv(
        "RESEARCH_RATE_LIMIT_MAX_REQUESTS",
        "10",
    )
    monkeypatch.setenv(
        "RESEARCH_RATE_LIMIT_WINDOW_SECONDS",
        "60",
    )
    monkeypatch.setenv(name, value)

    get_rate_limiter.cache_clear()

    with pytest.raises(
        RuntimeError,
        match="Research rate-limit configuration must be positive",
    ):
        get_rate_limiter()

    get_rate_limiter.cache_clear()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RESEARCH_RATE_LIMIT_MAX_REQUESTS", "abc"),
        ("RESEARCH_RATE_LIMIT_WINDOW_SECONDS", "xyz"),
    ],
)
def test_get_rate_limiter_rejects_non_numeric_config(
    monkeypatch,
    name,
    value,
):
    from arxiv_pipeline.api.main import get_rate_limiter

    monkeypatch.setenv(
        "RESEARCH_RATE_LIMIT_TABLE_NAME",
        "research-rate-limit-test",
    )
    monkeypatch.setenv(
        "RESEARCH_RATE_LIMIT_MAX_REQUESTS",
        "10",
    )
    monkeypatch.setenv(
        "RESEARCH_RATE_LIMIT_WINDOW_SECONDS",
        "60",
    )
    monkeypatch.setenv(name, value)

    get_rate_limiter.cache_clear()

    with pytest.raises(
        RuntimeError,
        match="Research rate-limit configuration must be integers",
    ):
        get_rate_limiter()

    get_rate_limiter.cache_clear()



    with pytest.raises(
        RuntimeError,
        match="Research rate-limit configuration must be integers",
    ):
        get_rate_limiter()

    get_rate_limiter.cache_clear()


def test_create_conversation_returns_user_scoped_conversation_id():
    conversation_store = MagicMock()
    conversation_store.create_conversation.return_value = "conv-123"

    with patch(
        "arxiv_pipeline.api.main.get_conversation_store",
        return_value=conversation_store,
    ):
        response = client.post(
            "/api/v1/conversations",
            headers={
                "Authorization": "Bearer test-token",
            },
        )

    assert response.status_code == 200

    body = response.json()

    assert body["conversation_id"] == "conv-123"

    conversation_store.create_conversation.assert_called_once_with(
        user_id="test-user",
    )


def test_send_conversation_message_uses_history_retrieval_synthesis_and_persistence():
    from arxiv_pipeline.synthesis.models import SynthesisResult

    conversation_store = MagicMock()
    retrieval_service = MagicMock()
    synthesis_service = MagicMock()

    conversation_store.get_messages.return_value = [
        {
            "role": "user",
            "content": "What approaches improve transformer attention efficiency?",
            "citations": [],
        },
        {
            "role": "assistant",
            "content": "Several approaches include KV-cache compression.",
            "citations": [],
        },
    ]

    paper = RetrievedPaper(
        paper_id="2606.03928",
        archive_id="arXiv_pdf_2606_001",
        year=2026,
        month=6,
        passage="KV-cache compression reduces memory usage.",
        arxiv_url="https://arxiv.org/abs/2606.03928",
        source_uri="s3://bucket/2606.03928.md",
        score=0.91,
    )

    retrieval_service.search.return_value = [paper]

    synthesis_service.synthesize.return_value = SynthesisResult(
        answer=(
            "KV-cache compression is useful for long-context inference "
            "[2606.03928]."
        ),
        cited_papers=[paper],
    )

    with (
        patch(
            "arxiv_pipeline.api.main.get_conversation_store",
            return_value=conversation_store,
        ),
        patch(
            "arxiv_pipeline.api.main.get_retrieval_service",
            return_value=retrieval_service,
        ),
        patch(
            "arxiv_pipeline.api.main.get_synthesis_service",
            return_value=synthesis_service,
        ),
    ):
        response = client.post(
            "/api/v1/conversations/conv-123/messages",
            headers={
                "Authorization": "Bearer test-token",
            },
            json={
                "message": (
                    "Which of these is useful for long-context inference?"
                ),
                "max_papers": 5,
            },
        )

    assert response.status_code == 200

    body = response.json()

    assert body["conversation_id"] == "conv-123"
    assert body["message"]["role"] == "assistant"
    assert (
        body["message"]["content"]
        == "KV-cache compression is useful for long-context inference "
        "[2606.03928]."
    )
    assert body["message"]["citations"][0]["paper_id"] == "2606.03928"

    conversation_store.get_messages.assert_called_once_with(
        user_id="test-user",
        conversation_id="conv-123",
        limit=20,
    )

    expected_user_history = [
        {
            "role": "user",
            "content": "What approaches improve transformer attention efficiency?",
            "citations": [],
        },
    ]

    retrieval_service.search.assert_called_once_with(
        query="Which of these is useful for long-context inference?",
        max_papers=5,
        conversation_history=expected_user_history,
    )

    synthesis_service.synthesize.assert_called_once_with(
        question="Which of these is useful for long-context inference?",
        papers=[paper],
        conversation_history=expected_user_history,
    )


def test_get_conversation_returns_authenticated_users_history():
    conversation_store = MagicMock()

    conversation_store.get_messages.return_value = [
        {
            "role": "user",
            "content": "What approaches improve transformer attention efficiency?",
            "citations": [],
        },
        {
            "role": "assistant",
            "content": "KV-cache compression can reduce memory usage.",
            "citations": [
                {
                    "paper_id": "2606.03928",
                    "arxiv_url": "https://arxiv.org/abs/2606.03928",
                    "passage": "Relevant passage.",
                }
            ],
        },
    ]

    with patch(
        "arxiv_pipeline.api.main.get_conversation_store",
        return_value=conversation_store,
    ):
        response = client.get(
            "/api/v1/conversations/conv-123",
            headers={
                "Authorization": "Bearer test-token",
            },
        )

    assert response.status_code == 200

    body = response.json()

    assert body["conversation_id"] == "conv-123"
    assert len(body["messages"]) == 2

    assert body["messages"][0]["role"] == "user"
    assert body["messages"][1]["role"] == "assistant"
    assert (
        body["messages"][1]["citations"][0]["paper_id"]
        == "2606.03928"
    )

    conversation_store.get_messages.assert_called_once_with(
        user_id="test-user",
        conversation_id="conv-123",
        limit=100,
    )


def test_get_conversation_returns_404_when_conversation_is_not_owned():
    conversation_store = MagicMock()
    conversation_store.conversation_exists.return_value = False

    with patch(
        "arxiv_pipeline.api.main.get_conversation_store",
        return_value=conversation_store,
    ):
        response = client.get(
            "/api/v1/conversations/conv-other-user",
            headers={
                "Authorization": "Bearer test-token",
            },
        )

    assert response.status_code == 404

    conversation_store.conversation_exists.assert_called_once_with(
        user_id="test-user",
        conversation_id="conv-other-user",
    )

    conversation_store.get_messages.assert_not_called()


def test_send_message_returns_404_when_conversation_is_not_owned():
    conversation_store = MagicMock()
    conversation_store.conversation_exists.return_value = False

    with patch(
        "arxiv_pipeline.api.main.get_conversation_store",
        return_value=conversation_store,
    ):
        response = client.post(
            "/api/v1/conversations/conv-other-user/messages",
            headers={
                "Authorization": "Bearer test-token",
            },
            json={
                "message": "Compare the approaches.",
                "max_papers": 5,
            },
        )

    assert response.status_code == 404

    conversation_store.conversation_exists.assert_called_once_with(
        user_id="test-user",
        conversation_id="conv-other-user",
    )

    conversation_store.get_messages.assert_not_called()


def test_send_conversation_message_returns_503_when_generated_citations_remain_invalid():
    from arxiv_pipeline.synthesis.service import CitationValidationError

    conversation_store = MagicMock()
    retrieval_service = MagicMock()
    synthesis_service = MagicMock()

    conversation_store.get_messages.return_value = []

    paper = RetrievedPaper(
        paper_id="2606.11111",
        archive_id="arXiv_pdf_2606_001",
        year=2026,
        month=6,
        passage="Relevant research evidence.",
        arxiv_url="https://arxiv.org/abs/2606.11111",
        source_uri="s3://bucket/2606.11111.md",
        score=0.91,
    )

    retrieval_service.search.return_value = [paper]

    synthesis_service.synthesize.side_effect = CitationValidationError(
        "quantitative claim contains no citation"
    )

    with (
        patch(
            "arxiv_pipeline.api.main.get_conversation_store",
            return_value=conversation_store,
        ),
        patch(
            "arxiv_pipeline.api.main.get_retrieval_service",
            return_value=retrieval_service,
        ),
        patch(
            "arxiv_pipeline.api.main.get_synthesis_service",
            return_value=synthesis_service,
        ),
    ):
        response = client.post(
            "/api/v1/conversations/conv-123/messages",
            headers={
                "Authorization": "Bearer test-token",
            },
            json={
                "message": "Which approach works well for short context?",
                "max_papers": 5,
            },
        )

    assert response.status_code == 503

    body = response.json()

    assert body["error"]["code"] == "RESEARCH_UNAVAILABLE"
    assert (
        body["error"]["message"]
        == "Research service is temporarily unavailable."
    )

    assert body["request_id"]
    assert response.headers["X-Request-ID"] == body["request_id"]
    assert response.headers["Cache-Control"] == "no-store"

    assert "quantitative claim contains no citation" not in response.text

    conversation_store.add_message.assert_called_once_with(
        user_id="test-user",
        conversation_id="conv-123",
        role="user",
        content="Which approach works well for short context?",
        citations=[],
    )


def test_send_conversation_message_passes_only_user_history_to_synthesis():
    from arxiv_pipeline.synthesis.models import SynthesisResult

    conversation_store = MagicMock()
    retrieval_service = MagicMock()
    synthesis_service = MagicMock()

    conversation_store.get_messages.return_value = [
        {
            "role": "user",
            "content": "What approaches improve transformer attention efficiency?",
            "citations": [],
        },
        {
            "role": "assistant",
            "content": (
                "Sparse attention is useful [2606.05208]."
            ),
            "citations": [],
        },
        {
            "role": "user",
            "content": "Which works best for long-context inference?",
            "citations": [],
        },
        {
            "role": "assistant",
            "content": (
                "Sparse attention works well [2606.04511]."
            ),
            "citations": [],
        },
    ]

    paper = RetrievedPaper(
        paper_id="2606.11111",
        archive_id="arXiv_pdf_2606_001",
        year=2026,
        month=6,
        passage="Relevant current-turn evidence.",
        arxiv_url="https://arxiv.org/abs/2606.11111",
        source_uri="s3://bucket/2606.11111.md",
        score=0.91,
    )

    retrieval_service.search.return_value = [paper]

    synthesis_service.synthesize.return_value = SynthesisResult(
        answer="Current evidence supports this approach [2606.11111].",
        cited_papers=[paper],
    )

    with (
        patch(
            "arxiv_pipeline.api.main.get_conversation_store",
            return_value=conversation_store,
        ),
        patch(
            "arxiv_pipeline.api.main.get_retrieval_service",
            return_value=retrieval_service,
        ),
        patch(
            "arxiv_pipeline.api.main.get_synthesis_service",
            return_value=synthesis_service,
        ),
    ):
        response = client.post(
            "/api/v1/conversations/conv-123/messages",
            headers={
                "Authorization": "Bearer test-token",
            },
            json={
                "message": "Which works well for short-context inference?",
                "max_papers": 5,
            },
        )

    assert response.status_code == 200

    synthesis_service.synthesize.assert_called_once_with(
        question="Which works well for short-context inference?",
        papers=[paper],
        conversation_history=[
            {
                "role": "user",
                "content": (
                    "What approaches improve transformer attention efficiency?"
                ),
                "citations": [],
            },
            {
                "role": "user",
                "content": (
                    "Which works best for long-context inference?"
                ),
                "citations": [],
            },
        ],
    )


def test_send_conversation_message_returns_429_when_rate_limit_is_exceeded():
    conversation_store = MagicMock()
    conversation_store.conversation_exists.return_value = True

    rate_limiter = MagicMock()
    rate_limiter.allow.return_value = False

    retrieval_service = MagicMock()
    synthesis_service = MagicMock()

    with (
        patch(
            "arxiv_pipeline.api.main.get_conversation_store",
            return_value=conversation_store,
        ),
        patch(
            "arxiv_pipeline.api.main.get_rate_limiter",
            return_value=rate_limiter,
        ),
        patch(
            "arxiv_pipeline.api.main.get_retrieval_service",
            return_value=retrieval_service,
        ),
        patch(
            "arxiv_pipeline.api.main.get_synthesis_service",
            return_value=synthesis_service,
        ),
    ):
        response = client.post(
            "/api/v1/conversations/conv-123/messages",
            headers={
                "Authorization": "Bearer test-token",
            },
            json={
                "message": "Which approach is most efficient?",
                "max_papers": 5,
            },
        )

    assert response.status_code == 429

    body = response.json()

    assert body["error"] == {
        "code": "RATE_LIMIT_EXCEEDED",
        "message": "Too many research requests. Please try again later.",
    }
    assert body["request_id"]
    assert response.headers["X-Request-ID"] == body["request_id"]
    assert response.headers["Cache-Control"] == "no-store"

    rate_limiter.allow.assert_called_once_with(
        user_id="test-user",
    )

    conversation_store.get_messages.assert_not_called()
    retrieval_service.search.assert_not_called()
    synthesis_service.synthesize.assert_not_called()


def test_send_conversation_message_returns_500_when_rate_limiter_fails():
    conversation_store = MagicMock()
    conversation_store.conversation_exists.return_value = True

    rate_limiter = MagicMock()
    rate_limiter.allow.side_effect = RuntimeError(
        "sensitive rate limiter failure"
    )

    retrieval_service = MagicMock()

    with (
        patch(
            "arxiv_pipeline.api.main.get_conversation_store",
            return_value=conversation_store,
        ),
        patch(
            "arxiv_pipeline.api.main.get_rate_limiter",
            return_value=rate_limiter,
        ),
        patch(
            "arxiv_pipeline.api.main.get_retrieval_service",
            return_value=retrieval_service,
        ),
    ):
        response = client.post(
            "/api/v1/conversations/conv-123/messages",
            headers={
                "Authorization": "Bearer test-token",
            },
            json={
                "message": "Which approach is most efficient?",
                "max_papers": 5,
            },
        )

    assert response.status_code == 500

    body = response.json()

    assert body["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "An unexpected internal error occurred.",
    }
    assert body["request_id"]
    assert response.headers["X-Request-ID"] == body["request_id"]
    assert response.headers["Cache-Control"] == "no-store"

    rate_limiter.allow.assert_called_once_with(
        user_id="test-user",
    )

    conversation_store.get_messages.assert_not_called()
    retrieval_service.search.assert_not_called()


def test_send_conversation_message_allows_user_within_rate_limit():
    from arxiv_pipeline.synthesis.models import SynthesisResult

    conversation_store = MagicMock()
    conversation_store.conversation_exists.return_value = True
    conversation_store.get_messages.return_value = []

    rate_limiter = MagicMock()
    rate_limiter.allow.return_value = True

    paper = RetrievedPaper(
        paper_id="2606.12345",
        archive_id="arXiv_pdf_2606_001",
        year=2026,
        month=6,
        passage="Relevant transformer passage.",
        arxiv_url="https://arxiv.org/abs/2606.12345",
        source_uri="s3://bucket/2606.12345.md",
        score=0.91,
    )

    retrieval_service = MagicMock()
    retrieval_service.search.return_value = [paper]

    synthesis_service = MagicMock()
    synthesis_service.synthesize.return_value = SynthesisResult(
        answer="Sparse attention can improve efficiency [2606.12345].",
        cited_papers=[paper],
    )

    with (
        patch(
            "arxiv_pipeline.api.main.get_conversation_store",
            return_value=conversation_store,
        ),
        patch(
            "arxiv_pipeline.api.main.get_rate_limiter",
            return_value=rate_limiter,
        ),
        patch(
            "arxiv_pipeline.api.main.get_retrieval_service",
            return_value=retrieval_service,
        ),
        patch(
            "arxiv_pipeline.api.main.get_synthesis_service",
            return_value=synthesis_service,
        ),
    ):
        response = client.post(
            "/api/v1/conversations/conv-123/messages",
            headers={
                "Authorization": "Bearer test-token",
            },
            json={
                "message": "Which approach is most efficient?",
                "max_papers": 5,
            },
        )

    assert response.status_code == 200

    rate_limiter.allow.assert_called_once_with(
        user_id="test-user",
    )

    retrieval_service.search.assert_called_once_with(
        query="Which approach is most efficient?",
        max_papers=5,
        conversation_history=[],
    )

    synthesis_service.synthesize.assert_called_once_with(
        question="Which approach is most efficient?",
        papers=[paper],
        conversation_history=[],
    )
