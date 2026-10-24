from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from arxiv_pipeline.api.bedrock_service import (
    BedrockKnowledgeBaseService,
)
from arxiv_pipeline.retrieval.service import RetrievalUnavailableError


def make_service() -> BedrockKnowledgeBaseService:
    service = BedrockKnowledgeBaseService.__new__(
        BedrockKnowledgeBaseService
    )

    service.retrieve = MagicMock()
    service.generate_answer = MagicMock()

    return service


def test_ask_normalizes_retrieval_metadata_into_research_citation():
    service = make_service()

    service.retrieve.return_value = [
        {
            "content": {
                "text": "Relevant transformer passage."
            },
            "location": {
                "s3Location": {
                    "uri": (
                        "https://example.com/"
                        "processed/arXiv_pdf_2606_030/"
                        "2606.04032.md"
                    )
                }
            },
            "score": 0.5473,
            "metadata": {
                "paper_id": "2606.04032",
                "archive_id": "arXiv_pdf_2606_030",
                "target_year": 2026.0,
                "target_month": 6.0,
                "_chunk_id": "internal-value",
            },
        }
    ]

    service.generate_answer.return_value = (
        "Transformers use self-attention [2606.04032]."
    )

    answer, citations = service.ask(
        question="How does transformer attention work?",
        number_of_results=5,
    )

    assert answer == (
        "Transformers use self-attention [2606.04032]."
    )

    assert len(citations) == 1

    citation = citations[0]

    assert citation.paper_id == "2606.04032"
    assert citation.archive_id == "arXiv_pdf_2606_030"
    assert citation.year == 2026
    assert citation.month == 6
    assert citation.score == 0.5473
    assert citation.passage == (
        "Relevant transformer passage."
    )

    dumped = citation.model_dump()

    assert "_chunk_id" not in dumped
    assert "metadata" not in dumped


def test_ask_rejects_retrieval_result_without_paper_id():
    service = make_service()

    service.retrieve.return_value = [
        {
            "content": {
                "text": "Relevant passage."
            },
            "metadata": {
                "archive_id": "arXiv_pdf_2606_030",
                "target_year": 2026.0,
                "target_month": 6.0,
            },
        }
    ]

    service.generate_answer.return_value = "Answer"

    with pytest.raises(
        RuntimeError,
        match="Retrieved Bedrock result is missing paper_id",
    ):
        service.ask(
            question="Explain transformers",
            number_of_results=5,
        )

    service.generate_answer.assert_not_called()


def test_build_context_uses_paper_id_for_citations():
    service = BedrockKnowledgeBaseService.__new__(
        BedrockKnowledgeBaseService
    )

    results = [
        {
            "content": {
                "text": "Transformer attention passage."
            },
            "location": {
                "s3Location": {
                    "uri": "s3://bucket/2606.04032.md"
                }
            },
            "metadata": {
                "paper_id": "2606.04032",
            },
        }
    ]

    context = service._build_context(results)

    assert "[Paper 2606.04032]" in context
    assert "s3://bucket/2606.04032.md" in context
    assert "Transformer attention passage." in context
    assert "[Source 1]" not in context


def test_bedrock_clients_use_bounded_timeout_and_retry_configuration(monkeypatch):
    client = MagicMock()

    monkeypatch.setattr(
        "arxiv_pipeline.api.bedrock_service.boto3.client",
        client,
    )
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)

    BedrockKnowledgeBaseService()

    client.assert_called_once()

    _, kwargs = client.call_args

    config = kwargs["config"]

    assert config.connect_timeout == 3
    assert config.read_timeout == 10
    assert config.retries["max_attempts"] == 3
    assert config.retries["mode"] == "standard"


def test_retrieve_translates_throttling_into_retrieval_unavailable():
    service = BedrockKnowledgeBaseService.__new__(
        BedrockKnowledgeBaseService
    )

    service.knowledge_base_id = "test-kb"
    service.agent_runtime = MagicMock()

    service.agent_runtime.retrieve.side_effect = ClientError(
        {
            "Error": {
                "Code": "ThrottlingException",
                "Message": "Rate exceeded",
            }
        },
        "Retrieve",
    )

    with pytest.raises(
        RetrievalUnavailableError,
        match="Bedrock retrieval is temporarily unavailable",
    ):
        service.retrieve(
            question="transformer attention",
            number_of_results=5,
        )


def test_retrieve_translates_service_unavailable_into_retrieval_unavailable():
    service = BedrockKnowledgeBaseService.__new__(
        BedrockKnowledgeBaseService
    )

    service.knowledge_base_id = "test-kb"
    service.agent_runtime = MagicMock()

    service.agent_runtime.retrieve.side_effect = ClientError(
        {
            "Error": {
                "Code": "ServiceUnavailableException",
                "Message": "Service temporarily unavailable",
            }
        },
        "Retrieve",
    )

    with pytest.raises(
        RetrievalUnavailableError,
        match="Bedrock retrieval is temporarily unavailable",
    ):
        service.retrieve(
            question="transformer attention",
            number_of_results=5,
        )
