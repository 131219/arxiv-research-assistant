from unittest.mock import MagicMock

import pytest

from arxiv_pipeline.retrieval.models import RetrievedPaper
from arxiv_pipeline.synthesis.service import (
    CitationValidationError,
    SynthesisService,
)


def make_paper(paper_id: str) -> RetrievedPaper:
    return RetrievedPaper(
        paper_id=paper_id,
        passage=f"Evidence from {paper_id}.",
        arxiv_url=f"https://arxiv.org/abs/{paper_id}",
    )


def test_validate_answer_keeps_only_cited_papers_in_first_appearance_order():
    service = SynthesisService()

    papers = [
        make_paper("2606.11111"),
        make_paper("2606.22222"),
        make_paper("2606.33333"),
    ]

    result = service.validate_answer(
        answer=(
            "Sparse attention reduces computation [2606.22222]. "
            "Another technique improves memory use [2606.11111]. "
            "The sparse approach is discussed again [2606.22222]."
        ),
        papers=papers,
    )

    assert result.answer.startswith("Sparse attention")

    assert [
        paper.paper_id
        for paper in result.cited_papers
    ] == [
        "2606.22222",
        "2606.11111",
    ]


def test_validate_answer_rejects_unknown_citation():
    service = SynthesisService()

    papers = [
        make_paper("2606.11111"),
    ]

    with pytest.raises(
        CitationValidationError,
        match="unsupported citation",
    ):
        service.validate_answer(
            answer=(
                "This claim cites an unknown paper "
                "[9999.99999]."
            ),
            papers=papers,
        )


def test_validate_answer_rejects_answer_without_citations():
    service = SynthesisService()

    papers = [
        make_paper("2606.11111"),
    ]

    with pytest.raises(
        CitationValidationError,
        match="no citations",
    ):
        service.validate_answer(
            answer="This answer contains no research citations.",
            papers=papers,
        )


def test_synthesize_uses_generation_backend_and_validates_answer():
    backend = MagicMock()

    backend.generate.return_value = (
        "Sparse attention reduces computation [2606.11111]."
    )

    service = SynthesisService(backend=backend)

    papers = [
        make_paper("2606.11111"),
        make_paper("2606.22222"),
    ]

    result = service.synthesize(
        question="How can transformer attention be made more efficient?",
        papers=papers,
    )

    backend.generate.assert_called_once_with(
        question="How can transformer attention be made more efficient?",
        papers=papers,
    )

    assert result.answer == (
        "Sparse attention reduces computation [2606.11111]."
    )

    assert [
        paper.paper_id
        for paper in result.cited_papers
    ] == [
        "2606.11111",
    ]


def test_validate_answer_ignores_non_citation_bracketed_text():
    service = SynthesisService()

    papers = [
        make_paper("2606.11111"),
    ]

    result = service.validate_answer(
        answer=(
            "Sparse attention reduces computation "
            "[2606.11111]. See [note] for additional context."
        ),
        papers=papers,
    )

    assert [
        paper.paper_id
        for paper in result.cited_papers
    ] == [
        "2606.11111",
    ]


def test_validate_answer_removes_source_local_numeric_references():
    service = SynthesisService()

    papers = [
        make_paper("2606.02836"),
    ]

    result = service.validate_answer(
        answer=(
            "MobileBERT [7] and SqueezeBERT [19] improve latency "
            "[2606.02836]."
        ),
        papers=papers,
    )

    assert result.answer == (
        "MobileBERT and SqueezeBERT improve latency "
        "[2606.02836]."
    )

    assert [
        paper.paper_id
        for paper in result.cited_papers
    ] == [
        "2606.02836",
    ]


def test_validate_answer_rejects_uncited_numbered_research_item():
    service = SynthesisService()

    papers = [
        make_paper("2606.11111"),
        make_paper("2606.22222"),
    ]

    answer = """Approaches include:

1. Sparse attention reduces computation [2606.11111].

2. Model compression reduces inference cost.

3. Cache optimization reduces repeated work [2606.22222].
"""

    with pytest.raises(
        CitationValidationError,
        match="numbered research item contains no citation",
    ):
        service.validate_answer(
            answer=answer,
            papers=papers,
        )


def test_validate_answer_rejects_uncited_quantitative_claim():
    service = SynthesisService()

    papers = [
        make_paper("2606.11111"),
    ]

    with pytest.raises(
        CitationValidationError,
        match="quantitative claim contains no citation",
    ):
        service.validate_answer(
            answer=(
                "The method improves runtime by 60%. "
                "The overall approach is supported [2606.11111]."
            ),
            papers=papers,
        )


def test_synthesize_passes_conversation_history_to_generation_backend():
    from unittest.mock import MagicMock

    from arxiv_pipeline.retrieval.models import RetrievedPaper
    from arxiv_pipeline.synthesis.service import SynthesisService

    backend = MagicMock()
    backend.generate.return_value = (
        "Long-context inference benefits from KV-cache compression "
        "[2606.03928]."
    )

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

    history = [
        {
            "role": "user",
            "content": "What approaches improve transformer attention efficiency?",
        },
        {
            "role": "assistant",
            "content": "Several approaches include KV-cache compression.",
        },
    ]

    service = SynthesisService(backend=backend)

    service.synthesize(
        question="Which of these is useful for long-context inference?",
        papers=[paper],
        conversation_history=history,
    )

    backend.generate.assert_called_once_with(
        question="Which of these is useful for long-context inference?",
        papers=[paper],
        conversation_history=history,
    )


def test_synthesize_retries_once_after_citation_validation_failure():
    backend = MagicMock()

    backend.generate.side_effect = [
        (
            "The method improves runtime by 60%. "
            "The approach is supported [2606.11111]."
        ),
        (
            "The method improves runtime by 60% [2606.11111]."
        ),
    ]

    service = SynthesisService(backend=backend)

    papers = [
        make_paper("2606.11111"),
    ]

    result = service.synthesize(
        question="Which approach works well for short context?",
        papers=papers,
    )

    assert result.answer == (
        "The method improves runtime by 60% [2606.11111]."
    )

    assert backend.generate.call_count == 2

    first_call = backend.generate.call_args_list[0]
    second_call = backend.generate.call_args_list[1]

    assert first_call.kwargs == {
        "question": "Which approach works well for short context?",
        "papers": papers,
    }

    assert second_call.kwargs == {
        "question": "Which approach works well for short context?",
        "papers": papers,
        "citation_retry": True,
    }
