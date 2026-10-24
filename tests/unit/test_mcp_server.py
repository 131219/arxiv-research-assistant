from unittest.mock import MagicMock, patch
from arxiv_pipeline.retrieval.models import RetrievedPaper

import pytest

from arxiv_pipeline.mcp.models import SearchPapersResponse
from arxiv_pipeline.mcp.server import (
    get_bedrock_service,
    get_retrieval_service,
    normalize_result,
    search_papers,
)


@pytest.fixture(autouse=True)
def clear_cached_service():
    get_bedrock_service.cache_clear()
    get_retrieval_service.cache_clear()
    yield
    get_retrieval_service.cache_clear()
    get_bedrock_service.cache_clear()


def test_normalize_result_returns_typed_model_without_raw_metadata():
    result = {
        "content": {
            "text": "Relevant passage about transformers."
        },
        "location": {
            "s3Location": {
                "uri": "s3://bucket/paper.md"
            }
        },
        "score": 0.91,
        "metadata": {
            "paper_id": "2606.12345",
            "archive_id": "arXiv_pdf_2606_001",
            "target_year": 2026,
            "target_month": 6,
            "internal_field": "must-not-leak",
        },
    }

    service = MagicMock()
    service._extract_text.return_value = (
        "Relevant passage about transformers."
    )
    service._extract_source_uri.return_value = (
        "s3://bucket/paper.md"
    )

    with patch(
        "arxiv_pipeline.mcp.server.get_bedrock_service",
        return_value=service,
    ):
        normalized = normalize_result(result)

    assert normalized.paper_id == "2606.12345"
    assert normalized.archive_id == "arXiv_pdf_2606_001"
    assert normalized.year == 2026
    assert normalized.month == 6
    assert normalized.score == 0.91
    assert normalized.arxiv_url == (
        "https://arxiv.org/abs/2606.12345"
    )

    dumped = normalized.model_dump()

    assert "metadata" not in dumped
    assert "internal_field" not in dumped


def test_search_papers_returns_typed_response():
    service = MagicMock()

    service.retrieve.return_value = [
        {
            "metadata": {
                "paper_id": "2606.12345",
                "archive_id": "arXiv_pdf_2606_001",
                "target_year": 2026,
                "target_month": 6,
            },
            "score": 0.88,
        }
    ]

    service._extract_text.return_value = "A retrieved passage."
    service._extract_source_uri.return_value = (
        "s3://bucket/2606.12345.md"
    )

    with patch(
        "arxiv_pipeline.mcp.server.get_bedrock_service",
        return_value=service,
    ):
        response = search_papers(
            query="transformer attention",
            top_k=5,
        )

    assert isinstance(response, SearchPapersResponse)
    assert response.query == "transformer attention"
    assert response.result_count == 1
    assert response.results[0].paper_id == "2606.12345"

    service.retrieve.assert_called_once_with(
        question="transformer attention",
        number_of_results=15,
    )


def test_search_papers_delegates_to_shared_retrieval_service():
    retrieval_service = MagicMock()

    retrieval_service.search.return_value = [
        RetrievedPaper(
            paper_id="2606.12345",
            archive_id="arXiv_pdf_2606_001",
            year=2026,
            month=6,
            passage="A retrieved passage.",
            arxiv_url="https://arxiv.org/abs/2606.12345",
            source_uri="s3://bucket/2606.12345.md",
            score=0.88,
        )
    ]

    with patch(
        "arxiv_pipeline.mcp.server.get_retrieval_service",
        return_value=retrieval_service,
    ):
        response = search_papers(
            query="transformer attention",
            top_k=5,
        )

    retrieval_service.search.assert_called_once_with(
        query="transformer attention",
        max_papers=5,
    )

    assert response.result_count == 1
    assert response.results[0].paper_id == "2606.12345"
    assert response.results[0].text == "A retrieved passage."


@pytest.mark.parametrize(
    "query",
    [
        "",
        "   ",
    ],
)
def test_search_papers_rejects_empty_query(query):
    with pytest.raises(
        ValueError,
        match="query must not be empty",
    ):
        search_papers(
            query=query,
            top_k=5,
        )


@pytest.mark.parametrize(
    "top_k",
    [
        0,
        21,
    ],
)
def test_search_papers_rejects_invalid_top_k(top_k):
    with pytest.raises(
        ValueError,
        match="top_k must be between 1 and 20",
    ):
        search_papers(
            query="graph neural networks",
            top_k=top_k,
        )


def test_search_papers_deduplicates_by_paper_id():
    service = MagicMock()

    service.retrieve.return_value = [
        {
            "metadata": {
                "paper_id": "2606.04032",
            },
            "score": 0.55,
        },
        {
            "metadata": {
                "paper_id": "2606.00111",
            },
            "score": 0.47,
        },
        {
            "metadata": {
                "paper_id": "2606.04032",
            },
            "score": 0.42,
        },
        {
            "metadata": {
                "paper_id": "2606.00892",
            },
            "score": 0.40,
        },
    ]

    service._extract_text.return_value = "Retrieved passage."
    service._extract_source_uri.return_value = None

    with patch(
        "arxiv_pipeline.mcp.server.get_bedrock_service",
        return_value=service,
    ):
        response = search_papers(
            query="transformer attention",
            top_k=3,
        )

    assert response.result_count == 3

    assert [
        result.paper_id
        for result in response.results
    ] == [
        "2606.04032",
        "2606.00111",
        "2606.00892",
    ]

    assert response.results[0].score == 0.55

    service.retrieve.assert_called_once_with(
        question="transformer attention",
        number_of_results=9,
    )
