from unittest.mock import MagicMock

from arxiv_pipeline.retrieval.models import RetrievedPaper
from arxiv_pipeline.retrieval.service import (
    MalformedRetrievalResultError,
    PaperRetrievalService,
    RetrievalError,
)

def test_search_overfetches_and_returns_ranked_unique_papers():
    backend = MagicMock()

    backend.retrieve.return_value = [
        {
            "content": {"text": "Highest-ranked passage for paper A."},
            "metadata": {
                "paper_id": "2606.04032",
                "archive_id": "arXiv_pdf_2606_030",
                "target_year": 2026,
                "target_month": 6,
            },
            "score": 0.55,
        },
        {
            "content": {"text": "Passage for paper B."},
            "metadata": {
                "paper_id": "2606.00111",
            },
            "score": 0.47,
        },
        {
            "content": {"text": "Lower-ranked duplicate passage for paper A."},
            "metadata": {
                "paper_id": "2606.04032",
            },
            "score": 0.42,
        },
        {
            "content": {"text": "Passage for paper C."},
            "metadata": {
                "paper_id": "2606.00892",
            },
            "score": 0.40,
        },
    ]

    service = PaperRetrievalService(backend=backend)

    results = service.search(
        query="transformer attention",
        max_papers=3,
    )

    backend.retrieve.assert_called_once_with(
        question="transformer attention",
        number_of_results=9,
    )

    assert all(isinstance(result, RetrievedPaper) for result in results)

    assert [result.paper_id for result in results] == [
        "2606.04032",
        "2606.00111",
        "2606.00892",
    ]

    assert results[0].passage == ("Highest-ranked passage for paper A.")


def test_search_raises_controlled_error_for_malformed_metadata():
    backend = MagicMock()

    backend.retrieve.return_value = [
        {
            "content": {"text": "Some passage."},
            "metadata": "not-a-dictionary",
        }
    ]

    service = PaperRetrievalService(backend=backend)

    try:
        service.search(
            query="transformer attention",
            max_papers=3,
        )
    except MalformedRetrievalResultError:
        pass
    else:
        raise AssertionError("Expected MalformedRetrievalResultError")


def test_search_raises_controlled_error_for_malformed_content():
    backend = MagicMock()

    backend.retrieve.return_value = [
        {
            "content": "not-a-dictionary",
            "metadata": {
                "paper_id": "2606.04032",
            },
        }
    ]

    service = PaperRetrievalService(backend=backend)

    try:
        service.search(
            query="transformer attention",
            max_papers=3,
        )
    except MalformedRetrievalResultError:
        pass
    else:
        raise AssertionError("Expected MalformedRetrievalResultError")


def test_search_raises_controlled_error_for_malformed_location():
    backend = MagicMock()

    backend.retrieve.return_value = [
        {
            "content": {"text": "Some passage."},
            "metadata": {
                "paper_id": "2606.04032",
            },
            "location": "not-a-dictionary",
        }
    ]

    service = PaperRetrievalService(backend=backend)

    try:
        service.search(
            query="transformer attention",
            max_papers=3,
        )
    except MalformedRetrievalResultError:
        pass
    else:
        raise AssertionError("Expected MalformedRetrievalResultError")


def test_search_raises_controlled_error_for_malformed_s3_location():
    backend = MagicMock()

    backend.retrieve.return_value = [
        {
            "content": {"text": "Some passage."},
            "metadata": {
                "paper_id": "2606.04032",
            },
            "location": {
                "s3Location": "not-a-dictionary",
            },
        }
    ]

    service = PaperRetrievalService(backend=backend)

    try:
        service.search(
            query="transformer attention",
            max_papers=3,
        )
    except MalformedRetrievalResultError:
        pass
    else:
        raise AssertionError("Expected MalformedRetrievalResultError")


def test_search_raises_controlled_error_when_paper_id_is_missing():
    backend = MagicMock()

    backend.retrieve.return_value = [
        {
            "content": {"text": "Some passage."},
            "metadata": {},
        }
    ]

    service = PaperRetrievalService(backend=backend)

    try:
        service.search(
            query="transformer attention",
            max_papers=3,
        )
    except MalformedRetrievalResultError:
        pass
    else:
        raise AssertionError("Expected MalformedRetrievalResultError")


def test_search_raises_controlled_error_when_paper_id_is_not_a_string():
    backend = MagicMock()

    backend.retrieve.return_value = [
        {
            "content": {"text": "Some passage."},
            "metadata": {
                "paper_id": ["2606.04032"],
            },
        }
    ]

    service = PaperRetrievalService(backend=backend)

    try:
        service.search(
            query="transformer attention",
            max_papers=3,
        )
    except MalformedRetrievalResultError:
        pass
    else:
        raise AssertionError("Expected MalformedRetrievalResultError")


def test_search_wraps_backend_failure_in_retrieval_error():
    backend = MagicMock()

    backend.retrieve.side_effect = RuntimeError("bedrock unavailable")

    service = PaperRetrievalService(backend=backend)

    try:
        service.search(
            query="transformer attention",
            max_papers=3,
        )
    except RetrievalError as exc:
        assert str(exc) == "paper retrieval failed"
    else:
        raise AssertionError("Expected RetrievalError")


def test_search_refines_broad_attention_efficiency_query_before_backend_call():
    backend = MagicMock()
    backend.retrieve.return_value = []

    service = PaperRetrievalService(backend=backend)

    original_query = (
        "What approaches improve transformer attention efficiency?"
    )

    service.search(
        query=original_query,
        max_papers=5,
    )

    backend.retrieve.assert_called_once()

    _, kwargs = backend.retrieve.call_args

    refined_query = kwargs["question"]

    assert refined_query != original_query
    assert "attention" in refined_query.lower()
    assert (
        "computational" in refined_query.lower()
        or "memory" in refined_query.lower()
    )


def test_search_leaves_specific_kv_cache_query_unchanged():
    backend = MagicMock()
    backend.retrieve.return_value = []

    service = PaperRetrievalService(backend=backend)

    original_query = (
        "What techniques reduce KV-cache memory "
        "during transformer inference?"
    )

    service.search(
        query=original_query,
        max_papers=5,
    )

    backend.retrieve.assert_called_once_with(
        question=original_query,
        number_of_results=15,
    )


def test_search_uses_previous_user_context_for_follow_up_query():
    backend = MagicMock()
    backend.retrieve.return_value = []

    service = PaperRetrievalService(backend=backend)

    service.search(
        query="Which of these works best for long-context inference?",
        max_papers=5,
        conversation_history=[
            {
                "role": "user",
                "content": (
                    "What approaches improve transformer attention efficiency?"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "Several approaches include sparse attention "
                    "and KV-cache compression."
                ),
            },
        ],
    )

    backend.retrieve.assert_called_once()

    _, kwargs = backend.retrieve.call_args
    retrieval_query = kwargs["question"]

    assert (
        "What approaches improve transformer attention efficiency?"
        in retrieval_query
    )
    assert (
        "Which of these works best for long-context inference?"
        in retrieval_query
    )
    assert "computational cost" in retrieval_query
    assert "memory usage" in retrieval_query
